# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import pytest
from rest_framework import status

from plane.db.models import (
    Issue,
    IssueAssignee,
    Project,
    ProjectMember,
    State,
    User,
    WorkspaceMember,
)


class TestTeamCalendarBase:
    def get_url(self, workspace_slug: str) -> str:
        return f"/api/workspaces/{workspace_slug}/team-calendar/"

    def create_project(self, workspace, user, identifier="TSTC"):
        project = Project.objects.create(
            name=f"Project {identifier}",
            identifier=identifier,
            workspace=workspace,
            created_by=user,
        )
        ProjectMember.objects.create(project=project, workspace=workspace, member=user, role=20, is_active=True)
        return project

    def get_or_create_state(self, project, group="unstarted"):
        state = State.all_state_objects.filter(project=project, group=group).first()
        if state:
            return state
        return State.objects.create(
            name=f"State {group}",
            color="#60646C",
            group=group,
            project=project,
            workspace=project.workspace,
            sequence=10000,
            created_by=project.created_by,
        )

    def create_assigned_issue(self, project, user, name, start_date=None, target_date=None, state_group="unstarted"):
        state = self.get_or_create_state(project, group=state_group)
        issue = Issue.objects.create(
            project=project,
            workspace=project.workspace,
            name=name,
            start_date=start_date,
            target_date=target_date,
            state=state,
        )
        IssueAssignee.objects.create(
            issue=issue, assignee=user, project=project, workspace=project.workspace
        )
        return issue


@pytest.mark.contract
class TestTeamCalendarAPI(TestTeamCalendarBase):
    @pytest.mark.django_db
    def test_requires_date_params(self, session_client, workspace):
        response = session_client.get(self.get_url(workspace.slug))
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.django_db
    def test_forbidden_for_member_role(self, session_client, create_user, workspace):
        WorkspaceMember.objects.filter(workspace=workspace, member=create_user).update(role=15)
        response = session_client.get(
            self.get_url(workspace.slug),
            {"start_date": "2026-07-13", "end_date": "2026-07-19"},
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.django_db
    def test_forbidden_for_guest_role(self, session_client, create_user, workspace):
        WorkspaceMember.objects.filter(workspace=workspace, member=create_user).update(role=5)
        response = session_client.get(
            self.get_url(workspace.slug),
            {"start_date": "2026-07-13", "end_date": "2026-07-19"},
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.django_db
    def test_window_overlap_logic(self, session_client, create_user, workspace):
        project = self.create_project(workspace, create_user)

        inside = self.create_assigned_issue(
            project, create_user, "inside", start_date="2026-07-14", target_date="2026-07-16"
        )
        spanning = self.create_assigned_issue(
            project, create_user, "spanning", start_date="2026-07-01", target_date="2026-07-31"
        )
        due_only = self.create_assigned_issue(project, create_user, "due only", target_date="2026-07-15")
        outside = self.create_assigned_issue(
            project, create_user, "outside", start_date="2026-08-01", target_date="2026-08-05"
        )
        no_dates = self.create_assigned_issue(project, create_user, "no dates")

        response = session_client.get(
            self.get_url(workspace.slug),
            {"start_date": "2026-07-13", "end_date": "2026-07-19"},
        )
        assert response.status_code == status.HTTP_200_OK

        members = {member["id"]: member for member in response.data["members"]}
        assert str(create_user.id) in members
        issue_ids = {str(issue["id"]) for issue in members[str(create_user.id)]["issues"]}
        assert str(inside.id) in issue_ids
        assert str(spanning.id) in issue_ids
        assert str(due_only.id) in issue_ids
        assert str(outside.id) not in issue_ids
        # no_dates has no start_date/target_date, but its created_at falls within the
        # window (created during this test), so the created_at fallback makes it appear.
        assert str(no_dates.id) in issue_ids

    @pytest.mark.django_db
    def test_project_filter_scopes_members_and_issues(self, session_client, create_user, workspace):
        project_a = self.create_project(workspace, create_user, identifier="PRJA")
        project_b = self.create_project(workspace, create_user, identifier="PRJB")

        other_user = User.objects.create(email="other@plane.so", display_name="Other User", username="other-user")
        WorkspaceMember.objects.create(workspace=workspace, member=other_user, role=15, is_active=True)
        ProjectMember.objects.create(
            project=project_b, workspace=workspace, member=other_user, role=15, is_active=True
        )

        issue_a = self.create_assigned_issue(
            project_a, create_user, "in project a", start_date="2026-07-14", target_date="2026-07-16"
        )
        issue_b = self.create_assigned_issue(
            project_b, other_user, "in project b", start_date="2026-07-14", target_date="2026-07-16"
        )

        response = session_client.get(
            self.get_url(workspace.slug),
            {
                "start_date": "2026-07-13",
                "end_date": "2026-07-19",
                "project": str(project_a.id),
            },
        )
        assert response.status_code == status.HTTP_200_OK

        member_ids = {member["id"] for member in response.data["members"]}
        assert str(create_user.id) in member_ids
        # other_user is only a member of project B, so the project A filter excludes them
        assert str(other_user.id) not in member_ids

        all_issue_ids = {
            str(issue["id"]) for member in response.data["members"] for issue in member["issues"]
        }
        assert str(issue_a.id) in all_issue_ids
        assert str(issue_b.id) not in all_issue_ids

    @pytest.mark.django_db
    def test_only_shows_unstarted_and_started_issues(self, session_client, create_user, workspace):
        project = self.create_project(workspace, create_user)

        unstarted_issue = self.create_assigned_issue(
            project, create_user, "unstarted item",
            start_date="2026-07-14", target_date="2026-07-16",
            state_group="unstarted",
        )
        started_issue = self.create_assigned_issue(
            project, create_user, "started item",
            start_date="2026-07-14", target_date="2026-07-16",
            state_group="started",
        )
        backlog_issue = self.create_assigned_issue(
            project, create_user, "backlog item",
            start_date="2026-07-14", target_date="2026-07-16",
            state_group="backlog",
        )
        completed_issue = self.create_assigned_issue(
            project, create_user, "done item",
            start_date="2026-07-14", target_date="2026-07-16",
            state_group="completed",
        )
        cancelled_issue = self.create_assigned_issue(
            project, create_user, "cancelled item",
            start_date="2026-07-14", target_date="2026-07-16",
            state_group="cancelled",
        )

        response = session_client.get(
            self.get_url(workspace.slug),
            {"start_date": "2026-07-13", "end_date": "2026-07-19"},
        )
        assert response.status_code == status.HTTP_200_OK

        members = {member["id"]: member for member in response.data["members"]}
        issue_ids = {str(issue["id"]) for issue in members[str(create_user.id)]["issues"]}
        assert str(unstarted_issue.id) in issue_ids
        assert str(started_issue.id) in issue_ids
        assert str(backlog_issue.id) not in issue_ids
        assert str(completed_issue.id) not in issue_ids
        assert str(cancelled_issue.id) not in issue_ids
