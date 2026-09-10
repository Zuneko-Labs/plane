# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Phase 6 regressions: adding/removing issues from a cycle or module must emit
one outbox event per link, not one per request — and these event types
(cycle_issue / module_issue) had zero webhook coverage before this plan
(the filter branches existed but nothing ever dispatched them)."""

import pytest
from rest_framework import status

from plane.db.models import Cycle, CycleIssue, EventLog, Issue, Module, Project, ProjectMember, State


@pytest.fixture
def project(db, workspace, create_user):
    project = Project.objects.create(
        name="Membership Project", identifier="MSP", workspace=workspace, created_by=create_user
    )
    ProjectMember.objects.create(project=project, member=create_user, role=20, is_active=True)
    return project


@pytest.fixture
def state(db, workspace, project):
    return State.objects.create(name="Todo", project=project, workspace=workspace, group="backlog", default=True)


@pytest.fixture
def issues(db, workspace, project, state, create_user):
    return [
        Issue.objects.create(
            name=f"Issue {i}", workspace=workspace, project=project, state=state, created_by=create_user
        )
        for i in range(3)
    ]


@pytest.mark.contract
class TestCycleIssueOutbox:
    def get_url(self, workspace_slug, project_id, cycle_id):
        return f"/api/v1/workspaces/{workspace_slug}/projects/{project_id}/cycles/{cycle_id}/cycle-issues/"

    @pytest.mark.django_db
    def test_adding_issues_emits_one_event_per_issue(self, api_key_client, workspace, project, issues, create_user):
        cycle = Cycle.objects.create(name="Cycle", project=project, workspace=workspace, owned_by=create_user)
        url = self.get_url(workspace.slug, project.id, cycle.id)
        issue_ids = [str(i.id) for i in issues]

        response = api_key_client.post(url, {"issues": issue_ids}, format="json")

        assert response.status_code == status.HTTP_200_OK, f"Got {response.status_code}: {response.data!r}"
        events = EventLog.objects.filter(entity_type="cycle_issue", event_type="cycle_issue.created")
        assert events.count() == len(issues)

    @pytest.mark.django_db
    def test_removing_an_issue_emits_a_deleted_event(self, api_key_client, workspace, project, issues, create_user):
        cycle = Cycle.objects.create(name="Cycle", project=project, workspace=workspace, owned_by=create_user)
        cycle_issue = CycleIssue.objects.create(
            cycle=cycle, issue=issues[0], project=project, workspace=workspace, created_by=create_user
        )
        url = f"{self.get_url(workspace.slug, project.id, cycle.id)}{issues[0].id}/"

        response = api_key_client.delete(url)

        assert response.status_code == status.HTTP_204_NO_CONTENT, f"Got {response.status_code}: {response.data!r}"
        event = EventLog.objects.get(
            entity_type="cycle_issue", entity_id=cycle_issue.id, event_type="cycle_issue.deleted"
        )
        assert event.workspace_id == workspace.id


@pytest.mark.contract
class TestModuleIssueOutbox:
    def get_url(self, workspace_slug, project_id, module_id):
        return f"/api/v1/workspaces/{workspace_slug}/projects/{project_id}/modules/{module_id}/module-issues/"

    @pytest.mark.django_db
    def test_adding_issues_emits_one_event_per_issue(self, api_key_client, workspace, project, issues):
        module = Module.objects.create(name="Module", project=project, workspace=workspace)
        url = self.get_url(workspace.slug, project.id, module.id)
        issue_ids = [str(i.id) for i in issues]

        response = api_key_client.post(url, {"issues": issue_ids}, format="json")

        assert response.status_code == status.HTTP_200_OK, f"Got {response.status_code}: {response.data!r}"
        events = EventLog.objects.filter(entity_type="module_issue", event_type="module_issue.created")
        assert events.count() == len(issues)
