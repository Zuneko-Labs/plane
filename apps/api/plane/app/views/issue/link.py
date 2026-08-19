# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import json

# Django imports
from django.utils import timezone
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction

# Third Party imports
from rest_framework.response import Response
from rest_framework import status

# Module imports
from .. import BaseViewSet
from plane.app.serializers import IssueLinkSerializer
from plane.app.permissions import ProjectEntityPermission
from plane.bgtasks.event_outbox import emit_delete_event, emit_model_event
from plane.db.models import IssueLink
from plane.bgtasks.issue_activities_task import issue_activity
from plane.bgtasks.work_item_link_task import crawl_work_item_link_title
from plane.utils.host import base_host


class IssueLinkViewSet(BaseViewSet):
    permission_classes = [ProjectEntityPermission]

    model = IssueLink
    serializer_class = IssueLinkSerializer

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .filter(workspace__slug=self.kwargs.get("slug"))
            .filter(project_id=self.kwargs.get("project_id"))
            .filter(issue_id=self.kwargs.get("issue_id"))
            .filter(
                project__project_projectmember__member=self.request.user,
                project__project_projectmember__is_active=True,
                project__archived_at__isnull=True,
            )
            .order_by("-created_at")
            .distinct()
        )

    def create(self, request, slug, project_id, issue_id):
        serializer = IssueLinkSerializer(data=request.data)
        if serializer.is_valid():
            with transaction.atomic():
                serializer.save(project_id=project_id, issue_id=issue_id)
                issue_link = IssueLink.objects.get(id=serializer.data.get("id"))

                emit_model_event(
                    model_name="issue_link",
                    model_id=str(issue_link.id),
                    requested_data=request.data,
                    current_instance=None,
                    actor_id=request.user.id,
                    workspace_id=issue_link.workspace_id,
                    project_id=issue_link.project_id,
                )

                def _dispatch_link_created():
                    crawl_work_item_link_title.delay(serializer.data.get("id"), serializer.data.get("url"))
                    issue_activity.delay(
                        type="link.activity.created",
                        requested_data=json.dumps(serializer.data, cls=DjangoJSONEncoder),
                        actor_id=str(self.request.user.id),
                        issue_id=str(self.kwargs.get("issue_id")),
                        project_id=str(self.kwargs.get("project_id")),
                        current_instance=None,
                        epoch=int(timezone.now().timestamp()),
                        notification=True,
                        origin=base_host(request=request, is_app=True),
                    )

                transaction.on_commit(_dispatch_link_created, robust=True)

            issue_link = self.get_queryset().get(id=serializer.data.get("id"))
            serializer = IssueLinkSerializer(issue_link)

            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def partial_update(self, request, slug, project_id, issue_id, pk):
        issue_link = IssueLink.objects.get(workspace__slug=slug, project_id=project_id, issue_id=issue_id, pk=pk)
        requested_data = json.dumps(request.data, cls=DjangoJSONEncoder)
        current_instance = json.dumps(IssueLinkSerializer(issue_link).data, cls=DjangoJSONEncoder)

        serializer = IssueLinkSerializer(issue_link, data=request.data, partial=True)
        if serializer.is_valid():
            with transaction.atomic():
                serializer.save()

                emit_model_event(
                    model_name="issue_link",
                    model_id=str(issue_link.id),
                    requested_data=request.data,
                    current_instance=current_instance,
                    actor_id=request.user.id,
                    workspace_id=issue_link.workspace_id,
                    project_id=issue_link.project_id,
                )

                def _dispatch_link_updated():
                    crawl_work_item_link_title.delay(serializer.data.get("id"), serializer.data.get("url"))
                    issue_activity.delay(
                        type="link.activity.updated",
                        requested_data=requested_data,
                        actor_id=str(request.user.id),
                        issue_id=str(issue_id),
                        project_id=str(project_id),
                        current_instance=current_instance,
                        epoch=int(timezone.now().timestamp()),
                        notification=True,
                        origin=base_host(request=request, is_app=True),
                    )

                transaction.on_commit(_dispatch_link_updated, robust=True)

            issue_link = self.get_queryset().get(id=serializer.data.get("id"))
            serializer = IssueLinkSerializer(issue_link)

            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def destroy(self, request, slug, project_id, issue_id, pk):
        issue_link = IssueLink.objects.get(workspace__slug=slug, project_id=project_id, issue_id=issue_id, pk=pk)
        current_instance = json.dumps(IssueLinkSerializer(issue_link).data, cls=DjangoJSONEncoder)
        link_name = issue_link.title or issue_link.url
        with transaction.atomic():
            issue_link.delete()

            emit_delete_event(
                model_name="issue_link",
                entity_id=str(pk),
                actor_id=request.user.id,
                workspace_id=issue_link.workspace_id,
                project_id=issue_link.project_id,
                entity_name=link_name,
            )

            def _dispatch_link_deleted():
                issue_activity.delay(
                    type="link.activity.deleted",
                    requested_data=json.dumps({"link_id": str(pk)}),
                    actor_id=str(request.user.id),
                    issue_id=str(issue_id),
                    project_id=str(project_id),
                    current_instance=current_instance,
                    epoch=int(timezone.now().timestamp()),
                    notification=True,
                    origin=base_host(request=request, is_app=True),
                )

            transaction.on_commit(_dispatch_link_deleted, robust=True)
        return Response(status=status.HTTP_204_NO_CONTENT)
