# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import uuid

# Third party imports
from celery import shared_task
from django.db import transaction
from django.utils import timezone

# Module imports
from plane.db.models import (
    Cycle,
    CycleIssue,
    Estimate,
    EstimatePoint,
    Intake,
    IntakeIssue,
    Issue,
    IssueAssignee,
    IssueLabel,
    IssueLink,
    IssueSequence,
    IssueView,
    Label,
    Module,
    ModuleIssue,
    ModuleLink,
    Notification,
    Page,
    PageLabel,
    Project,
    ProjectPage,
    State,
)
from plane.utils.exception_logger import log_exception


def _remap_filter_ids(value, id_map):
    """Best-effort substitution of old entity UUIDs with their cloned equivalents inside
    arbitrarily nested filter JSON. Unmatched UUIDs are dropped rather than left dangling."""
    if isinstance(value, dict):
        return {key: _remap_filter_ids(val, id_map) for key, val in value.items()}
    if isinstance(value, list):
        remapped = [_remap_filter_ids(item, id_map) for item in value]
        return [item for item in remapped if item is not None]
    if isinstance(value, str) and value in id_map:
        return str(id_map[value])
    if isinstance(value, str):
        try:
            uuid.UUID(value)
        except ValueError:
            return value
        # Looks like a UUID we don't have a mapping for - drop it
        return None
    return value


def _clone_estimate(source_project, new_project, actor_id):
    source_estimate = source_project.estimate
    if source_estimate is None:
        return

    new_estimate = Estimate.objects.create(
        name=source_estimate.name,
        description=source_estimate.description,
        type=source_estimate.type,
        last_used=source_estimate.last_used,
        project=new_project,
        workspace=new_project.workspace,
        created_by_id=actor_id,
    )

    points = list(EstimatePoint.objects.filter(estimate=source_estimate))
    EstimatePoint.objects.bulk_create(
        [
            EstimatePoint(
                estimate=new_estimate,
                key=point.key,
                description=point.description,
                value=point.value,
                project=new_project,
                workspace=new_project.workspace,
                created_by_id=actor_id,
            )
            for point in points
        ]
    )

    new_project.estimate = new_estimate
    new_project.save(update_fields=["estimate"])


def _clone_states(source_project, new_project, actor_id):
    source_states = list(State.all_state_objects.filter(project=source_project))
    new_states = State.all_state_objects.bulk_create(
        [
            State(
                name=state.name,
                description=state.description,
                color=state.color,
                sequence=state.sequence,
                group=state.group,
                is_triage=state.is_triage,
                default=state.default,
                project=new_project,
                workspace=new_project.workspace,
                created_by_id=actor_id,
            )
            for state in source_states
        ]
    )
    state_map = {str(old.id): new.id for old, new in zip(source_states, new_states)}

    if source_project.default_state_id and str(source_project.default_state_id) in state_map:
        new_project.default_state_id = state_map[str(source_project.default_state_id)]
        new_project.save(update_fields=["default_state"])

    return state_map


def _clone_labels(source_project, new_project, actor_id):
    source_labels = list(Label.objects.filter(project=source_project))
    new_labels = Label.objects.bulk_create(
        [
            Label(
                name=label.name,
                description=label.description,
                color=label.color,
                sort_order=label.sort_order,
                project=new_project,
                workspace=new_project.workspace,
                created_by_id=actor_id,
            )
            for label in source_labels
        ]
    )
    label_map = {str(old.id): new.id for old, new in zip(source_labels, new_labels)}

    to_update = []
    for old_label, new_label in zip(source_labels, new_labels):
        if old_label.parent_id and str(old_label.parent_id) in label_map:
            new_label.parent_id = label_map[str(old_label.parent_id)]
            to_update.append(new_label)
    if to_update:
        Label.objects.bulk_update(to_update, ["parent"])

    return label_map


def _clone_cycles(source_project, new_project, actor_id):
    source_cycles = list(Cycle.objects.filter(project=source_project))
    new_cycles = Cycle.objects.bulk_create(
        [
            Cycle(
                name=cycle.name,
                description=cycle.description,
                start_date=cycle.start_date,
                end_date=cycle.end_date,
                owned_by_id=actor_id,
                view_props=cycle.view_props,
                sort_order=cycle.sort_order,
                logo_props=cycle.logo_props,
                timezone=cycle.timezone,
                project=new_project,
                workspace=new_project.workspace,
                created_by_id=actor_id,
            )
            for cycle in source_cycles
        ]
    )
    return {str(old.id): new.id for old, new in zip(source_cycles, new_cycles)}


def _clone_modules(source_project, new_project, actor_id):
    source_modules = list(Module.objects.filter(project=source_project))
    new_modules = Module.objects.bulk_create(
        [
            Module(
                name=module.name,
                description=module.description,
                description_text=module.description_text,
                description_html=module.description_html,
                start_date=module.start_date,
                target_date=module.target_date,
                status=module.status,
                lead_id=actor_id,
                view_props=module.view_props,
                sort_order=module.sort_order,
                logo_props=module.logo_props,
                project=new_project,
                workspace=new_project.workspace,
                created_by_id=actor_id,
            )
            for module in source_modules
        ]
    )
    module_map = {str(old.id): new.id for old, new in zip(source_modules, new_modules)}

    source_links = list(ModuleLink.objects.filter(module__project=source_project))
    ModuleLink.objects.bulk_create(
        [
            ModuleLink(
                title=link.title,
                url=link.url,
                metadata=link.metadata,
                module_id=module_map[str(link.module_id)],
                project=new_project,
                workspace=new_project.workspace,
                created_by_id=actor_id,
            )
            for link in source_links
            if str(link.module_id) in module_map
        ]
    )

    return module_map


def _clone_views(source_project, new_project, actor_id, state_map, label_map, cycle_map, module_map):
    id_map = {**state_map, **label_map, **cycle_map, **module_map}
    source_views = list(IssueView.objects.filter(project=source_project))
    IssueView.objects.bulk_create(
        [
            IssueView(
                name=view.name,
                description=view.description,
                query=_remap_filter_ids(view.query, id_map),
                filters=_remap_filter_ids(view.filters, id_map),
                display_filters=view.display_filters,
                display_properties=view.display_properties,
                rich_filters=_remap_filter_ids(view.rich_filters, id_map),
                access=view.access,
                sort_order=view.sort_order,
                logo_props=view.logo_props,
                owned_by_id=actor_id,
                is_locked=view.is_locked,
                project=new_project,
                workspace=new_project.workspace,
                created_by_id=actor_id,
            )
            for view in source_views
        ]
    )


def _clone_intake(new_project, actor_id):
    if not new_project.intake_view:
        return None
    return Intake.objects.create(
        name=f"{new_project.name} Intake",
        project=new_project,
        workspace=new_project.workspace,
        is_default=True,
        created_by_id=actor_id,
    )


def _clone_issues(source_project, new_project, actor_id, state_map, label_map, cycle_map, module_map, new_intake):
    source_issues = list(Issue.objects.filter(project=source_project).order_by("sequence_id"))

    new_issues = Issue.objects.bulk_create(
        [
            Issue(
                name=issue.name,
                description_json=issue.description_json,
                description_html=issue.description_html,
                description_stripped=issue.description_stripped,
                description_binary=issue.description_binary,
                priority=issue.priority,
                start_date=issue.start_date,
                target_date=issue.target_date,
                point=issue.point,
                sort_order=issue.sort_order,
                is_draft=issue.is_draft,
                state_id=state_map.get(str(issue.state_id)),
                estimate_point=None,
                type=None,
                parent=None,
                project=new_project,
                workspace=new_project.workspace,
                created_by_id=actor_id,
            )
            for issue in source_issues
        ]
    )
    issue_map = {str(old.id): new for old, new in zip(source_issues, new_issues)}

    # Manually create IssueSequence rows since bulk_create bypasses Issue.save()
    IssueSequence.objects.bulk_create(
        [
            IssueSequence(
                issue=new_issue,
                sequence=index + 1,
                project=new_project,
                workspace=new_project.workspace,
                created_by_id=actor_id,
            )
            for index, new_issue in enumerate(new_issues)
        ]
    )
    to_update = []
    for index, new_issue in enumerate(new_issues):
        new_issue.sequence_id = index + 1
        to_update.append(new_issue)
    Issue.objects.bulk_update(to_update, ["sequence_id"])

    # Second pass: remap sub-issue hierarchy
    parent_updates = []
    for old_issue, new_issue in zip(source_issues, new_issues):
        if old_issue.parent_id and str(old_issue.parent_id) in issue_map:
            new_issue.parent = issue_map[str(old_issue.parent_id)]
            parent_updates.append(new_issue)
    if parent_updates:
        Issue.objects.bulk_update(parent_updates, ["parent"])

    # Assignees - only the cloning user's own assignment carries over
    IssueAssignee.objects.bulk_create(
        [
            IssueAssignee(
                issue=issue_map[str(assignee.issue_id)],
                assignee_id=actor_id,
                project=new_project,
                workspace=new_project.workspace,
                created_by_id=actor_id,
            )
            for assignee in IssueAssignee.objects.filter(issue__project=source_project, assignee_id=actor_id)
            if str(assignee.issue_id) in issue_map
        ]
    )

    # Labels
    source_issue_labels = list(IssueLabel.objects.filter(issue__project=source_project))
    IssueLabel.objects.bulk_create(
        [
            IssueLabel(
                issue=issue_map[str(issue_label.issue_id)],
                label_id=label_map[str(issue_label.label_id)],
                project=new_project,
                workspace=new_project.workspace,
                created_by_id=actor_id,
            )
            for issue_label in source_issue_labels
            if str(issue_label.issue_id) in issue_map and str(issue_label.label_id) in label_map
        ]
    )

    # Links
    source_issue_links = list(IssueLink.objects.filter(issue__project=source_project))
    IssueLink.objects.bulk_create(
        [
            IssueLink(
                title=link.title,
                url=link.url,
                metadata=link.metadata,
                issue=issue_map[str(link.issue_id)],
                project=new_project,
                workspace=new_project.workspace,
                created_by_id=actor_id,
            )
            for link in source_issue_links
            if str(link.issue_id) in issue_map
        ]
    )

    # Cycle/module associations
    source_cycle_issues = list(CycleIssue.objects.filter(issue__project=source_project))
    CycleIssue.objects.bulk_create(
        [
            CycleIssue(
                issue=issue_map[str(cycle_issue.issue_id)],
                cycle_id=cycle_map[str(cycle_issue.cycle_id)],
                project=new_project,
                workspace=new_project.workspace,
                created_by_id=actor_id,
            )
            for cycle_issue in source_cycle_issues
            if str(cycle_issue.issue_id) in issue_map and str(cycle_issue.cycle_id) in cycle_map
        ]
    )

    source_module_issues = list(ModuleIssue.objects.filter(issue__project=source_project))
    ModuleIssue.objects.bulk_create(
        [
            ModuleIssue(
                issue=issue_map[str(module_issue.issue_id)],
                module_id=module_map[str(module_issue.module_id)],
                project=new_project,
                workspace=new_project.workspace,
                created_by_id=actor_id,
            )
            for module_issue in source_module_issues
            if str(module_issue.issue_id) in issue_map and str(module_issue.module_id) in module_map
        ]
    )

    # Intake
    if new_intake is not None:
        source_intake_issues = list(IntakeIssue.objects.filter(issue__project=source_project))
        IntakeIssue.objects.bulk_create(
            [
                IntakeIssue(
                    intake=new_intake,
                    issue=issue_map[str(intake_issue.issue_id)],
                    status=intake_issue.status,
                    snoozed_till=intake_issue.snoozed_till,
                    duplicate_to=None,
                    source=intake_issue.source,
                    project=new_project,
                    workspace=new_project.workspace,
                    created_by_id=actor_id,
                )
                for intake_issue in source_intake_issues
                if str(intake_issue.issue_id) in issue_map
            ]
        )


def _clone_pages(source_project, new_project, actor_id, label_map):
    source_pages = list(Page.objects.filter(projects=source_project))
    new_pages = Page.objects.bulk_create(
        [
            Page(
                name=page.name,
                description_json=page.description_json,
                description_binary=page.description_binary,
                description_html=page.description_html,
                description_stripped=page.description_stripped,
                owned_by_id=actor_id,
                access=page.access,
                color=page.color,
                parent=None,
                view_props=page.view_props,
                logo_props=page.logo_props,
                sort_order=page.sort_order,
                workspace=new_project.workspace,
                created_by_id=actor_id,
            )
            for page in source_pages
        ]
    )
    page_map = {str(old.id): new for old, new in zip(source_pages, new_pages)}

    parent_updates = []
    for old_page, new_page in zip(source_pages, new_pages):
        if old_page.parent_id and str(old_page.parent_id) in page_map:
            new_page.parent = page_map[str(old_page.parent_id)]
            parent_updates.append(new_page)
    if parent_updates:
        Page.objects.bulk_update(parent_updates, ["parent"])

    ProjectPage.objects.bulk_create(
        [
            ProjectPage(
                project=new_project,
                page=new_page,
                workspace=new_project.workspace,
                created_by_id=actor_id,
            )
            for new_page in new_pages
        ]
    )

    source_page_labels = list(PageLabel.objects.filter(page__in=source_pages))
    PageLabel.objects.bulk_create(
        [
            PageLabel(
                page=page_map[str(page_label.page_id)],
                label_id=label_map[str(page_label.label_id)],
                workspace=new_project.workspace,
                created_by_id=actor_id,
            )
            for page_label in source_page_labels
            if str(page_label.page_id) in page_map and str(page_label.label_id) in label_map
        ]
    )


def _notify_completion(new_project, actor_id, failed=False):
    Notification.objects.create(
        workspace=new_project.workspace,
        project=new_project,
        entity_identifier=new_project.id,
        entity_name="project",
        title=(f"Failed to clone project into {new_project.name}" if failed else f"{new_project.name} is ready"),
        message_html=(
            "<p>Something went wrong while cloning the project.</p>"
            if failed
            else f"<p>Your cloned project {new_project.name} has been fully populated.</p>"
        ),
        sender="in_app:project:cloned" if not failed else "in_app:project:clone_failed",
        triggered_by_id=actor_id,
        receiver_id=actor_id,
    )


@shared_task
def clone_project_data(source_project_id, new_project_id, actor_id):
    try:
        with transaction.atomic():
            source_project = Project.objects.get(pk=source_project_id)
            new_project = Project.objects.get(pk=new_project_id)

            _clone_estimate(source_project, new_project, actor_id)
            state_map = _clone_states(source_project, new_project, actor_id)
            label_map = _clone_labels(source_project, new_project, actor_id)
            cycle_map = _clone_cycles(source_project, new_project, actor_id)
            module_map = _clone_modules(source_project, new_project, actor_id)
            _clone_views(source_project, new_project, actor_id, state_map, label_map, cycle_map, module_map)
            new_intake = _clone_intake(new_project, actor_id)
            _clone_issues(
                source_project, new_project, actor_id, state_map, label_map, cycle_map, module_map, new_intake
            )
            _clone_pages(source_project, new_project, actor_id, label_map)

        _notify_completion(new_project, actor_id)
    except Exception as e:
        log_exception(e)
        try:
            new_project = Project.objects.get(pk=new_project_id)
            _notify_completion(new_project, actor_id, failed=True)
        except Exception as inner_e:
            log_exception(inner_e)
