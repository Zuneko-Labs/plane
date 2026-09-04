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

On by default, no setup required: a project with a state matching one of
the name aliases below (case-insensitive) is gated automatically — this
covers both the ticket's own naming and the client's actual department
workflows (see apply_department_workflows.py), which use different words
for the same roles ("Sent for Approval", "Handedover", "Publish/Close", …).
None of those workflows model a rejection step, so there is no "sent back"
alias beyond the literal name — a project without a state named that stays
ungated for that role until one is added. ApprovalGateConfig is an explicit
override for teams naming things some other way entirely.
"""

from plane.db.models import ApprovalGateConfig, ProjectMember, State
from plane.utils.permissions.base import ROLE

_PENDING_APPROVAL_ALIASES = {"pending approval", "sent for approval"}
_APPROVED_ALIASES = {"approved", "handedover", "publish/close", "post/close", "completed"}
_SENT_BACK_ALIASES = {"sent back"}


def get_approval_gate_config(project_id):
    return (
        ApprovalGateConfig.objects.filter(project_id=project_id)
        .select_related("pending_approval_state", "approved_state", "sent_back_state")
        .first()
    )


def resolve_gate_state_ids(project_id):
    """Returns (pending_approval_id, approved_id, sent_back_id), each a
    string id or None. Prefers an explicit ApprovalGateConfig; otherwise
    falls back to matching State names so the gate works with zero setup.
    """
    config = get_approval_gate_config(project_id)
    if config:
        return (
            str(config.pending_approval_state_id),
            str(config.approved_state_id),
            str(config.sent_back_state_id),
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


def apply_approval_gate(project_id, issue, requested_state_id, mutable_request_data, actor):
    """Returns (redirected_state_id, error).

    error is set only when the transition must be rejected outright — an
    approver targeting Sent Back with no comment. A non-approver targeting
    Approved or Sent Back is never rejected: the move is silently
    redirected into Pending Approval instead (redirected_state_id is set,
    error is None) so their action still succeeds — it becomes a request
    the approver reviews, rather than a direct move into a sign-off state.
    Caller must overwrite the state field in the request with
    redirected_state_id (and drop approval_comment_html) before saving.
    """
    if not requested_state_id:
        return None, None

    requested_state_id = str(requested_state_id)
    if requested_state_id == str(issue.state_id):
        return None, None  # not actually a transition

    pending_id, approved_id, sent_back_id = resolve_gate_state_ids(project_id)
    if requested_state_id not in filter(None, (approved_id, sent_back_id)):
        return None, None  # Handover / Pending Approval stay open to anyone

    if not is_project_approver(actor, project_id):
        if pending_id and pending_id != requested_state_id:
            mutable_request_data.pop("approval_comment_html", None)
            return pending_id, None
        # No Pending Approval state configured to redirect into — fall
        # back to a hard rejection rather than silently landing on the
        # sign-off state the member isn't allowed to reach.
        return None, 'Only a project approver can move a work item to "Approved" or "Sent Back".'

    if requested_state_id == sent_back_id:
        comment_html = mutable_request_data.get("approval_comment_html")
        if not comment_html or not comment_html.strip():
            return None, "Sending back requires a comment explaining why."

    return None, None
