# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from rest_framework import status
from rest_framework.response import Response

from plane.app.permissions import ROLE, allow_permission
from plane.app.serializers import RegistrationHandoffConfigSerializer
from plane.db.models import Project, RegistrationHandoffConfig

from .base import BaseViewSet


class RegistrationHandoffConfigViewSet(BaseViewSet):
    """Admin-only CRUD for the per-project registration-handoff rule: which
    State triggers it, and which users are eligible to be named as the
    registration agent. Read is open to project members so the detail-view
    modal can fetch the current config; writes are ADMIN-only."""

    serializer_class = RegistrationHandoffConfigSerializer
    model = RegistrationHandoffConfig

    def get_queryset(self):
        return RegistrationHandoffConfig.objects.filter(
            workspace__slug=self.kwargs.get("slug"),
            project_id=self.kwargs.get("project_id"),
        ).select_related("trigger_state")

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def list(self, request, slug, project_id):
        serializer = RegistrationHandoffConfigSerializer(self.get_queryset(), many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN])
    def create(self, request, slug, project_id):
        project = Project.objects.get(pk=project_id, workspace__slug=slug)
        serializer = RegistrationHandoffConfigSerializer(data=request.data, context={"project_id": project_id})
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        config = serializer.save(project=project, workspace_id=project.workspace_id)
        return Response(RegistrationHandoffConfigSerializer(config).data, status=status.HTTP_201_CREATED)

    @allow_permission([ROLE.ADMIN])
    def partial_update(self, request, slug, project_id, pk):
        config = self.get_queryset().filter(pk=pk).first()
        if not config:
            return Response({"error": "Registration handoff config not found"}, status=status.HTTP_404_NOT_FOUND)
        serializer = RegistrationHandoffConfigSerializer(
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
            return Response({"error": "Registration handoff config not found"}, status=status.HTTP_404_NOT_FOUND)
        config.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
