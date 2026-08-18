# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Phase 7: the incremental sync pull API.

  * dispatch_seq is the only cursor — pending (dispatch_seq IS NULL) rows
    are never returned
  * 410 Gone when `after` has fallen behind the oldest retained dispatch_seq
    for that workspace, never an empty 200 (indistinguishable from caught up)
  * workspace scoping is enforced in the query itself, not the serializer
"""

from uuid import uuid4

import pytest
from rest_framework import status

from plane.bgtasks.event_outbox import write_event
from plane.db.models import Workspace, WorkspaceMember


def _make_event(workspace, dispatch_seq, sequence, entity_type="project"):
    event = write_event(
        workspace_id=workspace.id,
        entity_type=entity_type,
        entity_id=uuid4(),
        event_type=f"{entity_type}.created",
    )
    # write_event/the trigger assign `sequence`; force both columns to the
    # exact values the test needs, bypassing the relay entirely.
    from plane.db.models import EventLog

    EventLog.objects.filter(pk=event.pk).update(dispatch_seq=dispatch_seq, sequence=sequence)
    event.refresh_from_db()
    return event


@pytest.mark.contract
class TestWorkspaceEventsAPIEndpoint:
    def get_url(self, workspace_slug, **params):
        url = f"/api/v1/workspaces/{workspace_slug}/events/"
        if params:
            query = "&".join(f"{k}={v}" for k, v in params.items())
            url += f"?{query}"
        return url

    @pytest.mark.django_db
    def test_returns_events_after_cursor_in_dispatch_seq_order(self, api_key_client, workspace):
        _make_event(workspace, dispatch_seq=1, sequence=1)
        e2 = _make_event(workspace, dispatch_seq=2, sequence=2)
        e3 = _make_event(workspace, dispatch_seq=3, sequence=3)

        response = api_key_client.get(self.get_url(workspace.slug, after=1))

        assert response.status_code == status.HTTP_200_OK, f"Got {response.status_code}: {response.data!r}"
        results = response.data["results"]
        assert [r["dispatch_seq"] for r in results] == [2, 3]
        assert results[0]["id"] == str(e2.id)
        assert results[1]["id"] == str(e3.id)
        assert response.data["next_after"] == 3
        assert response.data["has_more"] is False

    @pytest.mark.django_db
    def test_pending_events_are_never_returned(self, api_key_client, workspace):
        # dispatch_seq still NULL — the relay/fast path hasn't claimed it yet.
        write_event(
            workspace_id=workspace.id, entity_type="project", entity_id=uuid4(), event_type="project.created"
        )
        e_dispatched = _make_event(workspace, dispatch_seq=1, sequence=1)

        response = api_key_client.get(self.get_url(workspace.slug, after=0))

        assert response.status_code == status.HTTP_200_OK
        assert [r["id"] for r in response.data["results"]] == [str(e_dispatched.id)]

    @pytest.mark.django_db
    def test_has_more_and_pagination(self, api_key_client, workspace):
        for i in range(1, 6):
            _make_event(workspace, dispatch_seq=i, sequence=i)

        response = api_key_client.get(self.get_url(workspace.slug, after=0, per_page=2))

        assert response.status_code == status.HTTP_200_OK
        assert [r["dispatch_seq"] for r in response.data["results"]] == [1, 2]
        assert response.data["has_more"] is True
        assert response.data["next_after"] == 2

    @pytest.mark.django_db
    def test_410_when_after_is_below_the_retained_floor(self, api_key_client, workspace):
        # Simulates retention having deleted dispatch_seq 1-9; oldest left is 10.
        _make_event(workspace, dispatch_seq=10, sequence=10)

        response = api_key_client.get(self.get_url(workspace.slug, after=0))

        assert response.status_code == status.HTTP_410_GONE, f"Got {response.status_code}: {response.data!r}"

    @pytest.mark.django_db
    def test_no_410_when_after_is_exactly_at_the_retained_floor(self, api_key_client, workspace):
        _make_event(workspace, dispatch_seq=10, sequence=10)

        # after=9 means "give me everything after 9" — 10 is still fully
        # servable, no gap, so this must NOT be 410.
        response = api_key_client.get(self.get_url(workspace.slug, after=9))

        assert response.status_code == status.HTTP_200_OK
        assert [r["dispatch_seq"] for r in response.data["results"]] == [10]

    @pytest.mark.django_db
    def test_empty_workspace_returns_200_not_410(self, api_key_client, workspace):
        response = api_key_client.get(self.get_url(workspace.slug, after=0))

        assert response.status_code == status.HTTP_200_OK
        assert response.data["results"] == []

    @pytest.mark.django_db
    def test_workspace_scoping_is_enforced_in_the_query(self, api_key_client, workspace, create_user):
        other_workspace = Workspace.objects.create(name="Other Workspace", owner=create_user, slug="other-workspace")
        WorkspaceMember.objects.create(workspace=other_workspace, member=create_user, role=20)

        _make_event(workspace, dispatch_seq=1, sequence=1, entity_type="project")
        _make_event(other_workspace, dispatch_seq=2, sequence=2, entity_type="issue")

        response = api_key_client.get(self.get_url(workspace.slug, after=0))

        assert response.status_code == status.HTTP_200_OK
        entity_types = {r["entity_type"] for r in response.data["results"]}
        assert entity_types == {"project"}

    @pytest.mark.django_db
    def test_non_member_is_forbidden(self, api_client, workspace):
        from plane.db.models import User
        from plane.db.models.api import APIToken

        outsider = User.objects.create(email="outsider@plane.so", username="outsider")
        token = APIToken.objects.create(user=outsider, label="Outsider Token", token="outsider-token-abc")
        api_client.credentials(HTTP_X_API_KEY=token.token)

        response = api_client.get(self.get_url(workspace.slug, after=0))

        assert response.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.django_db
    def test_invalid_after_returns_400(self, api_key_client, workspace):
        response = api_key_client.get(self.get_url(workspace.slug, after="not-a-number"))
        assert response.status_code == status.HTTP_400_BAD_REQUEST

        response = api_key_client.get(self.get_url(workspace.slug, after=-1))
        assert response.status_code == status.HTTP_400_BAD_REQUEST
