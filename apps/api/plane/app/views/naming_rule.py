# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from rest_framework import status
from rest_framework.response import Response

from plane.app.permissions import ROLE, allow_permission
from plane.app.serializers import WorkItemNamingRuleSerializer
from plane.db.models import Project, WorkItemNamingRule

from .base import BaseViewSet


class WorkItemNamingRuleViewSet(BaseViewSet):
    """Admin-only CRUD for the regex a project (or one of its modules) uses
    to validate work item names — lets ops correct a wrong pattern without a
    deploy. Read is open to project members so the create/rename UI can show
    the active pattern; writes are ADMIN-only."""

    serializer_class = WorkItemNamingRuleSerializer
    model = WorkItemNamingRule

    def get_queryset(self):
        return WorkItemNamingRule.objects.filter(
            workspace__slug=self.kwargs.get("slug"),
            project_id=self.kwargs.get("project_id"),
        ).select_related("module")

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def list(self, request, slug, project_id):
        serializer = WorkItemNamingRuleSerializer(self.get_queryset(), many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN])
    def create(self, request, slug, project_id):
        project = Project.objects.get(pk=project_id, workspace__slug=slug)
        serializer = WorkItemNamingRuleSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        naming_rule = serializer.save(project=project, workspace_id=project.workspace_id)
        return Response(WorkItemNamingRuleSerializer(naming_rule).data, status=status.HTTP_201_CREATED)

    @allow_permission([ROLE.ADMIN])
    def partial_update(self, request, slug, project_id, pk):
        naming_rule = self.get_queryset().filter(pk=pk).first()
        if not naming_rule:
            return Response({"error": "Naming rule not found"}, status=status.HTTP_404_NOT_FOUND)
        serializer = WorkItemNamingRuleSerializer(naming_rule, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN])
    def destroy(self, request, slug, project_id, pk):
        naming_rule = self.get_queryset().filter(pk=pk).first()
        if not naming_rule:
            return Response({"error": "Naming rule not found"}, status=status.HTTP_404_NOT_FOUND)
        naming_rule.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
