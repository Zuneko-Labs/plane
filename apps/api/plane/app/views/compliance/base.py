# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
from datetime import datetime

# Django imports
from django.db import IntegrityError
from django.utils import timezone

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from ..base import BaseAPIView
from plane.app.permissions import allow_permission, ROLE
from plane.app.serializers import ComplianceCategorySerializer, ComplianceTemplateSerializer
from plane.bgtasks.compliance_task import generate_compliance_issues
from plane.db.models import (
    ComplianceApplicability,
    ComplianceCategory,
    ComplianceTemplate,
    Project,
    Workspace,
)


class ComplianceCategoryEndpoint(BaseAPIView):
    @allow_permission(allowed_roles=[ROLE.ADMIN], level="WORKSPACE")
    def get(self, request, slug, pk=None):
        if pk is None:
            categories = ComplianceCategory.objects.filter(workspace__slug=slug)
            serializer = ComplianceCategorySerializer(categories, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)
        category = ComplianceCategory.objects.get(workspace__slug=slug, pk=pk)
        return Response(ComplianceCategorySerializer(category).data, status=status.HTTP_200_OK)

    @allow_permission(allowed_roles=[ROLE.ADMIN], level="WORKSPACE")
    def post(self, request, slug):
        workspace = Workspace.objects.get(slug=slug)
        serializer = ComplianceCategorySerializer(data=request.data, context={"workspace_id": workspace.id})
        try:
            if serializer.is_valid():
                serializer.save(workspace_id=workspace.id)
                return Response(serializer.data, status=status.HTTP_201_CREATED)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except IntegrityError:
            return Response(
                {"error": "A category with this name already exists in the workspace"},
                status=status.HTTP_400_BAD_REQUEST,
            )

    @allow_permission(allowed_roles=[ROLE.ADMIN], level="WORKSPACE")
    def patch(self, request, slug, pk):
        category = ComplianceCategory.objects.get(workspace__slug=slug, pk=pk)
        serializer = ComplianceCategorySerializer(
            category, data=request.data, context={"workspace_id": category.workspace_id}, partial=True
        )
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @allow_permission(allowed_roles=[ROLE.ADMIN], level="WORKSPACE")
    def delete(self, request, slug, pk):
        category = ComplianceCategory.objects.get(workspace__slug=slug, pk=pk)
        category.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ComplianceTemplateEndpoint(BaseAPIView):
    @allow_permission(allowed_roles=[ROLE.ADMIN], level="WORKSPACE")
    def get(self, request, slug, pk=None):
        if pk is None:
            templates = ComplianceTemplate.objects.filter(workspace__slug=slug).select_related("category")
            serializer = ComplianceTemplateSerializer(templates, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)
        template = ComplianceTemplate.objects.select_related("category").get(workspace__slug=slug, pk=pk)
        return Response(ComplianceTemplateSerializer(template).data, status=status.HTTP_200_OK)

    @allow_permission(allowed_roles=[ROLE.ADMIN], level="WORKSPACE")
    def post(self, request, slug):
        workspace = Workspace.objects.get(slug=slug)
        serializer = ComplianceTemplateSerializer(data=request.data, context={"workspace_id": workspace.id})
        try:
            if serializer.is_valid():
                serializer.save(workspace_id=workspace.id)
                return Response(serializer.data, status=status.HTTP_201_CREATED)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except IntegrityError:
            return Response(
                {"error": "A template with this key already exists in the workspace"},
                status=status.HTTP_400_BAD_REQUEST,
            )

    @allow_permission(allowed_roles=[ROLE.ADMIN], level="WORKSPACE")
    def patch(self, request, slug, pk):
        template = ComplianceTemplate.objects.get(workspace__slug=slug, pk=pk)
        serializer = ComplianceTemplateSerializer(
            template, data=request.data, context={"workspace_id": template.workspace_id}, partial=True
        )
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @allow_permission(allowed_roles=[ROLE.ADMIN], level="WORKSPACE")
    def delete(self, request, slug, pk):
        template = ComplianceTemplate.objects.get(workspace__slug=slug, pk=pk)
        template.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ComplianceApplicabilityEndpoint(BaseAPIView):
    """Toggles one cell of the Applicability grid.

    Mutates the `ComplianceApplicability` through-model row directly rather
    than going through the template serializer's M2M field — Django forbids
    `.set()`/`.add()` on a `through` M2M that carries extra fields, and a
    direct create/soft-delete keeps the audit trail (who applied this, and
    when) that a bare M2M would lose.
    """

    @allow_permission(allowed_roles=[ROLE.ADMIN], level="WORKSPACE")
    def patch(self, request, slug, pk):
        template = ComplianceTemplate.objects.get(workspace__slug=slug, pk=pk)
        project_id = request.data.get("project_id")
        applicable = request.data.get("applicable")

        if not project_id or applicable is None:
            return Response(
                {"error": "project_id and applicable are both required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        project = Project.objects.get(workspace__slug=slug, pk=project_id, archived_at__isnull=True)

        if applicable:
            try:
                ComplianceApplicability.objects.create(
                    project=project,
                    template=template,
                    workspace_id=template.workspace_id,
                    created_by=request.user,
                )
            except IntegrityError:
                # Already applicable — treat as a no-op, not an error, since
                # the grid may re-send a toggle after a stale read.
                pass
        else:
            ComplianceApplicability.objects.filter(project=project, template=template).delete()

        return Response(status=status.HTTP_204_NO_CONTENT)


class ComplianceGenerateEndpoint(BaseAPIView):
    """The "Generate now" manual trigger — runs the engine synchronously
    (not `.delay()`) so the response can show the created/skipped/failed
    summary immediately, same shape the daily Celery Beat run produces."""

    @allow_permission(allowed_roles=[ROLE.ADMIN], level="WORKSPACE")
    def post(self, request, slug):
        as_of_str = request.data.get("as_of")
        as_of = None
        if as_of_str:
            try:
                as_of = datetime.strptime(as_of_str, "%Y-%m-%d").date()
            except ValueError:
                return Response(
                    {"error": "as_of must be in YYYY-MM-DD format"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # Scope the run to this workspace's templates only — a workspace
        # admin triggering "Generate now" shouldn't fan out to every other
        # workspace's compliance templates too.
        summary = generate_compliance_issues(as_of=as_of, workspace_slug=slug)
        return Response(summary, status=status.HTTP_200_OK)
