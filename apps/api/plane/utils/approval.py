# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Handover approval gate — the last stage of the handover flow is a sign-off,
not a status. Only a project Admin (the accountant, in practice) may move a
work item into the configured Approved or Sent Back state, and Sent Back
requires a comment explaining why every time. Enforced here so every
state-change surface (app API, external API, kanban drag, list/spreadsheet
inline edit — they all funnel into the two view methods that call this)
gets it for free; client-side state-picker filtering is UX only.

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


def apply_approval_gate(project_id, issue, requested_state_id, mutable_request_data, actor):
    """Returns (redirected_state_id, error).

    Two separate rules, because the two sign-off states play very different
    roles in the workflow:

    * Approved is a pure sign-off — reaching it is approver-only, from
      wherever the work item currently sits.
    * Sent Back doubles as an ordinary workflow stage ("Xerox and Binding"
      by default), so only the rejection *transition* is gated: an approver
      moving a work item out of Pending Approval back into it, which is the
      one that must carry a comment. Everyone else moving into that state
      is doing normal work and is left alone (see is_send_back_transition).

    error is set only when the transition must be rejected outright — an
    approver rejecting with no comment. A non-approver targeting Approved
    is never rejected: the move is silently redirected into Pending
    Approval instead (redirected_state_id is set, error is None) so their
    action still succeeds — it becomes a request the approver reviews,
    rather than a direct move into the sign-off state. Caller must
    overwrite the state field in the request with redirected_state_id (and
    drop approval_comment_html) before saving.
    """
    if not requested_state_id:
        return None, None

    requested_state_id = str(requested_state_id)
    original_state_id = str(issue.state_id)
    if requested_state_id == original_state_id:
        return None, None  # not actually a transition

    pending_id, approved_id, sent_back_id = resolve_gate_state_ids(project_id)

    if approved_id and requested_state_id == approved_id:
        if not is_project_approver(actor, project_id):
            if pending_id and pending_id != requested_state_id:
                mutable_request_data.pop("approval_comment_html", None)
                return pending_id, None
            # No Pending Approval state configured to redirect into — fall
            # back to a hard rejection rather than silently landing on the
            # sign-off state the member isn't allowed to reach.
            return None, 'Only a project approver can move a work item to "Approved".'
        return None, None

    if is_send_back_transition(original_state_id, requested_state_id, pending_id, sent_back_id):
        if not is_project_approver(actor, project_id):
            # Not a rejection at all — a member is just moving the work
            # item back into an earlier stage. Nothing to gate; drop any
            # stray comment so it isn't mistaken for a sign-off below.
            mutable_request_data.pop("approval_comment_html", None)
            return None, None
        comment_html = mutable_request_data.get("approval_comment_html")
        if not comment_html or not comment_html.strip():
            return None, "Sending back requires a comment explaining why."

    return None, None
