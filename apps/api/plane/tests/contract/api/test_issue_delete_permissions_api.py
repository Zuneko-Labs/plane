# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
A3 — permission regression tests for the external REST API work item delete
path (IssueDetailAPIEndpoint.delete), the path API-token integrations hit.

A Contributor (ProjectMember role=MEMBER/15) must get a 403 and the work
item must survive. A Project Admin (role=ADMIN/20) must be able to delete.
"""

from unittest.mock import patch

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from plane.db.models import Issue, Project, ProjectMember, State, User
from plane.db.models.api import APIToken


@pytest.fixture
def project(db, workspace, create_user):
    project = Project.objects.create(
        name="Delete Permissions API Project",
        identifier="DPA",
        workspace=workspace,
        created_by=create_user,
    )
    ProjectMember.objects.create(project=project, member=create_user, role=20, is_active=True)
    return project


@pytest.fixture
def state(db, workspace, project):
    return State.objects.create(name="Todo", project=project, workspace=workspace, group="backlog", default=True)


@pytest.fixture
def project_admin(db, project):
    user = User.objects.create(email="api-admin@plane.so", first_name="Admin", last_name="User")
    user.set_password("password")
    user.save()
    ProjectMember.objects.create(project=project, member=user, role=20, is_active=True)
    return user


@pytest.fixture
def contributor(db, project):
    user = User.objects.create(email="api-contributor@plane.so", first_name="Contributor", last_name="User")
    user.set_password("password")
    user.save()
    ProjectMember.objects.create(project=project, member=user, role=15, is_active=True)
    return user


def _client_for(user, label):
    token = APIToken.objects.create(user=user, label=label, token=f"test-token-{user.id}")
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=token.token)
    return client


@pytest.fixture
def admin_api_client(project_admin):
    return _client_for(project_admin, "Admin Token")


@pytest.fixture
def contributor_api_client(contributor):
    return _client_for(contributor, "Contributor Token")


def issue_url(workspace_slug, project_id, pk):
    return f"/api/v1/workspaces/{workspace_slug}/projects/{project_id}/issues/{pk}/"


@pytest.mark.contract
class TestExternalApiIssueDeletePermissions:
    @pytest.mark.django_db
    def test_contributor_cannot_delete_issue(self, contributor_api_client, workspace, project, state, contributor):
        issue = Issue.objects.create(
            name="Contributor's issue", workspace=workspace, project=project, state=state, created_by=contributor
        )
        url = issue_url(workspace.slug, project.id, issue.id)

        response = contributor_api_client.delete(url)

        assert response.status_code == status.HTTP_403_FORBIDDEN, f"Got {response.status_code}: {response.data!r}"
        assert Issue.objects.filter(pk=issue.id).exists()

    @pytest.mark.django_db
    def test_project_admin_can_delete_issue(self, admin_api_client, workspace, project, state, project_admin):
        issue = Issue.objects.create(
            name="Issue to delete", workspace=workspace, project=project, state=state, created_by=project_admin
        )
        url = issue_url(workspace.slug, project.id, issue.id)

        with patch("plane.api.views.issue.issue_activity"):
            response = admin_api_client.delete(url)

        assert response.status_code == status.HTTP_204_NO_CONTENT, f"Got {response.status_code}: {response.data!r}"
        assert not Issue.objects.filter(pk=issue.id).exists()

    @pytest.mark.django_db
    def test_creator_who_is_not_admin_cannot_delete_issue(
        self, contributor_api_client, workspace, project, state, contributor
    ):
        """Regression guard: being the work item's creator no longer bypasses
        the admin check (the loophole A1 closed)."""
        issue = Issue.objects.create(
            name="Created by contributor", workspace=workspace, project=project, state=state, created_by=contributor
        )
        url = issue_url(workspace.slug, project.id, issue.id)

        response = contributor_api_client.delete(url)

        assert response.status_code == status.HTTP_403_FORBIDDEN, f"Got {response.status_code}: {response.data!r}"
        assert Issue.objects.filter(pk=issue.id).exists()
