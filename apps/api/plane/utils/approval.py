# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Handover approval gate — Pending Approval is a hard stop in the workflow.
Every work item has to pass through it, and only a project Admin (the
approver, in practice the accountant) can move one past it, and only from
it. The rule is the same for every role — Admins included — and is applied
to every request that can set a state (app/external API create, update and
upsert, draft conversion, intake) through plane.utils.state_transition, so
client-side state-picker filtering is UX only. See evaluate_approval_gate.

On by default, no setup required: every project gets an explicit
ApprovalGateConfig (`is_enabled=True`, mapped over DEFAULT_STATES — see
plane.db.models.state.DEFAULT_APPROVAL_GATE_STATES) at project creation, and
existing projects were backfilled the same way (see migration
0134_backfill_approval_gate_configs). A project can still turn it off
(`is_enabled=False`) or repoint any of the three states without touching
code.

For the rare project with no config row at all, a state matching one of the
name aliases below (case-insensitive) is gated automatically as a
last-resort fallback — this covers both the ticket's own naming and the
client's actual department workflows (see apply_department_workflows.py),
which use different words for the same roles ("Sent for Approval",
"Handedover", "Publish/Close", …). None of those workflows model a
rejection step, so there is no "sent back" alias beyond the literal name (or
the default "Xerox and Binding") — a project without a state named that
stays ungated for that role until one is added.
"""

from plane.db.models import ApprovalGateConfig, ProjectMember, State
from plane.db.models.state import DEFAULT_APPROVAL_GATE_STATES
from plane.utils.permissions.base import ROLE

_PENDING_APPROVAL_ALIASES = {"pending approval", "sent for approval", DEFAULT_APPROVAL_GATE_STATES["pending_approval"].lower()}
_APPROVED_ALIASES = {
    "approved",
    "handedover",
    "publish/close",
    "post/close",
    "completed",
    DEFAULT_APPROVAL_GATE_STATES["approved"].lower(),
}
_SENT_BACK_ALIASES = {"sent back", DEFAULT_APPROVAL_GATE_STATES["sent_back"].lower()}


def get_approval_gate_config(project_id):
    return (
        ApprovalGateConfig.objects.filter(project_id=project_id)
        .select_related("pending_approval_state", "approved_state", "sent_back_state")
        .first()
    )


def resolve_gate_state_ids(project_id):
    """Returns (pending_approval_id, approved_id, sent_back_id), each a
    string id or None. Prefers an explicit ApprovalGateConfig — including an
    explicitly disabled one, which returns (None, None, None) to switch the
    gate fully off; otherwise falls back to matching State names so the
    gate still works with zero setup.
    """
    config = get_approval_gate_config(project_id)
    if config:
        if not config.is_enabled:
            return None, None, None
        return (
            str(config.pending_approval_state_id) if config.pending_approval_state_id else None,
            str(config.approved_state_id) if config.approved_state_id else None,
            str(config.sent_back_state_id) if config.sent_back_state_id else None,
        )

    pending_id = approved_id = sent_back_id = None
    for state in State.objects.filter(project_id=project_id).order_by("sequence").only("id", "name"):
        key = state.name.strip().lower()
        if pending_id is None and key in _PENDING_APPROVAL_ALIASES:
            pending_id = str(state.id)
        if approved_id is None and key in _APPROVED_ALIASES:
            approved_id = str(state.id)
        if sent_back_id is None and key in _SENT_BACK_ALIASES:
            sent_back_id = str(state.id)

    return pending_id, approved_id, sent_back_id


def is_project_approver(user, project_id) -> bool:
    return ProjectMember.objects.filter(
        project_id=project_id,
        member=user,
        is_active=True,
        role=ROLE.ADMIN.value,
    ).exists()


def is_send_back_transition(original_state_id, requested_state_id, pending_id, sent_back_id) -> bool:
    """True only for a rejection: a move OUT of Pending Approval INTO the
    Sent Back state.

    The Sent Back state is an ordinary workflow stage that work items pass
    through on the way *forward* — "Xerox and Binding" by default, which
    sits mid-workflow, well before Pending Approval. Entering it from
    anywhere else is a normal state change and must not be gated, must not
    demand a comment, and must not be logged as a rejection. Only coming
    back to it from Pending Approval means "the approver bounced this".

    Contrast the Approved state, which is a pure sign-off with no other
    role in the workflow — reaching that is gated no matter where from.
    """
    return bool(
        sent_back_id
        and pending_id
        and str(requested_state_id) == str(sent_back_id)
        and str(original_state_id) == str(pending_id)
    )


APPROVAL_DECISION_APPROVED = "approved"
APPROVAL_DECISION_SENT_BACK = "sent_back"

# States in these groups are never "further along" than Pending Approval:
# triage sits outside the flow, and cancelling a work item is not a step
# forward in it.
_NON_FORWARD_GROUPS = {"triage", "cancelled"}


def _past_pending_state_ids(states, pending_id, approved_id):
    """`states` maps state id -> {"sequence", "group", ...} for one project."""
    past_ids = {approved_id} if approved_id else set()
    pending = states.get(pending_id) if pending_id else None
    if pending:
        past_ids |= {
            state_id
            for state_id, state in states.items()
            if state["group"] not in _NON_FORWARD_GROUPS and state["sequence"] > pending["sequence"]
        }
    return past_ids


def get_past_pending_state_ids(project_id):
    """Ids of the project's states that only an approver may move a work item
    into (from Pending Approval). Empty when the gate is off."""
    pending_id, approved_id, _ = resolve_gate_state_ids(project_id)
    if not pending_id and not approved_id:
        return set()
    states = {
        str(state["id"]): state
        for state in State.all_state_objects.filter(project_id=project_id, deleted_at__isnull=True).values("id", "sequence", "group")
    }
    return _past_pending_state_ids(states, pending_id, approved_id)


def evaluate_approval_gate(project_id, original_state_id, requested_state_id, actor, comment_html=None):
    """Decide whether moving a work item from `original_state_id` (None when
    the work item is being created) into `requested_state_id` is allowed.

    Returns (error, decision, enters_pending):
      * error — message to reject the request with (nothing may be written).
      * decision — APPROVAL_DECISION_APPROVED / _SENT_BACK when the move is a
        sign-off that must be recorded, else None.
      * enters_pending — True when the move puts the work item into Pending
        Approval (approvers must be notified).

    The rule, identical for every role and every entry point:
      * A state "past" Pending Approval is any state ordered after it
        (higher `sequence`), plus the configured Approved state itself.
      * Nobody skips Pending Approval: reaching a past state is only possible
        from Pending Approval itself (or from a state that is already past
        it), and never on creation.
      * Leaving Pending Approval forwards is the sign-off — approvers only.
      * Anyone may send a work item into Pending Approval or pull it back
        out to an earlier stage; an approver bouncing it into the Sent Back
        state is a rejection and must carry a comment.
    """
    if not requested_state_id:
        return None, None, False

    requested_state_id = str(requested_state_id)
    original_state_id = str(original_state_id) if original_state_id else None
    if requested_state_id == original_state_id:
        return None, None, False  # not actually a transition

    pending_id, approved_id, sent_back_id = resolve_gate_state_ids(project_id)
    if not pending_id and not approved_id:
        return None, None, False  # gate off / not configured

    states = {
        str(state["id"]): state
        for state in State.all_state_objects.filter(project_id=project_id, deleted_at__isnull=True).values("id", "name", "sequence", "group")
    }
    target = states.get(requested_state_id)
    if target is None:
        return None, None, False  # unknown state - the serializer rejects it
    pending = states.get(pending_id) if pending_id else None
    past_pending_ids = _past_pending_state_ids(states, pending_id, approved_id)

    def is_past_pending(state_id):
        return bool(state_id) and state_id in past_pending_ids

    if is_past_pending(requested_state_id):
        if is_past_pending(original_state_id):
            return None, None, False  # already signed off - later stages are free
        if not pending:
            # no Pending Approval state mapped: the Approved state alone is
            # the sign-off and stays approver-only.
            if not is_project_approver(actor, project_id):
                return f'Only a project approver can move a work item to "{target["name"]}".', None, False
            return None, APPROVAL_DECISION_APPROVED, False
        if original_state_id != pending_id:
            return (
                f'A work item must be sent to "{pending["name"]}" and approved before it can move to '
                f'"{target["name"]}".',
                None,
                False,
            )
        if not is_project_approver(actor, project_id):
            return f'Only a project approver can move a work item past "{pending["name"]}".', None, False
        return None, APPROVAL_DECISION_APPROVED, False

    if pending_id and requested_state_id == pending_id:
        return None, None, True

    if is_send_back_transition(original_state_id, requested_state_id, pending_id, sent_back_id) and (
        is_project_approver(actor, project_id)
    ):
        if not comment_html or not str(comment_html).strip():
            return "Sending back requires a comment explaining why.", None, False
        return None, APPROVAL_DECISION_SENT_BACK, False

    # every other move - including a member pulling a work item back out of
    # Pending Approval - is ordinary work.
    return None, None, False
