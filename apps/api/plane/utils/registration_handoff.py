# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Moving a work item into the client's configured "registration" state means a
physical person now has to go to the sub-registrar's office — usually not
whoever changed the state. This must not complete without naming an eligible
registrar (registration agent), who is then assigned to the work item and
emailed.

Split in two so nothing is written or sent for a request that later fails:
  * plan_registration_handoff() only validates — call it before the save.
  * commit_registration_handoff() writes the record and queues the email on
    transaction commit — call it inside the save transaction.
Both are driven by plane.utils.state_transition, which every state-changing
entry point goes through.

The trigger state is configured per project via RegistrationHandoffConfig,
keyed by a State FK (not a name string) — renaming the stage doesn't break
this rule.

Registration can't be skipped either: a work item jumping from an earlier
stage (or created) straight into a stage after the registration state,
without ever having had a registrar named, must name one on that move.
"""

from dataclasses import dataclass
from typing import Optional

from django.db import transaction

from plane.bgtasks.registration_handoff_task import send_registration_agent_email
from plane.db.models import (
    IssueAssignee,
    ProjectMember,
    RegistrationHandoffConfig,
    RegistrationHandoffRecord,
    State,
)
from plane.utils.permissions.base import ROLE

REGISTRATION_AGENT_REQUIRED = "registration_agent_required"

# never "after" the registration state: triage sits outside the flow, and
# cancelling a work item is not a step forward in it (mirrors
# plane.utils.approval._NON_FORWARD_GROUPS)
_NON_FORWARD_GROUPS = {"triage", "cancelled"}


@dataclass
class RegistrationHandoffPlan:
    agent_id: str
    # the record to write on commit: "create", "update" (new pick replaces a
    # registrar who is no longer eligible, or an explicit re-pick) or "keep"
    record_action: str


def get_registration_handoff_config(project_id):
    return (
        RegistrationHandoffConfig.objects.filter(project_id=project_id)
        .select_related("trigger_state")
        .prefetch_related("eligible_agents")
        .first()
    )


def get_eligible_agent_ids(project_id, config=None):
    """Active project Members/Admins — guests can't be assigned work items, so
    naming one would email them without ever assigning them. When the config
    restricts the pool (eligible_agents), only those of them still in the
    project are eligible; an empty pool means "not restricted"."""
    member_ids = {
        str(uid)
        for uid in ProjectMember.objects.filter(
            project_id=project_id,
            is_active=True,
            role__gte=ROLE.MEMBER.value,
            member__is_active=True,
        ).values_list("member_id", flat=True)
    }
    if config is not None:
        restricted_ids = {str(uid) for uid in config.eligible_agents.values_list("id", flat=True)}
        if restricted_ids:
            return member_ids & restricted_ids
    return member_ids


def _is_at_or_past_registration(state, trigger_state):
    """`state` is a {"id", "sequence", "group"} dict, or None."""
    if state is None:
        return False
    if str(state["id"]) == str(trigger_state.id):
        return True
    return state["group"] not in _NON_FORWARD_GROUPS and state["sequence"] > trigger_state.sequence


def plan_registration_handoff(project_id, issue, requested_state_id, mutable_request_data, agent_key):
    """Validate a move into, or past, the registration state. No side
    effects apart from removing `agent_key` from the request data.

    Returns (error, error_code, plan). `plan` is None when the move doesn't
    need a registrar.

    Naming a registrar is required the first time a work item enters the
    state. On re-entry the registrar on record is reused (and re-notified) —
    unless they are no longer eligible (left the project, became a guest,
    were removed from the eligible pool), in which case a new one must be
    named. A registrar named explicitly always wins.

    Skipping the state is treated as entering it: a move from before the
    registration state (or a create) into any state after it needs a
    registrar too, unless the work item already has one on record. A work
    item already at or past the registration state is not re-asked when it
    moves between later stages.
    """
    requested_agent_id = mutable_request_data.pop(agent_key, None)

    if not requested_state_id:
        return None, None, None
    requested_state_id = str(requested_state_id)
    if issue is not None and requested_state_id == str(issue.state_id):
        return None, None, None  # not actually a transition

    config = get_registration_handoff_config(project_id)
    if config is None or config.trigger_state is None:
        return None, None, None
    trigger_state = config.trigger_state

    existing_record = (
        RegistrationHandoffRecord.objects.filter(issue_id=issue.id).first() if issue is not None else None
    )

    target_name = trigger_state.name
    if requested_state_id != str(trigger_state.id):
        if existing_record is not None:
            return None, None, None  # a registrar was named already
        state_ids = [requested_state_id] + ([issue.state_id] if issue is not None and issue.state_id else [])
        states = {
            str(state["id"]): state
            for state in State.objects.filter(project_id=project_id, id__in=state_ids).values(
                "id", "name", "sequence", "group"
            )
        }
        target = states.get(requested_state_id)
        if not _is_at_or_past_registration(target, trigger_state):
            return None, None, None  # a stage before registration
        original = states.get(str(issue.state_id)) if issue is not None and issue.state_id else None
        if _is_at_or_past_registration(original, trigger_state):
            return None, None, None  # already through registration - not a skip
        target_name = target["name"]

    eligible_ids = get_eligible_agent_ids(project_id, config)

    if requested_agent_id:
        if str(requested_agent_id) not in eligible_ids:
            return (
                f"The selected registrar can't be assigned for \"{trigger_state.name}\". "
                "Pick an active project member.",
                REGISTRATION_AGENT_REQUIRED,
                None,
            )
        action = "create" if existing_record is None else "update"
        return None, None, RegistrationHandoffPlan(agent_id=str(requested_agent_id), record_action=action)

    if existing_record is not None and str(existing_record.agent_id) in eligible_ids:
        return None, None, RegistrationHandoffPlan(agent_id=str(existing_record.agent_id), record_action="keep")

    if requested_state_id != str(trigger_state.id):
        return (
            f"\"{trigger_state.name}\" can't be skipped — moving to \"{target_name}\" requires naming a registrar "
            f"({agent_key}).",
            REGISTRATION_AGENT_REQUIRED,
            None,
        )
    return (
        f'Moving to "{trigger_state.name}" requires naming a registrar ({agent_key}).',
        REGISTRATION_AGENT_REQUIRED,
        None,
    )


def merge_registrar_into_assignees(plan, issue, mutable_request_data, assignee_key):
    """Add the registrar to the assignees being saved without dropping anyone:
    on top of the assignees sent in this same request when there are any,
    else on top of the work item's current assignees."""
    if assignee_key in mutable_request_data and mutable_request_data.get(assignee_key) is not None:
        base_ids = {str(uid) for uid in mutable_request_data.get(assignee_key) or []}
    elif issue is not None:
        base_ids = {
            str(uid) for uid in IssueAssignee.objects.filter(issue_id=issue.id).values_list("assignee_id", flat=True)
        }
    else:
        base_ids = set()
    mutable_request_data[assignee_key] = sorted(base_ids | {plan.agent_id})


def commit_registration_handoff(plan, issue, actor_id=None):
    """Write the handoff record and queue the registrar email. Must run inside
    the transaction that saves the state change: the email only goes out
    once that transaction commits."""
    if plan.record_action == "create":
        RegistrationHandoffRecord.objects.create(
            issue_id=issue.id,
            project_id=issue.project_id,
            workspace_id=issue.workspace_id,
            agent_id=plan.agent_id,
        )
    elif plan.record_action == "update":
        RegistrationHandoffRecord.objects.filter(issue_id=issue.id).update(agent_id=plan.agent_id)

    issue_id = str(issue.id)
    agent_id = plan.agent_id
    actor = str(actor_id) if actor_id else None
    transaction.on_commit(
        lambda: send_registration_agent_email.delay(issue_id=issue_id, agent_id=agent_id, actor_id=actor)
    )
