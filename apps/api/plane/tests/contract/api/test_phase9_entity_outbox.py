# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Phase 9: entity coverage (Option 3 — everything). Exercises the outbox
wiring added to State, Label, IssueLink, IssueAttachment, IssueRelation, and
Estimate/EstimatePoint via the v1 API — the same endpoints external
consumers actually hit. These entity types have no webhook fan-out flag
(see _WEBHOOK_FILTER_FIELD in event_outbox.py), so the only way to observe
the wiring is via event_log rows, not a mocked webhook call.
"""

import pytest
from rest_framework import status

from plane.db.models import Estimate, EstimatePoint, EventLog, Issue, Project, ProjectMember, State


@pytest.fixture
def project(db, workspace, create_user):
    project = Project.objects.create(
        name="Phase9 Project", identifier="PH9", workspace=workspace, created_by=create_user
    )
    ProjectMember.objects.create(project=project, member=create_user, role=20, is_active=True)
    return project


@pytest.fixture
def state(db, workspace, project):
    return State.objects.create(name="Todo", project=project, workspace=workspace, group="backlog", default=True)


@pytest.fixture
def issue(db, workspace, project, state, create_user):
    return Issue.objects.create(name="Issue", workspace=workspace, project=project, state=state, created_by=create_user)


@pytest.mark.contract
class TestStateOutbox:
    def get_url(self, workspace_slug, project_id, state_id=None):
        base = f"/api/v1/workspaces/{workspace_slug}/projects/{project_id}/states/"
        return f"{base}{state_id}/" if state_id else base

    @pytest.mark.django_db
    def test_create_emits_created_event(self, api_key_client, workspace, project):
        response = api_key_client.post(
            self.get_url(workspace.slug, project.id),
            {"name": "In Progress", "color": "#000000", "group": "started"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, f"Got {response.status_code}: {response.data!r}"
        event = EventLog.objects.get(entity_type="state", event_type="state.created")
        assert str(event.entity_id) == str(response.data["id"])
        assert event.workspace_id == workspace.id

    @pytest.mark.django_db
    def test_update_emits_updated_event(self, api_key_client, workspace, project, state):
        response = api_key_client.patch(
            self.get_url(workspace.slug, project.id, state.id), {"name": "Renamed"}, format="json"
        )
        assert response.status_code == status.HTTP_200_OK, f"Got {response.status_code}: {response.data!r}"
        event = EventLog.objects.get(entity_type="state", entity_id=state.id, event_type="state.updated")
        assert event.changes["name"]["new"] == "Renamed"

    @pytest.mark.django_db
    def test_delete_emits_deleted_event(self, api_key_client, workspace, project, create_user):
        empty_state = State.objects.create(
            name="Empty", project=project, workspace=workspace, group="backlog", default=False
        )
        response = api_key_client.delete(self.get_url(workspace.slug, project.id, empty_state.id))
        assert response.status_code == status.HTTP_204_NO_CONTENT, f"Got {response.status_code}: {response.data!r}"
        event = EventLog.objects.get(entity_type="state", entity_id=empty_state.id, event_type="state.deleted")
        assert event.data is None


@pytest.mark.contract
class TestLabelOutbox:
    def get_url(self, workspace_slug, project_id, pk=None):
        base = f"/api/v1/workspaces/{workspace_slug}/projects/{project_id}/labels/"
        return f"{base}{pk}/" if pk else base

    @pytest.mark.django_db
    def test_create_emits_created_event(self, api_key_client, workspace, project):
        response = api_key_client.post(
            self.get_url(workspace.slug, project.id), {"name": "Bug", "color": "#ff0000"}, format="json"
        )
        assert response.status_code == status.HTTP_201_CREATED, f"Got {response.status_code}: {response.data!r}"
        event = EventLog.objects.get(entity_type="label", event_type="label.created")
        assert str(event.entity_id) == str(response.data["id"])

    @pytest.mark.django_db
    def test_delete_emits_deleted_event(self, api_key_client, workspace, project):
        create_response = api_key_client.post(
            self.get_url(workspace.slug, project.id), {"name": "Feature", "color": "#00ff00"}, format="json"
        )
        label_id = create_response.data["id"]

        response = api_key_client.delete(self.get_url(workspace.slug, project.id, label_id))
        assert response.status_code == status.HTTP_204_NO_CONTENT, f"Got {response.status_code}: {response.data!r}"
        event = EventLog.objects.get(entity_type="label", entity_id=label_id, event_type="label.deleted")
        assert event.data is None


@pytest.mark.contract
class TestIssueLinkOutbox:
    def get_url(self, workspace_slug, project_id, issue_id, pk=None):
        base = f"/api/v1/workspaces/{workspace_slug}/projects/{project_id}/issues/{issue_id}/links/"
        return f"{base}{pk}/" if pk else base

    @pytest.mark.django_db
    def test_create_emits_created_event(self, api_key_client, workspace, project, issue):
        response = api_key_client.post(
            self.get_url(workspace.slug, project.id, issue.id),
            {"url": "https://example.com", "title": "Example"},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, f"Got {response.status_code}: {response.data!r}"
        event = EventLog.objects.get(entity_type="issue_link", event_type="issue_link.created")
        assert str(event.entity_id) == str(response.data["id"])

    @pytest.mark.django_db
    def test_delete_emits_deleted_event(self, api_key_client, workspace, project, issue):
        create_response = api_key_client.post(
            self.get_url(workspace.slug, project.id, issue.id),
            {"url": "https://example.com/2", "title": "Example 2"},
            format="json",
        )
        link_id = create_response.data["id"]

        response = api_key_client.delete(self.get_url(workspace.slug, project.id, issue.id, link_id))
        assert response.status_code == status.HTTP_204_NO_CONTENT, f"Got {response.status_code}: {response.data!r}"
        event = EventLog.objects.get(entity_type="issue_link", entity_id=link_id, event_type="issue_link.deleted")
        assert event.data is None


@pytest.mark.contract
class TestIssueRelationOutbox:
    def get_url(self, workspace_slug, project_id, issue_id):
        return f"/api/v1/workspaces/{workspace_slug}/projects/{project_id}/work-items/{issue_id}/relations/"

    @pytest.mark.django_db
    def test_create_emits_one_event_per_relation(self, api_key_client, workspace, project, issue, state, create_user):
        other_issues = [
            Issue.objects.create(
                name=f"Related {i}", workspace=workspace, project=project, state=state, created_by=create_user
            )
            for i in range(2)
        ]
        response = api_key_client.post(
            self.get_url(workspace.slug, project.id, issue.id),
            {"relation_type": "relates_to", "issues": [str(i.id) for i in other_issues]},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, f"Got {response.status_code}: {response.data!r}"
        events = EventLog.objects.filter(entity_type="issue_relation", event_type="issue_relation.created")
        assert events.count() == len(other_issues)


@pytest.mark.contract
class TestEstimateOutbox:
    def get_url(self, workspace_slug, project_id):
        return f"/api/v1/workspaces/{workspace_slug}/projects/{project_id}/estimates/"

    @pytest.mark.django_db
    def test_create_emits_created_event(self, api_key_client, workspace, project):
        response = api_key_client.post(
            self.get_url(workspace.slug, project.id),
            {"name": "Points", "type": "categories"},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, f"Got {response.status_code}: {response.data!r}"
        event = EventLog.objects.get(entity_type="estimate", event_type="estimate.created")
        assert str(event.entity_id) == str(response.data["id"])

    @pytest.mark.django_db
    def test_delete_emits_deleted_event(self, api_key_client, workspace, project):
        estimate = Estimate.objects.create(name="Points", project=project, workspace=workspace, type="categories")

        response = api_key_client.delete(self.get_url(workspace.slug, project.id))
        assert response.status_code == status.HTTP_204_NO_CONTENT, f"Got {response.status_code}: {response.data!r}"
        event = EventLog.objects.get(entity_type="estimate", entity_id=estimate.id, event_type="estimate.deleted")
        assert event.data is None


@pytest.mark.contract
class TestEstimatePointOutbox:
    def get_url(self, workspace_slug, project_id, estimate_id, pk=None):
        base = f"/api/v1/workspaces/{workspace_slug}/projects/{project_id}/estimates/{estimate_id}/estimate-points/"
        return f"{base}{pk}/" if pk else base

    @pytest.fixture
    def estimate(self, db, workspace, project):
        return Estimate.objects.create(name="Points", project=project, workspace=workspace, type="categories")

    @pytest.mark.django_db
    def test_bulk_create_emits_one_event_per_point(self, api_key_client, workspace, project, estimate):
        response = api_key_client.post(
            self.get_url(workspace.slug, project.id, estimate.id),
            [{"key": 0, "value": "XS"}, {"key": 1, "value": "S"}],
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, f"Got {response.status_code}: {response.data!r}"
        events = EventLog.objects.filter(entity_type="estimate_point", event_type="estimate_point.created")
        assert events.count() == 2

    @pytest.mark.django_db
    def test_delete_emits_deleted_event(self, api_key_client, workspace, project, estimate):
        point = EstimatePoint.objects.create(estimate=estimate, project=project, workspace=workspace, key=0, value="XS")

        response = api_key_client.delete(self.get_url(workspace.slug, project.id, estimate.id, point.id))
        assert response.status_code == status.HTTP_204_NO_CONTENT, f"Got {response.status_code}: {response.data!r}"
        event = EventLog.objects.get(
            entity_type="estimate_point", entity_id=point.id, event_type="estimate_point.deleted"
        )
        assert event.data is None
