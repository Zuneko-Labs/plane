# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
The `module_issue.created` outbox payload must carry the work item title and
the module name, not just UUIDs — a module maps 1:1 to one builder's billed
hours downstream, so the module name is a join key, and a consumer deciding a
per-module naming convention has to act on this one event without a follow-up
call.

Both create endpoints are covered, and pinned to the same payload keys:
IssueListCreateAPIEndpoint.post (apps/api/plane/api/views/issue.py) for
API-token integrations, and IssueViewSet.create
(apps/api/plane/app/views/issue/base.py) for the web app.
"""

import pytest
from rest_framework import status

from plane.db.models import EventLog, Module, Project, ProjectMember, State

EXPECTED_KEYS = {"id", "module_id", "issue_id", "issue_name", "module_name"}


@pytest.fixture
def project(db, workspace, create_user):
    project = Project.objects.create(
        name="Payload Project",
        identifier="WMP",
        workspace=workspace,
        created_by=create_user,
    )
    ProjectMember.objects.create(project=project, member=create_user, role=20, is_active=True)
    return project


@pytest.fixture
def state(db, workspace, project):
    return State.objects.create(name="Todo", project=project, workspace=workspace, group="backlog", default=True)


@pytest.fixture
def module(db, workspace, project, create_user):
    return Module.objects.create(name="Builder X", project=project, workspace=workspace, created_by=create_user)


def v1_issue_url(workspace_slug, project_id):
    return f"/api/v1/workspaces/{workspace_slug}/projects/{project_id}/issues/"


def app_issue_url(workspace_slug, project_id):
    return f"/api/workspaces/{workspace_slug}/projects/{project_id}/issues/"


@pytest.mark.contract
class TestModuleIssueCreatedPayloadV1API:
    @pytest.mark.django_db
    def test_payload_carries_issue_and_module_names(self, api_key_client, workspace, project, state, module):
        url = v1_issue_url(workspace.slug, project.id)

        response = api_key_client.post(url, {"name": "ACME-1042", "module_ids": [str(module.id)]}, format="json")

        assert response.status_code == status.HTTP_201_CREATED, f"Got {response.status_code}: {response.data!r}"
        event = EventLog.objects.get(entity_type="module_issue", event_type="module_issue.created")
        assert event.data["issue_name"] == "ACME-1042"
        assert event.data["module_name"] == "Builder X"

    @pytest.mark.django_db
    def test_existing_uuid_keys_are_unchanged(self, api_key_client, workspace, project, state, module):
        """The wire contract is additive-only — the original three keys stay."""
        url = v1_issue_url(workspace.slug, project.id)

        response = api_key_client.post(url, {"name": "ACME-1043", "module_ids": [str(module.id)]}, format="json")

        assert response.status_code == status.HTTP_201_CREATED, f"Got {response.status_code}: {response.data!r}"
        event = EventLog.objects.get(entity_type="module_issue", event_type="module_issue.created")
        assert event.data["issue_id"] == str(response.data["id"])
        assert event.data["module_id"] == str(module.id)
        assert event.data["id"] == str(event.entity_id)

    @pytest.mark.django_db
    def test_payload_has_no_top_level_name_key(self, api_key_client, workspace, project, state, module):
        """
        The events API derives an event's `entity_name` from data["name"]. This
        event's entity is the link, not the work item, so a "name" key here
        would surface the work item's title as the link's own name.
        """
        url = v1_issue_url(workspace.slug, project.id)

        response = api_key_client.post(url, {"name": "ACME-1044", "module_ids": [str(module.id)]}, format="json")

        assert response.status_code == status.HTTP_201_CREATED, f"Got {response.status_code}: {response.data!r}"
        event = EventLog.objects.get(entity_type="module_issue", event_type="module_issue.created")
        assert "name" not in event.data


@pytest.mark.contract
class TestModuleIssueCreatedPayloadAppAPI:
    @pytest.mark.django_db
    def test_payload_carries_issue_and_module_names(self, session_client, workspace, project, state, module):
        url = app_issue_url(workspace.slug, project.id)

        response = session_client.post(url, {"name": "ACME-2042", "module_ids": [str(module.id)]}, format="json")

        assert response.status_code == status.HTTP_201_CREATED, f"Got {response.status_code}: {response.data!r}"
        event = EventLog.objects.get(entity_type="module_issue", event_type="module_issue.created")
        assert event.data["issue_name"] == "ACME-2042"
        assert event.data["module_name"] == "Builder X"

    @pytest.mark.django_db
    def test_payload_has_no_top_level_name_key(self, session_client, workspace, project, state, module):
        url = app_issue_url(workspace.slug, project.id)

        response = session_client.post(url, {"name": "ACME-2043", "module_ids": [str(module.id)]}, format="json")

        assert response.status_code == status.HTTP_201_CREATED, f"Got {response.status_code}: {response.data!r}"
        event = EventLog.objects.get(entity_type="module_issue", event_type="module_issue.created")
        assert "name" not in event.data


@pytest.mark.contract
class TestModuleIssueCreatedPayloadParity:
    """
    Both endpoints must emit the same `module_issue.created` keys. This parity
    is deliberately NOT guaranteed for `issue.created`, whose payload shape
    differs between the two paths — which is precisely why a consumer should
    read title-plus-module off this event instead.
    """

    @pytest.mark.django_db
    def test_both_endpoints_emit_identical_payload_keys(
        self, api_client, api_token, create_user, workspace, project, state, module
    ):
        api_client.credentials(HTTP_X_API_KEY=api_token.token)
        v1_response = api_client.post(
            v1_issue_url(workspace.slug, project.id),
            {"name": "ACME-3042", "module_ids": [str(module.id)]},
            format="json",
        )
        assert v1_response.status_code == status.HTTP_201_CREATED, (
            f"Got {v1_response.status_code}: {v1_response.data!r}"
        )

        api_client.credentials()
        api_client.force_authenticate(user=create_user)
        app_response = api_client.post(
            app_issue_url(workspace.slug, project.id),
            {"name": "ACME-3043", "module_ids": [str(module.id)]},
            format="json",
        )
        assert app_response.status_code == status.HTTP_201_CREATED, (
            f"Got {app_response.status_code}: {app_response.data!r}"
        )

        v1_event = EventLog.objects.get(
            entity_type="module_issue", event_type="module_issue.created", data__issue_id=str(v1_response.data["id"])
        )
        app_event = EventLog.objects.get(
            entity_type="module_issue", event_type="module_issue.created", data__issue_id=str(app_response.data["id"])
        )

        assert set(v1_event.data.keys()) == EXPECTED_KEYS
        assert set(app_event.data.keys()) == EXPECTED_KEYS
