# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
One-time backfill: replace each project's default-seeded States with the
client's real department workflow (see the department-workflow Google
Sheet), reassigning existing Issues to the new state sharing the same
StateGroup so nothing is orphaned, then removing the old states.

    python manage.py apply_department_workflows --mapping-file mapping.json
    python manage.py apply_department_workflows --mapping-file mapping.json --apply

Defaults to a dry run: everything is computed and printed, but rolled back
before commit, unless --apply is passed.

--mapping-file is a small JSON file: {"<project name>": "<workflow key>"}
mapping specific projects to one of the 4 department workflows below. Any
project NOT listed gets the new global DEFAULT_STATES (the "all other
projects" row) — which is what a brand new project gets automatically now
anyway, so for most existing projects this step just swaps the old 6
generic states for the new 9.
"""

import json

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from plane.db.models import Issue, Project, State
from plane.db.models.state import DEFAULT_STATES, StateGroup

# The triage-group state is not part of the client's visible workflow, but
# is required (with no auto-create fallback) by the Intake feature. Appended
# to every department workflow below, same as DEFAULT_STATES already does.
TRIAGE_STATE_SPEC = {"name": "Triage", "color": "#4E5355", "group": StateGroup.TRIAGE.value}

DEPARTMENT_WORKFLOWS = {
    "public_notice": [
        {"name": "Client consultation/Documents Received", "color": "#60646C", "group": StateGroup.BACKLOG.value, "default": True},
        {"name": "Drafting", "color": "#60646C", "group": StateGroup.UNSTARTED.value},
        {"name": "Quotation finalize/Invoice", "color": "#F59E0B", "group": StateGroup.STARTED.value},
        {"name": "Sent for Approval", "color": "#F59E0B", "group": StateGroup.STARTED.value},
        {"name": "Draft verified", "color": "#F59E0B", "group": StateGroup.STARTED.value},
        {"name": "Publish/Close", "color": "#46A758", "group": StateGroup.COMPLETED.value},
        TRIAGE_STATE_SPEC,
    ],
    "legal_notice": [
        {"name": "Client consultation/Documents Received", "color": "#60646C", "group": StateGroup.BACKLOG.value, "default": True},
        {"name": "Drafting", "color": "#60646C", "group": StateGroup.UNSTARTED.value},
        {"name": "Invoice", "color": "#F59E0B", "group": StateGroup.STARTED.value},
        {"name": "Sent for Approval", "color": "#F59E0B", "group": StateGroup.STARTED.value},
        {"name": "Draft verified", "color": "#F59E0B", "group": StateGroup.STARTED.value},
        {"name": "Post/Close", "color": "#46A758", "group": StateGroup.COMPLETED.value},
        TRIAGE_STATE_SPEC,
    ],
    "document_review": [
        {"name": "First meeting-Document received", "color": "#60646C", "group": StateGroup.BACKLOG.value, "default": True},
        {"name": "Shared quotation", "color": "#60646C", "group": StateGroup.UNSTARTED.value},
        {"name": "Review in progress", "color": "#F59E0B", "group": StateGroup.STARTED.value},
        {"name": "Client Meeting", "color": "#F59E0B", "group": StateGroup.STARTED.value},
        {"name": "Pending for Payment", "color": "#F59E0B", "group": StateGroup.STARTED.value},
        {"name": "Completed", "color": "#46A758", "group": StateGroup.COMPLETED.value},
        TRIAGE_STATE_SPEC,
    ],
    "agreements": [
        {"name": "Client consultation/Documents Received", "color": "#60646C", "group": StateGroup.BACKLOG.value, "default": True},
        {"name": "Drafting", "color": "#60646C", "group": StateGroup.UNSTARTED.value},
        {"name": "Invoice", "color": "#F59E0B", "group": StateGroup.STARTED.value},
        {"name": "Sent for Approval", "color": "#F59E0B", "group": StateGroup.STARTED.value},
        {"name": "Draft verified and Notarised", "color": "#F59E0B", "group": StateGroup.STARTED.value},
        {"name": "Handedover", "color": "#46A758", "group": StateGroup.COMPLETED.value},
        TRIAGE_STATE_SPEC,
    ],
}

# Reassignment fallback order when an old state's group has no direct match
# in the new workflow (this only affects "cancelled" — none of the 5 stage
# lists model a cancelled stage). Walk backwards from "started" so a
# cancelled item lands on the last active-work stage, never silently in
# "completed" (which would misreport it as finished) or lost entirely.
GROUP_FALLBACK_ORDER = [StateGroup.STARTED.value, StateGroup.UNSTARTED.value, StateGroup.BACKLOG.value, StateGroup.COMPLETED.value]


class Command(BaseCommand):
    help = (
        "One-time backfill of the client's department workflows onto existing projects' States, "
        "reassigning issues by StateGroup before removing the old states. Dry-run by default."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--mapping-file",
            type=str,
            required=True,
            help=f"JSON file: {{\"<project name>\": \"<workflow key>\"}}. Valid workflow keys: "
            f"{', '.join(DEPARTMENT_WORKFLOWS.keys())}. Unlisted projects get the new global default.",
        )
        parser.add_argument("--workspace-slug", type=str, default=None, help="Limit to one workspace.")
        parser.add_argument("--apply", action="store_true", help="Actually write changes. Omit for a dry run.")

    def handle(self, *args, **options):
        apply_changes = options["apply"]
        with open(options["mapping_file"], encoding="utf-8") as f:
            mapping = json.load(f)

        for workflow_key in set(mapping.values()):
            if workflow_key not in DEPARTMENT_WORKFLOWS:
                raise CommandError(
                    f"Unknown workflow key '{workflow_key}' in mapping file. "
                    f"Valid keys: {', '.join(DEPARTMENT_WORKFLOWS.keys())}"
                )

        projects = Project.objects.all()
        if options["workspace_slug"]:
            projects = projects.filter(workspace__slug=options["workspace_slug"])

        self.stdout.write(
            self.style.WARNING("DRY RUN — nothing will be written. Pass --apply to commit.")
            if not apply_changes
            else self.style.WARNING("--apply passed — changes WILL be written.")
        )

        for project in projects:
            self._migrate_project(project, mapping.get(project.name), apply_changes)

    def _migrate_project(self, project, workflow_key, apply_changes):
        target_spec = DEPARTMENT_WORKFLOWS.get(workflow_key, DEFAULT_STATES)
        label = workflow_key or "(default — all other projects)"

        with transaction.atomic():
            existing_by_name = {s.name: s for s in State.all_state_objects.filter(project=project)}

            # 1. Create (or reuse) each target state.
            new_states = []
            default_new_state = None
            for index, spec in enumerate(target_spec):
                state = existing_by_name.get(spec["name"])
                if state is None:
                    state = State.objects.create(
                        project=project,
                        workspace=project.workspace,
                        name=spec["name"],
                        color=spec["color"],
                        group=spec["group"],
                        sequence=(index + 1) * 15000,
                        default=spec.get("default", False),
                    )
                new_states.append(state)
                if spec.get("default"):
                    default_new_state = state

            new_names = {s["name"] for s in target_spec}
            group_to_new_state = {}
            for state in new_states:
                group_to_new_state.setdefault(state.group, state)

            # 2. Retire every state that isn't part of the new workflow.
            old_states = [s for s in existing_by_name.values() if s.name not in new_names]

            moved_count = 0
            manual_review = []
            for old_state in old_states:
                target_state = group_to_new_state.get(old_state.group)
                if target_state is None:
                    for fallback_group in GROUP_FALLBACK_ORDER:
                        target_state = group_to_new_state.get(fallback_group)
                        if target_state:
                            break
                    manual_review.append((old_state, target_state))

                issue_count = Issue.objects.filter(state=old_state).count()
                if issue_count and target_state:
                    Issue.objects.filter(state=old_state).update(state=target_state)
                    moved_count += issue_count

                if project.default_state_id == old_state.id and default_new_state:
                    project.default_state = default_new_state
                    project.save(update_fields=["default_state"])

                old_state.delete()

            self.stdout.write(
                f"{project.workspace.slug}/{project.name} -> {label}: "
                f"{len(new_states)} target states ready, {len(old_states)} old state(s) retired, "
                f"{moved_count} issue(s) reassigned."
            )
            for old_state, target_state in manual_review:
                self.stdout.write(
                    self.style.WARNING(
                        f"  MANUAL REVIEW: '{old_state.name}' (group={old_state.group}) had no matching "
                        f"new state for its group; issues moved to '{target_state.name if target_state else 'NONE — unassigned!'}' instead."
                    )
                )

            if not apply_changes:
                transaction.set_rollback(True)
