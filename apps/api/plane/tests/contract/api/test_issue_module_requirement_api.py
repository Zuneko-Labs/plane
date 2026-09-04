# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
B2 — a work item must belong to exactly one Module, never zero, never
two-or-more simultaneously. Covers the external REST API create endpoint:
IssueListCreateAPIEndpoint.post (apps/api/plane/api/views/issue.py), used by
API-token integrations.
"""

import pytest
from rest_framework import status

from plane.db.models import Issue, Module, ModuleIssue, Project, ProjectMember, State


@pytest.fixture
def project(db, workspace, create_user):
    project = Project.objects.create(
        name="Test Project",
        identifier="MRA",
        workspace=workspace,
        created_by=create_user,
    )
    ProjectMember.objects.create(project=project, member=create_user, role=20, is_active=True)
    return project


@pytest.fixture
def state(db, workspace, project):
    return State.objects.create(name="Todo", project=project, workspace=workspace, group="backlog", default=True)


@pytest.fixture
def module_a(db, workspace, project, create_user):
    return Module.objects.create(name="Module A", project=project, workspace=workspace, created_by=create_user)


@pytest.fixture
def module_b(db, workspace, project, create_user):
    return Module.objects.create(name="Module B", project=project, workspace=workspace, created_by=create_user)


def issue_url(workspace_slug, project_id):
    return f"/api/v1/workspaces/{workspace_slug}/projects/{project_id}/issues/"


@pytest.mark.contract
class TestIssueListCreateAPIEndpointModuleRequirement:
    @pytest.mark.django_db
    def test_create_with_zero_modules_is_rejected(self, api_key_client, workspace, project, state):
        url = issue_url(workspace.slug, project.id)

        response = api_key_client.post(url, {"name": "No module issue"}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, f"Got {response.status_code}: {response.data!r}"
        assert response.data["error"] == "A work item must belong to exactly one module"
        assert not Issue.objects.filter(name="No module issue").exists()

    @pytest.mark.django_db
    def test_create_with_one_module_succeeds(self, api_key_client, workspace, project, state, module_a):
        url = issue_url(workspace.slug, project.id)

        response = api_key_client.post(
            url, {"name": "One module issue", "module_ids": [str(module_a.id)]}, format="json"
        )

        assert response.status_code == status.HTTP_201_CREATED, f"Got {response.status_code}: {response.data!r}"
        issue_id = response.data["id"]
        assert ModuleIssue.objects.filter(issue_id=issue_id, module_id=module_a.id).exists()

    @pytest.mark.django_db
    def test_create_with_two_modules_is_rejected(self, api_key_client, workspace, project, state, module_a, module_b):
        url = issue_url(workspace.slug, project.id)

        response = api_key_client.post(
            url,
            {"name": "Two module issue", "module_ids": [str(module_a.id), str(module_b.id)]},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, f"Got {response.status_code}: {response.data!r}"
        assert response.data["error"] == "A work item must belong to exactly one module"
        assert not Issue.objects.filter(name="Two module issue").exists()
