# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
A3 — permission regression tests for the in-app work item delete paths.

A Contributor (ProjectMember role=MEMBER/15) must get a 403 and the work
item must survive. A Project Admin (role=ADMIN/20) must be able to delete.
Covers: single delete, bulk delete, and sub-issue delete (the sub-issue path
reuses IssueViewSet.destroy on the sub-issue's own pk, so it is exercised
here rather than against a separate endpoint).
"""

from unittest.mock import patch

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from plane.db.models import Issue, Project, ProjectMember, State, User


@pytest.fixture
def project(db, workspace, create_user):
    """Project with the workspace owner as an active project admin."""
    project = Project.objects.create(
        name="Delete Permissions Project",
        identifier="DPP",
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
    """A second user, distinct from the workspace owner, holding project ADMIN."""
    user = User.objects.create(email="admin@plane.so", first_name="Admin", last_name="User")
    user.set_password("password")
    user.save()
    ProjectMember.objects.create(project=project, member=user, role=20, is_active=True)
    return user


@pytest.fixture
def contributor(db, project):
    """A Contributor: ProjectMember role=MEMBER (15), not an admin."""
    user = User.objects.create(email="contributor@plane.so", first_name="Contributor", last_name="User")
    user.set_password("password")
    user.save()
    ProjectMember.objects.create(project=project, member=user, role=15, is_active=True)
    return user


@pytest.fixture
def admin_client(project_admin):
    client = APIClient()
    client.force_authenticate(user=project_admin)
    return client


@pytest.fixture
def contributor_client(contributor):
    client = APIClient()
    client.force_authenticate(user=contributor)
    return client


def issue_url(workspace_slug, project_id, pk):
    return f"/api/workspaces/{workspace_slug}/projects/{project_id}/issues/{pk}/"


def bulk_delete_url(workspace_slug, project_id):
    return f"/api/workspaces/{workspace_slug}/projects/{project_id}/bulk-delete-issues/"


@pytest.mark.contract
class TestSingleIssueDeletePermissions:
    @pytest.mark.django_db
    def test_contributor_cannot_delete_issue(self, contributor_client, workspace, project, state, contributor):
        issue = Issue.objects.create(name="Contributor's issue", workspace=workspace, project=project, state=state, created_by=contributor)
        url = issue_url(workspace.slug, project.id, issue.id)

        response = contributor_client.delete(url)

        assert response.status_code == status.HTTP_403_FORBIDDEN, f"Got {response.status_code}: {response.data!r}"
        assert Issue.objects.filter(pk=issue.id).exists()

    @pytest.mark.django_db
    def test_project_admin_can_delete_issue(self, admin_client, workspace, project, state, project_admin):
        issue = Issue.objects.create(name="Issue to delete", workspace=workspace, project=project, state=state, created_by=project_admin)
        url = issue_url(workspace.slug, project.id, issue.id)

        with patch("plane.app.views.issue.base.issue_activity"):
            response = admin_client.delete(url)

        assert response.status_code == status.HTTP_204_NO_CONTENT, f"Got {response.status_code}: {response.data!r}"
        assert not Issue.objects.filter(pk=issue.id).exists()


@pytest.mark.contract
class TestBulkDeleteIssuesPermissions:
    @pytest.mark.django_db
    def test_contributor_cannot_bulk_delete(self, contributor_client, workspace, project, state, contributor):
        issues = [
            Issue.objects.create(name=f"Bulk issue {i}", workspace=workspace, project=project, state=state, created_by=contributor)
            for i in range(2)
        ]
        url = bulk_delete_url(workspace.slug, project.id)

        response = contributor_client.delete(url, {"issue_ids": [str(i.id) for i in issues]}, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN, f"Got {response.status_code}: {response.data!r}"
        for issue in issues:
            assert Issue.objects.filter(pk=issue.id).exists()

    @pytest.mark.django_db
    def test_project_admin_can_bulk_delete(self, admin_client, workspace, project, state, project_admin):
        issues = [
            Issue.objects.create(name=f"Bulk issue {i}", workspace=workspace, project=project, state=state, created_by=project_admin)
            for i in range(2)
        ]
        url = bulk_delete_url(workspace.slug, project.id)

        response = admin_client.delete(url, {"issue_ids": [str(i.id) for i in issues]}, format="json")

        assert response.status_code == status.HTTP_200_OK, f"Got {response.status_code}: {response.data!r}"
        for issue in issues:
            assert not Issue.objects.filter(pk=issue.id).exists()


@pytest.mark.contract
class TestSubIssueDeletePermissions:
    """Sub-issues are plain Issue rows with parent set; deleting one goes
    through the exact same IssueViewSet.destroy as a top-level issue."""

    @pytest.mark.django_db
    def test_contributor_cannot_delete_sub_issue(self, contributor_client, workspace, project, state, contributor):
        parent = Issue.objects.create(name="Parent issue", workspace=workspace, project=project, state=state, created_by=contributor)
        sub_issue = Issue.objects.create(
            name="Sub issue", workspace=workspace, project=project, state=state, created_by=contributor, parent=parent
        )
        url = issue_url(workspace.slug, project.id, sub_issue.id)

        response = contributor_client.delete(url)

        assert response.status_code == status.HTTP_403_FORBIDDEN, f"Got {response.status_code}: {response.data!r}"
        assert Issue.objects.filter(pk=sub_issue.id).exists()

    @pytest.mark.django_db
    def test_project_admin_can_delete_sub_issue(self, admin_client, workspace, project, state, project_admin):
        parent = Issue.objects.create(name="Parent issue", workspace=workspace, project=project, state=state, created_by=project_admin)
        sub_issue = Issue.objects.create(
            name="Sub issue", workspace=workspace, project=project, state=state, created_by=project_admin, parent=parent
        )
        url = issue_url(workspace.slug, project.id, sub_issue.id)

        with patch("plane.app.views.issue.base.issue_activity"):
            response = admin_client.delete(url)

        assert response.status_code == status.HTTP_204_NO_CONTENT, f"Got {response.status_code}: {response.data!r}"
        assert not Issue.objects.filter(pk=sub_issue.id).exists()
