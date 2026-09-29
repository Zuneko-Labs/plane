# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
One entry point for every request that can set a work item's state — the
app and external APIs (create, update, upsert), draft conversion and intake.
Each of them runs the same two steps:

    plan = plan_state_change(...)          # before validation / save
    if plan.error: return 400 (plan.error_response())
    ... serializer.save() inside transaction.atomic() ...
    commit_state_change(plan, issue, actor) # inside the same transaction

so the handover approval gate (plane.utils.approval) and the registration
handoff (plane.utils.registration_handoff) behave the same wherever the
change comes from, and nothing is written or emailed for a request that is
rejected.
"""

from dataclasses import dataclass
from typing import Optional

from django.db import transaction

from plane.bgtasks.notification_task import notify_pending_approval
from plane.db.models import ApprovalGateConfig, ApprovalRecord, IssueComment, RegistrationHandoffConfig
from plane.utils.approval import (
    APPROVAL_DECISION_APPROVED,
    APPROVAL_DECISION_SENT_BACK,
    evaluate_approval_gate,
)
from plane.utils.registration_handoff import (
    RegistrationHandoffPlan,
    commit_registration_handoff,
    merge_registrar_into_assignees,
    plan_registration_handoff,
)


@dataclass
class StateChangePlan:
    error: Optional[str] = None
    error_code: Optional[str] = None
    requested_state_id: Optional[str] = None
    approval_decision: Optional[str] = None
    approval_comment_html: Optional[str] = None
    enters_pending: bool = False
    handoff: Optional[RegistrationHandoffPlan] = None

    def error_response(self):
        body = {"error": self.error}
        if self.error_code:
            body["error_code"] = self.error_code
        return body


def normalize_state_key(mutable_request_data, state_key, alias_key):
    """The app API reads `state_id`, the external API `state`, and both
    serializers write whichever they are given. Fold the alias into the key
    the gate reads so a request can't slip past it by using the other name."""
    if alias_key not in mutable_request_data:
        return
    alias_value = mutable_request_data.pop(alias_key)
    if mutable_request_data.get(state_key) in (None, ""):
        mutable_request_data[state_key] = alias_value


def plan_state_change(
    project_id,
    issue,
    mutable_request_data,
    actor,
    state_key="state_id",
    alias_key="state",
    agent_key="registration_agent_id",
    assignee_key="assignee_ids",
    requested_state_id=None,
):
    """Validate the state change carried by `mutable_request_data` (or passed
    explicitly as `requested_state_id`). `issue` is None when creating.

    May edit the request data in place: folds the state alias, removes the
    gate-only keys, and adds the registrar to the assignees being saved.
    Call before taking the `requested_data` snapshot for activity tracking.
    """
    if mutable_request_data is not None:
        normalize_state_key(mutable_request_data, state_key, alias_key)
        comment_html = mutable_request_data.pop("approval_comment_html", None)
        if requested_state_id is None:
            requested_state_id = mutable_request_data.get(state_key)
    else:
        mutable_request_data = {}
        comment_html = None

    plan = StateChangePlan(requested_state_id=str(requested_state_id) if requested_state_id else None)
    original_state_id = str(issue.state_id) if issue is not None and issue.state_id else None
    if not plan.requested_state_id or plan.requested_state_id == original_state_id:
        # no transition - still drop the registrar key so it never reaches
        # the serializer
        mutable_request_data.pop(agent_key, None)
        return plan

    error, decision, enters_pending = evaluate_approval_gate(
        project_id, original_state_id, plan.requested_state_id, actor, comment_html
    )
    if error:
        mutable_request_data.pop(agent_key, None)
        plan.error = error
        return plan
    plan.approval_decision = decision
    plan.approval_comment_html = comment_html if decision == APPROVAL_DECISION_SENT_BACK else None
    plan.enters_pending = enters_pending

    error, error_code, handoff = plan_registration_handoff(
        project_id, issue, plan.requested_state_id, mutable_request_data, agent_key
    )
    if error:
        plan.error = error
        plan.error_code = error_code
        return plan
    if handoff is not None:
        merge_registrar_into_assignees(handoff, issue, mutable_request_data, assignee_key)
        plan.handoff = handoff

    return plan


def commit_state_change(plan, issue, actor):
    """Write the sign-off register / registrar record and queue the
    notifications. Call inside the transaction that saved `issue`, after the
    save; notifications go out only once it commits."""
    if plan is None or not plan.requested_state_id:
        return

    if plan.approval_decision == APPROVAL_DECISION_SENT_BACK:
        IssueComment.objects.create(
            issue=issue,
            project_id=issue.project_id,
            workspace_id=issue.workspace_id,
            actor=actor,
            comment_html=plan.approval_comment_html,
        )
        ApprovalRecord.objects.create(
            issue=issue,
            project_id=issue.project_id,
            workspace_id=issue.workspace_id,
            actor=actor,
            decision=ApprovalRecord.Decision.SENT_BACK,
            comment=plan.approval_comment_html,
        )
    elif plan.approval_decision == APPROVAL_DECISION_APPROVED:
        ApprovalRecord.objects.create(
            issue=issue,
            project_id=issue.project_id,
            workspace_id=issue.workspace_id,
            actor=actor,
            decision=ApprovalRecord.Decision.APPROVED,
        )

    if plan.handoff is not None:
        commit_registration_handoff(plan.handoff, issue, actor_id=actor.id)

    if plan.enters_pending:
        issue_id = str(issue.id)
        project_id = str(issue.project_id)
        actor_id = str(actor.id)
        transaction.on_commit(
            lambda: notify_pending_approval.delay(issue_id=issue_id, project_id=project_id, actor_id=actor_id)
        )


def workflow_role_of_state(project_id, state_id):
    """Name of the approval / registration role a state plays in the
    project's workflow config, or None. Such a state must not be deleted:
    the gate would silently lose its Pending Approval / Approved stop."""
    config = ApprovalGateConfig.objects.filter(project_id=project_id).first()
    if config:
        roles = {
            config.pending_approval_state_id: "Pending Approval",
            config.approved_state_id: "Approved",
            config.sent_back_state_id: "Sent Back",
        }
        for role_state_id, role in roles.items():
            if role_state_id and str(role_state_id) == str(state_id):
                return role
    if RegistrationHandoffConfig.objects.filter(project_id=project_id, trigger_state_id=state_id).exists():
        return "Registration"
    return None
