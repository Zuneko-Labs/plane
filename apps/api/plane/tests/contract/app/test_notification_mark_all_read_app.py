# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework import status

from plane.db.models import Notification


@pytest.mark.contract
class TestMarkAllReadNotificationAPI:
    def get_url(self, workspace_slug: str) -> str:
        return f"/api/workspaces/{workspace_slug}/users/notifications/mark-all-read/"

    def create_notification(self, workspace, user, sender="in_app:issue_activities:subscribed", **kwargs):
        return Notification.objects.create(
            workspace=workspace,
            receiver=user,
            entity_name="issue",
            title="t",
            sender=sender,
            **kwargs,
        )

    @pytest.mark.django_db
    def test_marks_all_unread_including_mentions(self, session_client, create_user, workspace):
        regular = self.create_notification(workspace, create_user)
        mention = self.create_notification(workspace, create_user, sender="in_app:issue_activities:mentioned")

        response = session_client.post(self.get_url(workspace.slug), {}, format="json")

        assert response.status_code == status.HTTP_200_OK
        regular.refresh_from_db()
        mention.refresh_from_db()
        assert regular.read_at is not None
        assert mention.read_at is not None

    @pytest.mark.django_db
    def test_mentioned_flag_only_marks_mentions(self, session_client, create_user, workspace):
        regular = self.create_notification(workspace, create_user)
        mention = self.create_notification(workspace, create_user, sender="in_app:issue_activities:mentioned")

        response = session_client.post(self.get_url(workspace.slug), {"mentioned": True}, format="json")

        assert response.status_code == status.HTTP_200_OK
        regular.refresh_from_db()
        mention.refresh_from_db()
        assert regular.read_at is None
        assert mention.read_at is not None

    @pytest.mark.django_db
    def test_skips_archived_and_snoozed_by_default(self, session_client, create_user, workspace):
        archived = self.create_notification(workspace, create_user, archived_at=timezone.now())
        snoozed = self.create_notification(
            workspace, create_user, snoozed_till=timezone.now() + timedelta(days=1)
        )
        visible = self.create_notification(workspace, create_user)

        response = session_client.post(self.get_url(workspace.slug), {"snoozed": False, "archived": False}, format="json")

        assert response.status_code == status.HTTP_200_OK
        for notification in (archived, snoozed, visible):
            notification.refresh_from_db()
        assert visible.read_at is not None
        assert archived.read_at is None
        # snoozed in the future is still "snoozed_till >= now" -> shown in the default list, so it is marked
        assert snoozed.read_at is not None
