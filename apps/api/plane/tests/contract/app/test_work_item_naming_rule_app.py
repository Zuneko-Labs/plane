# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
B3 — work item name validation against a per-project / per-module regex
stored in WorkItemNamingRule. Checked on create and on rename. A
module-level rule takes precedence over the project's default rule.

NOTE: the regex patterns used below (CODE-NUMBER, CODE-Name-NUMBER) are the
two provisional examples from the ticket, not confirmed against the
client's real live data — see plane.utils.naming_rules for the caveat.
"""

from unittest.mock import patch

import pytest
from rest_framework import status

from plane.db.models import Issue, Module, Project, ProjectMember, State, WorkItemNamingRule


@pytest.fixture
def project(db, workspace, create_user):
    project = Project.objects.create(
        name="Naming Rule Project", identifier="NRP", workspace=workspace, created_by=create_user
    )
    ProjectMember.objects.create(project=project, member=create_user, role=20, is_active=True)
    return project


@pytest.fixture
def state(db, workspace, project):
    return State.objects.create(name="Todo", project=project, workspace=workspace, group="backlog", default=True)


@pytest.fixture
def module(db, workspace, project, create_user):
    return Module.objects.create(name="Builder X", project=project, workspace=workspace, created_by=create_user)


@pytest.fixture
def b2c_module(db, workspace, project, create_user):
    return Module.objects.create(name="B2C", project=project, workspace=workspace, created_by=create_user)


@pytest.fixture
def project_default_rule(db, project):
    """CODE-NUMBER, e.g. NRP-101 — the project's default naming rule."""
    return WorkItemNamingRule.objects.create(
        project=project,
        module=None,
        regex_pattern=r"^[A-Za-z0-9]+-\d+$",
        example="NRP-101",
    )


@pytest.fixture
def b2c_module_rule(db, project, b2c_module):
    """CODE-Name-NUMBER, e.g. NRP-Society-102 — overrides the project
    default for work items in the shared B2C module."""
    return WorkItemNamingRule.objects.create(
        project=project,
        module=b2c_module,
        regex_pattern=r"^[A-Za-z0-9]+-[A-Za-z]+-\d+$",
        example="NRP-Society-102",
    )


def issue_url(workspace_slug, project_id):
    return f"/api/workspaces/{workspace_slug}/projects/{project_id}/issues/"


def issue_detail_url(workspace_slug, project_id, pk):
    return f"/api/workspaces/{workspace_slug}/projects/{project_id}/issues/{pk}/"


@pytest.mark.contract
class TestWorkItemNamingRuleOnCreate:
    @pytest.mark.django_db
    def test_name_matching_project_rule_succeeds(self, session_client, workspace, project, state, module, project_default_rule):
        url = issue_url(workspace.slug, project.id)

        with patch("plane.app.views.issue.base.issue_activity"):
            response = session_client.post(
                url, {"name": "NRP-101", "state_id": str(state.id), "module_ids": [str(module.id)]}, format="json"
            )

        assert response.status_code == status.HTTP_201_CREATED, f"Got {response.status_code}: {response.data!r}"

    @pytest.mark.django_db
    def test_name_not_matching_project_rule_rejected(self, session_client, workspace, project, state, module, project_default_rule):
        url = issue_url(workspace.slug, project.id)

        response = session_client.post(
            url,
            {"name": "not-a-valid-name", "state_id": str(state.id), "module_ids": [str(module.id)]},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, f"Got {response.status_code}: {response.data!r}"
        # The error must carry the pattern and a valid example, not just "invalid name".
        error = response.data.get("error", "")
        assert project_default_rule.regex_pattern in error
        assert project_default_rule.example in error
        assert not Issue.objects.filter(name="not-a-valid-name", project=project).exists()

    @pytest.mark.django_db
    def test_module_rule_overrides_project_default(
        self, session_client, workspace, project, state, b2c_module, project_default_rule, b2c_module_rule
    ):
        """A work item in the B2C module must match the B2C pattern
        (CODE-Name-NUMBER), even though it would fail the project's default
        CODE-NUMBER pattern."""
        url = issue_url(workspace.slug, project.id)

        with patch("plane.app.views.issue.base.issue_activity"):
            response = session_client.post(
                url,
                {"name": "NRP-Society-102", "state_id": str(state.id), "module_ids": [str(b2c_module.id)]},
                format="json",
            )

        assert response.status_code == status.HTTP_201_CREATED, f"Got {response.status_code}: {response.data!r}"

    @pytest.mark.django_db
    def test_no_rule_configured_allows_any_name(self, session_client, workspace, project, state, module):
        """Projects with no rule row yet aren't blocked — B3 rolls out per
        project, not as a blanket constraint."""
        url = issue_url(workspace.slug, project.id)

        with patch("plane.app.views.issue.base.issue_activity"):
            response = session_client.post(
                url, {"name": "anything at all", "state_id": str(state.id), "module_ids": [str(module.id)]}, format="json"
            )

        assert response.status_code == status.HTTP_201_CREATED, f"Got {response.status_code}: {response.data!r}"


@pytest.mark.contract
class TestWorkItemNamingRuleOnRename:
    @pytest.mark.django_db
    def test_rename_to_non_matching_name_rejected(
        self, session_client, workspace, project, state, module, create_user, project_default_rule
    ):
        issue = Issue.objects.create(
            name="NRP-101", workspace=workspace, project=project, state=state, created_by=create_user
        )
        from plane.db.models import ModuleIssue

        ModuleIssue.objects.create(
            issue=issue, module=module, project=project, workspace=workspace, created_by=create_user
        )
        url = issue_detail_url(workspace.slug, project.id, issue.id)

        response = session_client.patch(url, {"name": "renamed wrong"}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, f"Got {response.status_code}: {response.data!r}"
        issue.refresh_from_db()
        assert issue.name == "NRP-101"

    @pytest.mark.django_db
    def test_rename_to_matching_name_succeeds(
        self, session_client, workspace, project, state, module, create_user, project_default_rule
    ):
        issue = Issue.objects.create(
            name="NRP-101", workspace=workspace, project=project, state=state, created_by=create_user
        )
        from plane.db.models import ModuleIssue

        ModuleIssue.objects.create(
            issue=issue, module=module, project=project, workspace=workspace, created_by=create_user
        )
        url = issue_detail_url(workspace.slug, project.id, issue.id)

        response = session_client.patch(url, {"name": "NRP-202"}, format="json")

        assert response.status_code == status.HTTP_200_OK, f"Got {response.status_code}: {response.data!r}"
        issue.refresh_from_db()
        assert issue.name == "NRP-202"
