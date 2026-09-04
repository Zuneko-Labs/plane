# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
B2 — a work item must belong to exactly one Module. Intake items may be
submitted without a module (the public submission form never asks for one),
but ACCEPTING an intake item into the project (IntakeIssueViewSet.
partial_update in apps/api/plane/app/views/intake/base.py, status -> 1)
must require exactly one module_id.
"""

from unittest.mock import patch

import pytest
from rest_framework import status

from plane.db.models import (
    Intake,
    IntakeIssue,
    Issue,
    Module,
    ModuleIssue,
    Project,
    ProjectMember,
    State,
    StateGroup,
)


@pytest.fixture
def project(db, workspace, create_user):
    project = Project.objects.create(
        name="Intake Module Requirement Project",
        identifier="IMR",
        workspace=workspace,
        created_by=create_user,
    )
    ProjectMember.objects.create(project=project, member=create_user, role=20, is_active=True)
    return project


@pytest.fixture
def intake(db, workspace, project):
    return Intake.objects.create(name="Intake", project=project, workspace=workspace, is_default=True)


@pytest.fixture
def triage_state(db, workspace, project):
    return State.objects.create(
        name="Triage", project=project, workspace=workspace, group=StateGroup.TRIAGE.value, default=False
    )


@pytest.fixture
def default_state(db, workspace, project):
    return State.objects.create(name="Todo", project=project, workspace=workspace, group="backlog", default=True)


@pytest.fixture
def module_a(db, workspace, project, create_user):
    return Module.objects.create(name="Module A", project=project, workspace=workspace, created_by=create_user)


@pytest.fixture
def intake_issue(db, workspace, project, intake, triage_state, default_state, create_user):
    issue = Issue.objects.create(
        name="Submitted work item",
        workspace=workspace,
        project=project,
        state=triage_state,
        created_by=create_user,
    )
    return IntakeIssue.objects.create(intake=intake, issue=issue, project=project, workspace=workspace, status=-2)


def intake_issue_url(workspace_slug, project_id, pk):
    return f"/api/workspaces/{workspace_slug}/projects/{project_id}/intake-issues/{pk}/"


@pytest.mark.contract
class TestIntakeAcceptModuleRequirement:
    @pytest.mark.django_db
    def test_accept_without_module_is_rejected(self, session_client, workspace, project, intake_issue):
        url = intake_issue_url(workspace.slug, project.id, intake_issue.issue_id)

        response = session_client.patch(url, {"status": 1}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, f"Got {response.status_code}: {response.data!r}"
        assert response.data["error"] == "A work item must belong to exactly one module"

        intake_issue.refresh_from_db()
        assert intake_issue.status == -2  # untouched — accept never happened

    @pytest.mark.django_db
    def test_accept_with_one_module_succeeds(
        self, session_client, workspace, project, intake_issue, module_a
    ):
        url = intake_issue_url(workspace.slug, project.id, intake_issue.issue_id)

        with patch("plane.app.views.intake.base.issue_activity"):
            response = session_client.patch(
                url, {"status": 1, "module_ids": [str(module_a.id)]}, format="json"
            )

        assert response.status_code == status.HTTP_200_OK, f"Got {response.status_code}: {response.data!r}"

        intake_issue.refresh_from_db()
        assert intake_issue.status == 1
        assert ModuleIssue.objects.filter(issue_id=intake_issue.issue_id, module_id=module_a.id).exists()

    @pytest.mark.django_db
    def test_accept_with_two_modules_is_rejected(
        self, session_client, workspace, project, intake_issue, module_a, create_user
    ):
        module_b = Module.objects.create(name="Module B", project=project, workspace=workspace, created_by=create_user)
        url = intake_issue_url(workspace.slug, project.id, intake_issue.issue_id)

        response = session_client.patch(
            url, {"status": 1, "module_ids": [str(module_a.id), str(module_b.id)]}, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, f"Got {response.status_code}: {response.data!r}"
        intake_issue.refresh_from_db()
        assert intake_issue.status == -2

    @pytest.mark.django_db
    def test_non_accept_update_does_not_require_module(self, session_client, workspace, project, intake_issue):
        """Snoozing / other status transitions are untouched by this rule —
        the module requirement only applies to status -> accepted (1)."""
        url = intake_issue_url(workspace.slug, project.id, intake_issue.issue_id)

        with patch("plane.app.views.intake.base.issue_activity"):
            response = session_client.patch(url, {"status": -1}, format="json")

        assert response.status_code == status.HTTP_200_OK, f"Got {response.status_code}: {response.data!r}"
