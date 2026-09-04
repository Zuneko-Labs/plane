# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from rest_framework import status
from rest_framework.response import Response

from plane.app.permissions import ROLE, allow_permission
from plane.app.serializers import ApprovalGateConfigSerializer, ApprovalRecordSerializer
from plane.db.models import ApprovalGateConfig, ApprovalRecord, Project
from plane.utils.approval import resolve_gate_state_ids

from .base import BaseAPIView, BaseViewSet


class ApprovalGateConfigViewSet(BaseViewSet):
    """Admin-only CRUD for the per-project handover approval gate: which
    States are Pending Approval / Approved / Sent Back. Read is open to
    project members so the state picker and drag-n-drop can fetch the
    current config; writes are ADMIN-only — this is how the approver-gated
    states are configured without a deploy."""

    serializer_class = ApprovalGateConfigSerializer
    model = ApprovalGateConfig

    def get_queryset(self):
        return ApprovalGateConfig.objects.filter(
            workspace__slug=self.kwargs.get("slug"),
            project_id=self.kwargs.get("project_id"),
        ).select_related("pending_approval_state", "approved_state", "sent_back_state")

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def list(self, request, slug, project_id):
        configs = list(self.get_queryset())
        if configs:
            serializer = ApprovalGateConfigSerializer(configs, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)

        # No explicit override: fall back to the zero-config default (name
        # aliases covering both the ticket's naming and the client's actual
        # department workflows) so the state picker and Sent Back modal work
        # out of the box, same as the server-side gate itself (see
        # plane.utils.approval). Sent Back is optional — none of the
        # client's real workflows model a rejection step, so a project
        # without one still gets Pending Approval / Approved gating.
        pending_id, approved_id, sent_back_id = resolve_gate_state_ids(project_id)
        if pending_id and approved_id:
            return Response(
                [
                    {
                        "id": None,
                        "project": str(project_id),
                        "pending_approval_state_id": pending_id,
                        "approved_state_id": approved_id,
                        "sent_back_state_id": sent_back_id,
                    }
                ],
                status=status.HTTP_200_OK,
            )
        return Response([], status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN])
    def create(self, request, slug, project_id):
        project = Project.objects.get(pk=project_id, workspace__slug=slug)
        serializer = ApprovalGateConfigSerializer(data=request.data, context={"project_id": project_id})
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        config = serializer.save(project=project, workspace_id=project.workspace_id)
        return Response(ApprovalGateConfigSerializer(config).data, status=status.HTTP_201_CREATED)

    @allow_permission([ROLE.ADMIN])
    def partial_update(self, request, slug, project_id, pk):
        config = self.get_queryset().filter(pk=pk).first()
        if not config:
            return Response({"error": "Approval gate config not found"}, status=status.HTTP_404_NOT_FOUND)
        serializer = ApprovalGateConfigSerializer(
            config, data=request.data, partial=True, context={"project_id": project_id}
        )
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN])
    def destroy(self, request, slug, project_id, pk):
        config = self.get_queryset().filter(pk=pk).first()
        if not config:
            return Response({"error": "Approval gate config not found"}, status=status.HTTP_404_NOT_FOUND)
        config.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ApprovalRecordListEndpoint(BaseAPIView):
    """Read-only sign-off register for a project — every Approved / Sent
    Back decision, with who and when, for export. Plane's IssueActivity
    already records this too; this is the queryable/exportable form of the
    same fact, kept in its own table (see plane.db.models.ApprovalRecord).
    """

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def get(self, request, slug, project_id):
        records = (
            ApprovalRecord.objects.filter(workspace__slug=slug, project_id=project_id)
            .select_related("issue", "actor")
            .order_by("-created_at")
        )
        serializer = ApprovalRecordSerializer(records, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
