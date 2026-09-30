# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
The workspace-wide approvals page: one place where an approver sees every
work item waiting on them across all the projects they approve for (a
project Admin — see plane.utils.approval.is_project_approver), the sign-off
register of those projects, and the requests to reopen approved work items.

Reopening: once a work item is in Pending Approval or signed off, nobody
moves it back directly (see plane.utils.approval.evaluate_approval_gate).
Anyone - approvers included - files an ApprovalReopenRequest with a reason;
the work item only moves when an approver of its project accepts it here.
"""

import json
from collections import defaultdict

from django.core.serializers.json import DjangoJSONEncoder
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.html import escape
from rest_framework import status
from rest_framework.response import Response

from plane.app.permissions import ROLE, allow_permission
from plane.app.serializers import IssueCreateSerializer
from plane.bgtasks.issue_activities_task import issue_activity
from plane.db.models import (
    ApprovalRecord,
    ApprovalReopenRequest,
    Issue,
    IssueAssignee,
    IssueLabel,
    ModuleIssue,
    Notification,
    Project,
    ProjectMember,
    RegistrationHandoffRecord,
    State,
)
from plane.utils.approval import (
    get_locked_state_ids,
    get_past_pending_state_ids,
    is_project_approver,
    resolve_gate_state_ids,
)
from plane.utils.host import base_host
from plane.utils.state_transition import commit_state_change, plan_state_change

from .base import BaseAPIView

REOPEN_REASON_MAX_LENGTH = 2000
REOPEN_NOTIFICATION_SENDER = "in_app:issue_activities:reopen_request"


def approver_project_ids(user, slug):
    """Projects of this workspace the user approves for (project Admin)."""
    return list(
        ProjectMember.objects.filter(
            member=user,
            workspace__slug=slug,
            role=ROLE.ADMIN.value,
            is_active=True,
            project__archived_at__isnull=True,
            project__deleted_at__isnull=True,
        ).values_list("project_id", flat=True)
    )


def _project_map(project_ids):
    return {
        str(project["id"]): project
        for project in Project.objects.filter(id__in=project_ids).values("id", "name", "identifier")
    }


def _modules_by_issue(issue_ids):
    modules = defaultdict(list)
    for row in ModuleIssue.objects.filter(
        issue_id__in=issue_ids, deleted_at__isnull=True, module__deleted_at__isnull=True
    ).values("issue_id", "module_id", "module__name"):
        modules[str(row["issue_id"])].append({"id": str(row["module_id"]), "name": row["module__name"]})
    return modules


def _reason_html(prefix, reason):
    return f"<p><strong>{escape(prefix)}</strong> {escape(reason)}</p>"


def _issue_notification_data(issue, project, field, verb, old_value=None, new_value=None):
    # shaped like an issue-activity notification, so the notification inbox
    # can render it (see workspace-notifications/notification-card)
    return {
        "issue": {
            "id": str(issue.id),
            "name": issue.name,
            "identifier": project.identifier,
            "sequence_id": issue.sequence_id,
            "state_name": None,
            "state_group": None,
        },
        "issue_activity": {
            "id": None,
            "verb": verb,
            "field": field,
            "actor": None,
            "new_value": new_value,
            "old_value": old_value,
            "old_identifier": None,
            "new_identifier": None,
        },
    }


def _notify(issue, project, actor_id, receiver_ids, title, data):
    Notification.objects.bulk_create(
        [
            Notification(
                workspace_id=project.workspace_id,
                project_id=project.id,
                sender=REOPEN_NOTIFICATION_SENDER,
                triggered_by_id=actor_id,
                receiver_id=receiver_id,
                entity_identifier=issue.id,
                entity_name="issue",
                title=title,
                data=data,
            )
            for receiver_id in {str(uid) for uid in receiver_ids}
            if receiver_id != str(actor_id)
        ],
        batch_size=100,
    )


def serialize_reopen_request(reopen_request, projects=None, modules=None):
    project = (projects or {}).get(str(reopen_request.project_id)) or {}
    return {
        "id": str(reopen_request.id),
        "project_id": str(reopen_request.project_id),
        "project_name": project.get("name"),
        "project_identifier": project.get("identifier"),
        "issue_id": str(reopen_request.issue_id),
        "issue_name": reopen_request.issue.name,
        "issue_sequence_id": reopen_request.issue.sequence_id,
        "issue_state_id": str(reopen_request.issue.state_id) if reopen_request.issue.state_id else None,
        "modules": (modules or {}).get(str(reopen_request.issue_id), []),
        "from_state_id": str(reopen_request.from_state_id) if reopen_request.from_state_id else None,
        "from_state_name": reopen_request.from_state.name if reopen_request.from_state_id else None,
        "to_state_id": str(reopen_request.to_state_id) if reopen_request.to_state_id else None,
        "to_state_name": reopen_request.to_state.name if reopen_request.to_state_id else None,
        "reason": reopen_request.reason,
        "status": reopen_request.status,
        "requested_by": str(reopen_request.requested_by_id),
        "requested_by_name": reopen_request.requested_by.display_name,
        "decided_by": str(reopen_request.decided_by_id) if reopen_request.decided_by_id else None,
        "decided_by_name": reopen_request.decided_by.display_name if reopen_request.decided_by_id else None,
        "decided_at": reopen_request.decided_at,
        "decision_comment": reopen_request.decision_comment,
        "created_at": reopen_request.created_at,
    }


class WorkspacePendingApprovalEndpoint(BaseAPIView):
    """Every work item sitting in Pending Approval, across the projects the
    user approves for — with the project and module each belongs to, and
    the gate states needed to approve or send it back."""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER], level="WORKSPACE")
    def get(self, request, slug):
        project_ids = approver_project_ids(request.user, slug)
        gates = {}
        for project_id in project_ids:
            pending_id, approved_id, sent_back_id = resolve_gate_state_ids(project_id)
            if pending_id and approved_id:
                gates[str(project_id)] = (pending_id, approved_id, sent_back_id)
        if not gates:
            return Response([], status=status.HTTP_200_OK)

        issues = list(
            Issue.issue_objects.filter(
                workspace__slug=slug,
                project_id__in=list(gates.keys()),
                state_id__in=[gate[0] for gate in gates.values()],
            )
            .select_related("state")
            .order_by("-updated_at")
        )
        issue_ids = [issue.id for issue in issues]
        projects = _project_map(gates.keys())
        modules = _modules_by_issue(issue_ids)

        assignees = defaultdict(list)
        for row in IssueAssignee.objects.filter(
            issue_id__in=issue_ids, deleted_at__isnull=True, assignee__is_active=True
        ).values("issue_id", "assignee_id"):
            assignees[str(row["issue_id"])].append(str(row["assignee_id"]))

        labels = defaultdict(list)
        for row in IssueLabel.objects.filter(
            issue_id__in=issue_ids, deleted_at__isnull=True, label__deleted_at__isnull=True
        ).values("issue_id", "label_id", "label__name", "label__color"):
            labels[str(row["issue_id"])].append(
                {"id": str(row["label_id"]), "name": row["label__name"], "color": row["label__color"]}
            )

        handed_off = {
            str(issue_id)
            for issue_id in RegistrationHandoffRecord.objects.filter(issue_id__in=issue_ids).values_list(
                "issue_id", flat=True
            )
        }

        results = []
        for issue in issues:
            project_id = str(issue.project_id)
            # a project's pending state id can't collide with another's, but
            # only keep work items in *their own* project's pending state
            pending_id, approved_id, sent_back_id = gates[project_id]
            if str(issue.state_id) != pending_id:
                continue
            project = projects.get(project_id, {})
            results.append(
                {
                    "id": str(issue.id),
                    "name": issue.name,
                    "sequence_id": issue.sequence_id,
                    "priority": issue.priority,
                    "target_date": issue.target_date,
                    "state_id": str(issue.state_id),
                    "state_name": issue.state.name if issue.state_id else None,
                    "project_id": project_id,
                    "project_name": project.get("name"),
                    "project_identifier": project.get("identifier"),
                    "modules": modules.get(str(issue.id), []),
                    "labels": labels.get(str(issue.id), []),
                    "assignee_ids": assignees.get(str(issue.id), []),
                    "has_registration_handoff": str(issue.id) in handed_off,
                    "approved_state_id": approved_id,
                    "sent_back_state_id": sent_back_id,
                    "updated_at": issue.updated_at,
                }
            )
        return Response(results, status=status.HTTP_200_OK)


class WorkspaceApprovalRecordEndpoint(BaseAPIView):
    """The sign-off register (approved / sent back / reopened) of every
    project the user approves for."""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER], level="WORKSPACE")
    def get(self, request, slug):
        project_ids = approver_project_ids(request.user, slug)
        records = list(
            ApprovalRecord.objects.filter(workspace__slug=slug, project_id__in=project_ids)
            .select_related("issue", "actor")
            .order_by("-created_at")[:500]
        )
        projects = _project_map(project_ids)
        modules = _modules_by_issue([record.issue_id for record in records])
        return Response(
            [
                {
                    "id": str(record.id),
                    "project": str(record.project_id),
                    "project_name": projects.get(str(record.project_id), {}).get("name"),
                    "project_identifier": projects.get(str(record.project_id), {}).get("identifier"),
                    "issue": str(record.issue_id),
                    "issue_name": record.issue.name,
                    "issue_sequence_id": record.issue.sequence_id,
                    "modules": modules.get(str(record.issue_id), []),
                    "actor": str(record.actor_id),
                    "actor_email": record.actor.email,
                    "actor_name": record.actor.display_name,
                    "decision": record.decision,
                    "comment": record.comment,
                    "created_at": record.created_at,
                }
                for record in records
            ],
            status=status.HTTP_200_OK,
        )


class IssueReopenRequestEndpoint(BaseAPIView):
    """Ask to take an approved work item back to an earlier stage. The work
    item stays where it is until an approver accepts the request."""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def get(self, request, slug, project_id, issue_id):
        reopen_requests = ApprovalReopenRequest.objects.filter(
            workspace__slug=slug, project_id=project_id, issue_id=issue_id
        ).select_related("issue", "from_state", "to_state", "requested_by", "decided_by")
        return Response(
            [serialize_reopen_request(reopen_request) for reopen_request in reopen_requests],
            status=status.HTTP_200_OK,
        )

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def post(self, request, slug, project_id, issue_id):
        issue = Issue.issue_objects.filter(workspace__slug=slug, project_id=project_id, pk=issue_id).first()
        if issue is None:
            return Response({"error": "Work item not found"}, status=status.HTTP_404_NOT_FOUND)

        reason = str(request.data.get("reason") or "").strip()
        if not reason:
            return Response({"error": "A reason is required to reopen an approved work item."}, status=400)
        if len(reason) > REOPEN_REASON_MAX_LENGTH:
            return Response(
                {"error": f"The reason can be at most {REOPEN_REASON_MAX_LENGTH} characters."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        to_state = State.objects.filter(project_id=project_id, pk=request.data.get("state_id")).first()
        if to_state is None:
            return Response({"error": "Pick the state to move the work item back to."}, status=400)

        if str(issue.state_id) not in get_locked_state_ids(project_id):
            return Response(
                {"error": "This work item isn't pending approval or approved - move it directly instead."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if str(to_state.id) == str(issue.state_id) or str(to_state.id) in get_past_pending_state_ids(project_id):
            return Response(
                {"error": f'"{to_state.name}" isn\'t an earlier stage - move the work item directly instead.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        project = Project.objects.get(pk=project_id)
        try:
            with transaction.atomic():
                reopen_request = ApprovalReopenRequest.objects.create(
                    issue=issue,
                    project_id=project_id,
                    workspace_id=project.workspace_id,
                    requested_by=request.user,
                    from_state_id=issue.state_id,
                    to_state=to_state,
                    reason=reason,
                )
                approver_ids = ProjectMember.objects.filter(
                    project_id=project_id, role=ROLE.ADMIN.value, is_active=True
                ).values_list("member_id", flat=True)
                _notify(
                    issue,
                    project,
                    request.user.id,
                    approver_ids,
                    f'Reopen requested for "{issue.name}"',
                    _issue_notification_data(
                        issue, project, "reopen_request", "created", issue.state.name, to_state.name
                    ),
                )
        except IntegrityError:
            return Response(
                {"error": "A reopen request is already waiting for an approver on this work item."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        reopen_request = ApprovalReopenRequest.objects.select_related(
            "issue", "from_state", "to_state", "requested_by", "decided_by"
        ).get(pk=reopen_request.pk)
        return Response(serialize_reopen_request(reopen_request), status=status.HTTP_201_CREATED)


class WorkspaceReopenRequestEndpoint(BaseAPIView):
    """Reopen requests in the projects the user approves for.
    `?status=pending` (default), `approved`, `rejected` or `all`."""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER], level="WORKSPACE")
    def get(self, request, slug):
        project_ids = approver_project_ids(request.user, slug)
        reopen_requests = ApprovalReopenRequest.objects.filter(
            workspace__slug=slug, project_id__in=project_ids, issue__deleted_at__isnull=True
        ).select_related("issue", "from_state", "to_state", "requested_by", "decided_by")
        status_filter = request.GET.get("status", ApprovalReopenRequest.Status.PENDING)
        if status_filter != "all":
            reopen_requests = reopen_requests.filter(status=status_filter)
        reopen_requests = list(reopen_requests.order_by("-created_at")[:500])

        projects = _project_map(project_ids)
        modules = _modules_by_issue([reopen_request.issue_id for reopen_request in reopen_requests])
        return Response(
            [serialize_reopen_request(reopen_request, projects, modules) for reopen_request in reopen_requests],
            status=status.HTTP_200_OK,
        )


class WorkspaceReopenRequestDecisionEndpoint(BaseAPIView):
    """An approver accepts (the work item moves back to the requested state,
    with the reason on record) or rejects a reopen request.

    Body: {"decision": "approve" | "reject", "comment"?: str,
           "registration_agent_id"?: uuid - only when moving back needs a
           registrar and the server asked for one}.
    """

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER], level="WORKSPACE")
    def post(self, request, slug, pk):
        decision = request.data.get("decision")
        if decision not in ("approve", "reject"):
            return Response({"error": 'decision must be "approve" or "reject".'}, status=400)
        comment = str(request.data.get("comment") or "").strip()[:REOPEN_REASON_MAX_LENGTH] or None

        with transaction.atomic():
            reopen_request = (
                ApprovalReopenRequest.objects.select_for_update(of=("self",))
                .select_related("issue", "from_state", "to_state", "requested_by", "project")
                .filter(workspace__slug=slug, pk=pk)
                .first()
            )
            if reopen_request is None:
                return Response({"error": "Reopen request not found"}, status=status.HTTP_404_NOT_FOUND)
            if not is_project_approver(request.user, reopen_request.project_id):
                return Response(
                    {"error": "Only a project approver can decide on a reopen request."},
                    status=status.HTTP_403_FORBIDDEN,
                )
            if reopen_request.status != ApprovalReopenRequest.Status.PENDING:
                return Response(
                    {"error": f"This request was already {reopen_request.get_status_display().lower()}."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            issue = reopen_request.issue
            project = reopen_request.project

            if decision == "approve":
                error = self._apply_reopen(request, slug, reopen_request, issue, comment)
                if error is not None:
                    return error

            reopen_request.status = (
                ApprovalReopenRequest.Status.APPROVED if decision == "approve" else ApprovalReopenRequest.Status.REJECTED
            )
            reopen_request.decided_by = request.user
            reopen_request.decided_at = timezone.now()
            reopen_request.decision_comment = comment
            reopen_request.save(update_fields=["status", "decided_by", "decided_at", "decision_comment", "updated_at"])

            _notify(
                issue,
                project,
                request.user.id,
                [reopen_request.requested_by_id],
                f'Reopen request for "{issue.name}" {"approved" if decision == "approve" else "rejected"}',
                _issue_notification_data(
                    issue,
                    project,
                    "reopen_request",
                    "approved" if decision == "approve" else "rejected",
                    reopen_request.from_state.name if reopen_request.from_state_id else None,
                    reopen_request.to_state.name if reopen_request.to_state_id else None,
                ),
            )

        reopen_request = ApprovalReopenRequest.objects.select_related(
            "issue", "from_state", "to_state", "requested_by", "decided_by"
        ).get(pk=reopen_request.pk)
        return Response(serialize_reopen_request(reopen_request), status=status.HTTP_200_OK)

    def _apply_reopen(self, request, slug, reopen_request, issue, comment):
        """Move the work item back. Returns an error Response, or None."""
        if reopen_request.to_state_id is None:
            return Response(
                {"error": "The requested state no longer exists - reject this request instead."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        project_id = reopen_request.project_id
        if str(issue.state_id) not in get_locked_state_ids(project_id):
            return Response(
                {"error": "This work item is no longer pending approval or approved - reject this request instead."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        reason_html = _reason_html(
            f"Reopened (requested by {reopen_request.requested_by.display_name}):", reopen_request.reason
        )
        if comment:
            reason_html += _reason_html("Approver's note:", comment)
        data = {"state_id": str(reopen_request.to_state_id), "approval_comment_html": reason_html}
        if request.data.get("registration_agent_id"):
            data["registration_agent_id"] = request.data.get("registration_agent_id")

        state_change = plan_state_change(project_id, issue, data, request.user, reopen_approved=True)
        if state_change.error:
            return Response(state_change.error_response(), status=status.HTTP_400_BAD_REQUEST)

        current_instance = json.dumps(
            {
                "state_id": str(issue.state_id),
                "assignee_ids": [
                    str(uid)
                    for uid in IssueAssignee.objects.filter(issue_id=issue.id).values_list("assignee_id", flat=True)
                ],
            },
            cls=DjangoJSONEncoder,
        )
        requested_data = json.dumps(data, cls=DjangoJSONEncoder)
        serializer = IssueCreateSerializer(issue, data=data, partial=True, context={"project_id": project_id})
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        serializer.save()
        commit_state_change(state_change, issue, request.user)
        issue_activity.delay(
            type="issue.activity.updated",
            requested_data=requested_data,
            actor_id=str(request.user.id),
            issue_id=str(issue.id),
            project_id=str(project_id),
            current_instance=current_instance,
            epoch=int(timezone.now().timestamp()),
            notification=True,
            origin=base_host(request=request, is_app=True),
        )
        return None
