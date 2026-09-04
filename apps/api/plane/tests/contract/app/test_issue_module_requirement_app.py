# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
B2 — a work item must belong to exactly one Module, never zero, never
two-or-more simultaneously. Covers the in-app endpoints:

- IssueViewSet.create              (apps/api/plane/app/views/issue/base.py)
- ModuleIssueViewSet.create_issue_modules   (apps/api/plane/app/views/module/issue.py)
- ModuleIssueViewSet.create_module_issues   (apps/api/plane/app/views/module/issue.py)

Moving a work item between modules (remove old + add new in one call) is
explicitly fine; only a final count of 0 or 2+ is rejected with HTTP 400.
"""

from unittest.mock import patch

import pytest
from rest_framework import status

from plane.db.models import Issue, Module, ModuleIssue, Project, ProjectMember, State


@pytest.fixture
def project(db, workspace, create_user):
    project = Project.objects.create(
        name="Module Requirement Project",
        identifier="MRP",
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


@pytest.fixture
def issue(db, workspace, project, state, create_user):
    return Issue.objects.create(name="Test Issue", workspace=workspace, project=project, state=state, created_by=create_user)


def issue_create_url(workspace_slug, project_id):
    return f"/api/workspaces/{workspace_slug}/projects/{project_id}/issues/"


def create_issue_modules_url(workspace_slug, project_id, issue_id):
    return f"/api/workspaces/{workspace_slug}/projects/{project_id}/issues/{issue_id}/modules/"


def create_module_issues_url(workspace_slug, project_id, module_id):
    return f"/api/workspaces/{workspace_slug}/projects/{project_id}/modules/{module_id}/issues/"


@pytest.mark.contract
class TestIssueCreateModuleRequirement:
    @pytest.mark.django_db
    def test_create_with_zero_modules_is_rejected(self, session_client, workspace, project, state):
        url = issue_create_url(workspace.slug, project.id)

        response = session_client.post(url, {"name": "No module issue"}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, f"Got {response.status_code}: {response.data!r}"
        assert response.data["error"] == "A work item must belong to exactly one module"
        assert not Issue.objects.filter(name="No module issue").exists()

    @pytest.mark.django_db
    def test_create_with_one_module_succeeds(self, session_client, workspace, project, state, module_a):
        url = issue_create_url(workspace.slug, project.id)

        with patch("plane.app.views.issue.base.issue_activity"), patch(
            "plane.app.views.issue.base.model_activity"
        ), patch("plane.app.views.issue.base.issue_description_version_task"):
            response = session_client.post(
                url, {"name": "One module issue", "module_ids": [str(module_a.id)]}, format="json"
            )

        assert response.status_code == status.HTTP_201_CREATED, f"Got {response.status_code}: {response.data!r}"
        issue_id = response.data["id"]
        assert ModuleIssue.objects.filter(issue_id=issue_id, module_id=module_a.id).exists()

    @pytest.mark.django_db
    def test_create_with_two_modules_is_rejected(self, session_client, workspace, project, state, module_a, module_b):
        url = issue_create_url(workspace.slug, project.id)

        response = session_client.post(
            url,
            {"name": "Two module issue", "module_ids": [str(module_a.id), str(module_b.id)]},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, f"Got {response.status_code}: {response.data!r}"
        assert response.data["error"] == "A work item must belong to exactly one module"
        assert not Issue.objects.filter(name="Two module issue").exists()


@pytest.mark.contract
class TestCreateIssueModules:
    """ModuleIssueViewSet.create_issue_modules — adds/removes modules for a
    single issue in one atomic call."""

    @pytest.mark.django_db
    def test_adding_a_second_module_is_rejected(
        self, session_client, workspace, project, issue, module_a, module_b, create_user
    ):
        ModuleIssue.objects.create(
            issue=issue, module=module_a, project=project, workspace=workspace, created_by=create_user
        )
        url = create_issue_modules_url(workspace.slug, project.id, issue.id)

        response = session_client.post(url, {"modules": [str(module_b.id)]}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, f"Got {response.status_code}: {response.data!r}"
        assert response.data["error"] == "A work item must belong to exactly one module"
        # DB untouched — issue still belongs only to module_a
        assert list(ModuleIssue.objects.filter(issue=issue).values_list("module_id", flat=True)) == [module_a.id]

    @pytest.mark.django_db
    def test_move_remove_old_add_new_in_one_call_succeeds(
        self, session_client, workspace, project, issue, module_a, module_b, create_user
    ):
        ModuleIssue.objects.create(
            issue=issue, module=module_a, project=project, workspace=workspace, created_by=create_user
        )
        url = create_issue_modules_url(workspace.slug, project.id, issue.id)

        with patch("plane.app.views.module.issue.issue_activity"):
            response = session_client.post(
                url,
                {"modules": [str(module_b.id)], "removed_modules": [str(module_a.id)]},
                format="json",
            )

        assert response.status_code == status.HTTP_201_CREATED, f"Got {response.status_code}: {response.data!r}"
        remaining = list(ModuleIssue.objects.filter(issue=issue).values_list("module_id", flat=True))
        assert remaining == [module_b.id]

    @pytest.mark.django_db
    def test_removing_the_only_module_without_replacement_is_rejected(
        self, session_client, workspace, project, issue, module_a, create_user
    ):
        ModuleIssue.objects.create(
            issue=issue, module=module_a, project=project, workspace=workspace, created_by=create_user
        )
        url = create_issue_modules_url(workspace.slug, project.id, issue.id)

        response = session_client.post(url, {"removed_modules": [str(module_a.id)]}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, f"Got {response.status_code}: {response.data!r}"
        assert ModuleIssue.objects.filter(issue=issue, module=module_a).exists()


@pytest.mark.contract
class TestCreateModuleIssues:
    """ModuleIssueViewSet.create_module_issues — additive-only bulk attach of
    existing issues to one module."""

    @pytest.mark.django_db
    def test_attaching_issue_already_in_another_module_is_rejected(
        self, session_client, workspace, project, issue, module_a, module_b, create_user
    ):
        ModuleIssue.objects.create(
            issue=issue, module=module_a, project=project, workspace=workspace, created_by=create_user
        )
        url = create_module_issues_url(workspace.slug, project.id, module_b.id)

        response = session_client.post(url, {"issues": [str(issue.id)]}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, f"Got {response.status_code}: {response.data!r}"
        assert response.data["error"] == "A work item must belong to exactly one module"
        # Not attached to module_b, and still attached to module_a only
        assert not ModuleIssue.objects.filter(issue=issue, module=module_b).exists()
        assert ModuleIssue.objects.filter(issue=issue, module=module_a).exists()

    @pytest.mark.django_db
    def test_attaching_a_moduleless_issue_succeeds(self, session_client, workspace, project, issue, module_a):
        url = create_module_issues_url(workspace.slug, project.id, module_a.id)

        with patch("plane.app.views.module.issue.issue_activity"):
            response = session_client.post(url, {"issues": [str(issue.id)]}, format="json")

        assert response.status_code == status.HTTP_201_CREATED, f"Got {response.status_code}: {response.data!r}"
        assert ModuleIssue.objects.filter(issue=issue, module=module_a).exists()
