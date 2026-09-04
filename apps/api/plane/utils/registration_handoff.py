# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Moving a work item into the client's configured "registration" state means a
physical person now has to go to the sub-registrar's office — usually not
whoever changed the state. This must not complete without naming an eligible
registration agent, enforced here so every state-change surface (app API,
external API, kanban drag, list/spreadsheet inline edit — they all funnel
into the two view methods that call this) gets it for free.

The trigger state is configured per project via RegistrationHandoffConfig,
keyed by a State FK (not a name string) — renaming the stage doesn't break
this rule.
"""

from plane.bgtasks.registration_handoff_task import send_registration_agent_email
from plane.db.models import IssueAssignee, ProjectMember, RegistrationHandoffConfig


def get_registration_handoff_config(project_id):
    return (
        RegistrationHandoffConfig.objects.filter(project_id=project_id)
        .select_related("trigger_state")
        .prefetch_related("eligible_agents")
        .first()
    )


def apply_registration_handoff(project_id, issue, requested_state_id, mutable_request_data, agent_key, assignee_key):
    """Returns an error message string if the transition should be rejected.
    Returns None otherwise — and, when the transition IS into the configured
    state, mutates `mutable_request_data[assignee_key]` in place to add the
    agent alongside the issue's existing assignees, so the caller's existing
    assignee-diff notification pipeline picks up the new agent for free and
    nobody already assigned (e.g. the drafter) gets dropped.
    """
    if not requested_state_id:
        return None

    requested_state_id = str(requested_state_id)
    if requested_state_id == str(issue.state_id):
        return None  # not actually a transition

    config = get_registration_handoff_config(project_id)
    if config is None or requested_state_id != str(config.trigger_state_id):
        return None

    agent_id = mutable_request_data.get(agent_key)
    eligible_ids = {str(uid) for uid in config.eligible_agents.values_list("id", flat=True)}
    # no eligible_agents configured yet means "not restricted", not "nobody
    # is eligible" - fall back to any active project member, mirroring the
    # modal's own fallback to the full member roster.
    if not eligible_ids:
        eligible_ids = {
            str(uid)
            for uid in ProjectMember.objects.filter(project_id=project_id, is_active=True).values_list(
                "member_id", flat=True
            )
        }

    if not agent_id or str(agent_id) not in eligible_ids:
        return (
            f'Moving to "{config.trigger_state.name}" requires naming an eligible registration agent '
            f"({agent_key})."
        )

    existing_assignee_ids = {
        str(uid)
        for uid in IssueAssignee.objects.filter(issue_id=issue.id).values_list("assignee_id", flat=True)
    }
    mutable_request_data[assignee_key] = list(existing_assignee_ids | {str(agent_id)})
    send_registration_agent_email.delay(issue_id=issue.id, agent_id=str(agent_id))
    return None
