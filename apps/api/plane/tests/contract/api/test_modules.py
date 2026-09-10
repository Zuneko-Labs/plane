# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Phase 4 outbox-wiring regressions for the module create/update endpoints —
this file had no test coverage at all before now.
"""

from unittest import mock

import pytest
from rest_framework import status

from plane.db.models import EventLog, Module, Project, ProjectMember


@pytest.fixture
def project(db, workspace, create_user):
    project = Project.objects.create(
        name="Test Project",
        identifier="MTP",
        workspace=workspace,
        created_by=create_user,
        module_view=True,
    )
    ProjectMember.objects.create(project=project, member=create_user, role=20, is_active=True)
    return project


@pytest.mark.contract
class TestModuleListCreateAPIEndpoint:
    def get_url(self, workspace_slug, project_id):
        return f"/api/v1/workspaces/{workspace_slug}/projects/{project_id}/modules/"

    @pytest.mark.django_db
    def test_create_module_writes_an_outbox_event(self, api_key_client, workspace, project, create_user):
        url = self.get_url(workspace.slug, project.id)
        payload = {"name": "Test Module", "description": "A test module"}

        response = api_key_client.post(url, payload, format="json")

        assert response.status_code == status.HTTP_201_CREATED, f"Got {response.status_code}: {response.data!r}"
        module = Module.objects.get(id=response.data["id"])

        event = EventLog.objects.get(entity_type="module", entity_id=module.id)
        assert event.event_type == "module.created"
        assert event.workspace_id == workspace.id
        assert event.project_id == project.id
        assert event.dispatch_seq is None  # pending — dispatch_event hasn't run yet

    @pytest.mark.django_db
    def test_update_module_records_a_diff(self, api_key_client, workspace, project, create_user):
        create_response = api_key_client.post(
            self.get_url(workspace.slug, project.id),
            {"name": "Original Name"},
            format="json",
        )
        module_id = create_response.data["id"]

        patch_url = f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}/modules/{module_id}/"
        response = api_key_client.patch(patch_url, {"name": "New Name"}, format="json")

        assert response.status_code == status.HTTP_200_OK, f"Got {response.status_code}: {response.data!r}"
        event = EventLog.objects.filter(entity_type="module", entity_id=module_id, event_type="module.updated").get()
        assert event.changes == {"name": {"old": "Original Name", "new": "New Name"}}

    @pytest.mark.django_db
    def test_no_outbox_event_survives_a_rolled_back_create(self, api_key_client, workspace, project):
        url = self.get_url(workspace.slug, project.id)
        payload = {"name": "Rollback Probe"}

        with mock.patch(
            "plane.api.views.module.Module.objects.get",
            side_effect=RuntimeError("forced failure for rollback test"),
        ):
            response = api_key_client.post(url, payload, format="json")

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR, (
            f"Got {response.status_code}: {response.data!r}"
        )
        assert Module.objects.count() == 0
        assert EventLog.objects.count() == 0
