# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Phase 5 regression: BulkArchiveIssuesEndpoint must emit one outbox event per
archived issue, not one per request — easy to get wrong, called out
explicitly in the sync architecture plan.
"""

import pytest
from rest_framework import status

from plane.db.models import EventLog, Issue, Project, ProjectMember, State


@pytest.fixture
def project(db, workspace, create_user):
    project = Project.objects.create(
        name="Bulk Archive Project",
        identifier="BAP",
        workspace=workspace,
        created_by=create_user,
    )
    ProjectMember.objects.create(project=project, member=create_user, role=20, is_active=True)
    return project


@pytest.fixture
def completed_state(db, workspace, project):
    return State.objects.create(name="Done", project=project, workspace=workspace, group="completed")


@pytest.fixture
def issues(db, workspace, project, completed_state, create_user):
    return [
        Issue.objects.create(
            name=f"Issue {i}", workspace=workspace, project=project, state=completed_state, created_by=create_user
        )
        for i in range(3)
    ]


@pytest.mark.contract
class TestBulkArchiveIssues:
    def get_url(self, workspace_slug, project_id):
        return f"/api/workspaces/{workspace_slug}/projects/{project_id}/bulk-archive-issues/"

    @pytest.mark.django_db
    def test_emits_one_event_per_issue_not_per_request(self, session_client, workspace, project, issues):
        url = self.get_url(workspace.slug, project.id)
        issue_ids = [str(issue.id) for issue in issues]

        response = session_client.post(url, {"issue_ids": issue_ids}, format="json")

        assert response.status_code == status.HTTP_200_OK, f"Got {response.status_code}: {response.data!r}"
        events = EventLog.objects.filter(entity_type="issue", event_type="issue.archived")
        assert events.count() == len(issues)
        assert {str(e.entity_id) for e in events} == set(issue_ids)
        for issue in issues:
            issue.refresh_from_db()
            assert issue.archived_at is not None
