# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
from datetime import datetime
from uuid import UUID

# Django imports
from django.db.models import F, Q, DateField
from django.db.models.functions import Cast, Coalesce

# Third party modules
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.app.permissions import ROLE, allow_permission
from plane.app.views.base import BaseAPIView
from plane.db.models import Issue, ProjectMember, WorkspaceMember


class TeamCalendarEndpoint(BaseAPIView):
    """Admin-only member x date matrix of work items for a given date window.

    Returns every active member with the work items assigned to them whose
    start_date/target_date overlap the requested window. Optionally scoped
    to a set of projects.
    """

    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def get(self, request, slug):
        start_date = request.query_params.get("start_date")
        end_date = request.query_params.get("end_date")

        try:
            window_start = datetime.strptime(start_date, "%Y-%m-%d").date()
            window_end = datetime.strptime(end_date, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return Response(
                {"error": "start_date and end_date are required in YYYY-MM-DD format."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if window_start > window_end:
            return Response(
                {"error": "start_date must be on or before end_date."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            project_ids = [
                str(UUID(project_id))
                for project_id in request.query_params.get("project", "").split(",")
                if project_id
            ]
        except ValueError:
            return Response(
                {"error": "project must be a comma-separated list of valid IDs."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if project_ids:
            member_qs = ProjectMember.objects.filter(
                workspace__slug=slug,
                project_id__in=project_ids,
                is_active=True,
                member__is_bot=False,
            )
        else:
            member_qs = WorkspaceMember.objects.filter(
                workspace__slug=slug, is_active=True, member__is_bot=False
            )

        members = {
            str(member["member__id"]): member
            for member in member_qs.values(
                "member__id",
                "member__display_name",
                "member__first_name",
                "member__last_name",
                "member__avatar",
            ).distinct()
        }

        # An issue belongs to the window when its date range overlaps it.
        # Open-ended items (missing target_date) appear in every week after start_date,
        # and items missing start_date appear in every week before target_date.
        # When start_date is null, fall back to created_at.
        window_overlap = (
            Q(effective_start_date__lte=window_end, target_date__gte=window_start)
            | Q(effective_start_date__isnull=True, target_date__gte=window_start)
            | Q(target_date__isnull=True, effective_start_date__lte=window_end)
        )

        # Only show in-progress work — unstarted and started items.
        ACTIVE_STATE_GROUPS = ["unstarted", "started"]

        issues = (
            Issue.issue_objects.filter(
                workspace__slug=slug,
                issue_assignee__assignee_id__in=list(members.keys()),
                issue_assignee__deleted_at__isnull=True,
                state__group__in=ACTIVE_STATE_GROUPS,
            )
            .annotate(
                effective_start_date=Coalesce("start_date", Cast("created_at", output_field=DateField())),
                assignee_id=F("issue_assignee__assignee_id"),
                issue_state_group=F("state__group"),
                project_identifier=F("project__identifier"),
                issue_state_id=F("state__id"),
                issue_state_name=F("state__name"),
                issue_state_color=F("state__color"),
            )
            .filter(window_overlap)
            .values(
                "id",
                "name",
                "sequence_id",
                "priority",
                "project_id",
                "project_identifier",
                "start_date",
                "target_date",
                "assignee_id",
                "issue_state_group",
                "issue_state_id",
                "issue_state_name",
                "issue_state_color",
                "effective_start_date",
            )
            .order_by("effective_start_date", "target_date")
        )

        if project_ids:
            issues = issues.filter(project_id__in=project_ids)

        issues_by_member = {member_id: [] for member_id in members}
        for issue in issues:
            assignee_id = str(issue.pop("assignee_id"))
            if assignee_id in issues_by_member:
                issue["state_group"] = issue.pop("issue_state_group")
                issue["state_id"] = issue.pop("issue_state_id")
                issue["state_name"] = issue.pop("issue_state_name")
                issue["state_color"] = issue.pop("issue_state_color")
                issues_by_member[assignee_id].append(issue)

        response_members = [
            {
                "id": member_id,
                "display_name": member["member__display_name"],
                "first_name": member["member__first_name"],
                "last_name": member["member__last_name"],
                "avatar_url": member["member__avatar"],
                "issues": issues_by_member[member_id],
            }
            for member_id, member in members.items()
        ]
        response_members.sort(key=lambda member: (member["display_name"] or "").lower())

        return Response({"members": response_members}, status=status.HTTP_200_OK)
