# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Reopening: once a work item is in Pending Approval or past it (approved),
it doesn't come back to an earlier stage for anyone - approvers included -
until an approver accepts a reopen request filed with a reason. Plus the workspace-wide approvals page
that lists all of it across projects.
"""

from unittest.mock import patch

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from plane.db.models import (
    ApprovalGateConfig,
    ApprovalRecord,
    ApprovalReopenRequest,
    Issue,
    IssueComment,
    Module,
    ModuleIssue,
    Notification,
    Project,
    ProjectMember,
    State,
    User,
    WorkspaceMember,
)
from plane.utils.approval import REOPEN_APPROVAL_REQUIRED

ISSUE_ACTIVITY = "plane.app.views.issue.base.issue_activity"
WORKSPACE_ISSUE_ACTIVITY = "plane.app.views.approval_workspace.issue_activity"


def make_state(**kwargs):
    # State.save() overwrites `sequence` on insert - pin it
    sequence = kwargs.pop("sequence", None)
    state = State.objects.create(**kwargs)
    if sequence is not None:
        State.objects.filter(pk=state.pk).update(sequence=sequence)
        state.sequence = sequence
    return state


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def project(db, workspace, create_user):
    project = Project.objects.create(name="Reopen Project", identifier="ROP", workspace=workspace, created_by=create_user)
    # create_user is the approver (Admin) for this project
    ProjectMember.objects.create(project=project, member=create_user, role=20, is_active=True)
    return project


@pytest.fixture
def handover_state(db, workspace, project):
    return make_state(name="Handover", workspace=workspace, project=project, group="started", default=True, sequence=20000)


@pytest.fixture
def pending_approval_state(db, workspace, project):
    return make_state(name="Pending Approval", workspace=workspace, project=project, group="started", sequence=40000)


@pytest.fixture
def approved_state(db, workspace, project):
    return make_state(name="Approved", workspace=workspace, project=project, group="completed", sequence=50000)


@pytest.fixture
def after_approved_state(db, workspace, project):
    return make_state(name="Archived Copy", workspace=workspace, project=project, group="completed", sequence=60000)


@pytest.fixture
def cancelled_state(db, workspace, project):
    return make_state(name="Cancelled", workspace=workspace, project=project, group="cancelled", sequence=70000)


@pytest.fixture
def gate_config(db, project, pending_approval_state, approved_state):
    return ApprovalGateConfig.objects.create(
        project=project,
        workspace=project.workspace,
        pending_approval_state=pending_approval_state,
        approved_state=approved_state,
    )


@pytest.fixture
def member(db, workspace, project):
    user = User.objects.create(email="reopen-member@plane.so", username="reopen-member@plane.so", first_name="Member")
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=15, is_active=True)
    ProjectMember.objects.create(project=project, member=user, role=15, is_active=True)
    return user


@pytest.fixture
def approved_issue(db, workspace, project, approved_state, create_user):
    return Issue.objects.create(
        name="Signed off", workspace=workspace, project=project, state=approved_state, created_by=create_user
    )


def issue_url(workspace_slug, project_id, pk):
    return f"/api/workspaces/{workspace_slug}/projects/{project_id}/issues/{pk}/"


def reopen_requests_url(workspace_slug, project_id, issue_id):
    return f"/api/workspaces/{workspace_slug}/projects/{project_id}/issues/{issue_id}/reopen-requests/"


def decision_url(workspace_slug, request_id):
    return f"/api/workspaces/{workspace_slug}/approvals/reopen-requests/{request_id}/decision/"


@pytest.mark.contract
class TestMovingAnApprovedWorkItemBack:
    @pytest.mark.django_db
    def test_member_cannot_move_an_approved_item_back(
        self, workspace, project, approved_issue, handover_state, gate_config, member
    ):
        url = issue_url(workspace.slug, project.id, approved_issue.id)
        with patch(ISSUE_ACTIVITY):
            response = client_for(member).patch(url, {"state_id": str(handover_state.id)}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["error_code"] == REOPEN_APPROVAL_REQUIRED
        approved_issue.refresh_from_db()
        assert approved_issue.state_id == gate_config.approved_state_id

    @pytest.mark.django_db
    def test_member_cannot_move_an_approved_item_back_into_pending_approval_or_cancelled(
        self, workspace, project, approved_issue, pending_approval_state, cancelled_state, gate_config, member
    ):
        url = issue_url(workspace.slug, project.id, approved_issue.id)
        for target in (pending_approval_state, cancelled_state):
            with patch(ISSUE_ACTIVITY):
                response = client_for(member).patch(url, {"state_id": str(target.id)}, format="json")
            assert response.status_code == status.HTTP_400_BAD_REQUEST, f"{target.name}: {response.data!r}"
            assert response.data["error_code"] == REOPEN_APPROVAL_REQUIRED

    @pytest.mark.django_db
    def test_approver_cannot_move_it_back_directly_either_even_with_a_reason(
        self, session_client, workspace, project, approved_issue, handover_state, gate_config
    ):
        url = issue_url(workspace.slug, project.id, approved_issue.id)
        with patch(ISSUE_ACTIVITY):
            response = session_client.patch(
                url,
                {"state_id": str(handover_state.id), "approval_comment_html": "<p>Wrong client name</p>"},
                format="json",
            )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["error_code"] == REOPEN_APPROVAL_REQUIRED
        approved_issue.refresh_from_db()
        assert approved_issue.state_id == gate_config.approved_state_id
        assert not ApprovalRecord.objects.filter(issue=approved_issue).exists()

    @pytest.mark.django_db
    def test_moves_between_approved_stages_stay_free(
        self, workspace, project, approved_issue, after_approved_state, gate_config, member
    ):
        url = issue_url(workspace.slug, project.id, approved_issue.id)
        with patch(ISSUE_ACTIVITY):
            response = client_for(member).patch(url, {"state_id": str(after_approved_state.id)}, format="json")
        assert response.status_code == status.HTTP_204_NO_CONTENT, f"Got {response.status_code}: {response.data!r}"

    @pytest.mark.django_db
    def test_disabled_gate_does_not_block_moving_back(
        self, workspace, project, approved_issue, handover_state, gate_config, member
    ):
        ApprovalGateConfig.objects.filter(pk=gate_config.pk).update(is_enabled=False)
        url = issue_url(workspace.slug, project.id, approved_issue.id)
        with patch(ISSUE_ACTIVITY):
            response = client_for(member).patch(url, {"state_id": str(handover_state.id)}, format="json")
        assert response.status_code == status.HTTP_204_NO_CONTENT, f"Got {response.status_code}: {response.data!r}"


@pytest.mark.contract
class TestReopenRequests:
    @pytest.mark.django_db
    def test_member_files_a_request_and_the_item_stays_put(
        self, workspace, project, approved_issue, handover_state, gate_config, member, create_user
    ):
        response = client_for(member).post(
            reopen_requests_url(workspace.slug, project.id, approved_issue.id),
            {"state_id": str(handover_state.id), "reason": "Client changed the deed"},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED, f"Got {response.status_code}: {response.data!r}"
        assert response.data["status"] == "pending"
        assert response.data["to_state_name"] == "Handover"
        approved_issue.refresh_from_db()
        assert approved_issue.state_id == gate_config.approved_state_id
        # the approvers are told
        assert Notification.objects.filter(receiver=create_user, entity_identifier=approved_issue.id).exists()

    @pytest.mark.django_db
    def test_reason_is_required(self, workspace, project, approved_issue, handover_state, gate_config, member):
        response = client_for(member).post(
            reopen_requests_url(workspace.slug, project.id, approved_issue.id),
            {"state_id": str(handover_state.id), "reason": "   "},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.django_db
    def test_only_one_request_waits_at_a_time(
        self, workspace, project, approved_issue, handover_state, gate_config, member
    ):
        url = reopen_requests_url(workspace.slug, project.id, approved_issue.id)
        payload = {"state_id": str(handover_state.id), "reason": "Needs a fix"}
        assert client_for(member).post(url, payload, format="json").status_code == status.HTTP_201_CREATED

        response = client_for(member).post(url, payload, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert ApprovalReopenRequest.objects.filter(issue=approved_issue).count() == 1

    @pytest.mark.django_db
    def test_request_is_refused_for_an_item_that_is_not_locked(
        self, workspace, project, handover_state, gate_config, member, create_user
    ):
        issue = Issue.objects.create(
            name="In progress", workspace=workspace, project=project, state=handover_state, created_by=create_user
        )
        other = make_state(name="Drafting", workspace=workspace, project=project, group="backlog", sequence=10000)
        response = client_for(member).post(
            reopen_requests_url(workspace.slug, project.id, issue.id),
            {"state_id": str(other.id), "reason": "Why not"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.django_db
    def test_item_in_pending_approval_comes_back_only_through_an_accepted_request(
        self, session_client, workspace, project, handover_state, pending_approval_state, gate_config, member, create_user
    ):
        issue = Issue.objects.create(
            name="Waiting", workspace=workspace, project=project, state=pending_approval_state, created_by=create_user
        )
        with patch(ISSUE_ACTIVITY):
            direct = client_for(member).patch(
                issue_url(workspace.slug, project.id, issue.id), {"state_id": str(handover_state.id)}, format="json"
            )
        assert direct.status_code == status.HTTP_400_BAD_REQUEST
        assert direct.data["error_code"] == REOPEN_APPROVAL_REQUIRED

        created = client_for(member).post(
            reopen_requests_url(workspace.slug, project.id, issue.id),
            {"state_id": str(handover_state.id), "reason": "Forgot the annexure"},
            format="json",
        )
        assert created.status_code == status.HTTP_201_CREATED, f"Got {created.status_code}: {created.data!r}"
        issue.refresh_from_db()
        assert issue.state_id == pending_approval_state.id

        with patch(WORKSPACE_ISSUE_ACTIVITY):
            response = session_client.post(
                decision_url(workspace.slug, created.data["id"]), {"decision": "approve"}, format="json"
            )
        assert response.status_code == status.HTTP_200_OK, f"Got {response.status_code}: {response.data!r}"
        issue.refresh_from_db()
        assert issue.state_id == handover_state.id
        assert ApprovalRecord.objects.get(issue=issue).decision == ApprovalRecord.Decision.REOPENED

    @pytest.mark.django_db
    def test_approver_files_a_request_too_and_it_moves_once_accepted(
        self, session_client, workspace, project, approved_issue, handover_state, gate_config
    ):
        created = session_client.post(
            reopen_requests_url(workspace.slug, project.id, approved_issue.id),
            {"state_id": str(handover_state.id), "reason": "Wrong client name"},
            format="json",
        )
        assert created.status_code == status.HTTP_201_CREATED
        with patch(WORKSPACE_ISSUE_ACTIVITY):
            session_client.post(decision_url(workspace.slug, created.data["id"]), {"decision": "approve"}, format="json")
        approved_issue.refresh_from_db()
        assert approved_issue.state_id == handover_state.id
        assert IssueComment.objects.filter(issue=approved_issue, comment_html__icontains="Wrong client name").exists()

    @pytest.mark.django_db
    def test_request_into_another_approved_stage_is_refused(
        self, workspace, project, approved_issue, after_approved_state, gate_config, member
    ):
        response = client_for(member).post(
            reopen_requests_url(workspace.slug, project.id, approved_issue.id),
            {"state_id": str(after_approved_state.id), "reason": "Why not"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.django_db
    def test_approver_accepting_moves_the_item_back_with_the_reason_on_record(
        self, session_client, workspace, project, approved_issue, handover_state, gate_config, member
    ):
        created = client_for(member).post(
            reopen_requests_url(workspace.slug, project.id, approved_issue.id),
            {"state_id": str(handover_state.id), "reason": "Client changed the deed"},
            format="json",
        )

        with patch(WORKSPACE_ISSUE_ACTIVITY):
            response = session_client.post(
                decision_url(workspace.slug, created.data["id"]), {"decision": "approve"}, format="json"
            )

        assert response.status_code == status.HTTP_200_OK, f"Got {response.status_code}: {response.data!r}"
        assert response.data["status"] == "approved"
        approved_issue.refresh_from_db()
        assert approved_issue.state_id == handover_state.id
        record = ApprovalRecord.objects.get(issue=approved_issue)
        assert record.decision == ApprovalRecord.Decision.REOPENED
        assert "Client changed the deed" in record.comment
        # the requester is told
        assert Notification.objects.filter(receiver=member, entity_identifier=approved_issue.id).exists()

    @pytest.mark.django_db
    def test_reason_is_escaped_when_written_as_a_comment(
        self, session_client, workspace, project, approved_issue, handover_state, gate_config, member
    ):
        created = client_for(member).post(
            reopen_requests_url(workspace.slug, project.id, approved_issue.id),
            {"state_id": str(handover_state.id), "reason": "<img src=x onerror=alert(1)>"},
            format="json",
        )
        with patch(WORKSPACE_ISSUE_ACTIVITY):
            session_client.post(decision_url(workspace.slug, created.data["id"]), {"decision": "approve"}, format="json")

        record = ApprovalRecord.objects.get(issue=approved_issue)
        assert "<img" not in record.comment
        assert "&lt;img" in record.comment

    @pytest.mark.django_db
    def test_approver_rejecting_leaves_the_item_approved(
        self, session_client, workspace, project, approved_issue, handover_state, gate_config, member
    ):
        created = client_for(member).post(
            reopen_requests_url(workspace.slug, project.id, approved_issue.id),
            {"state_id": str(handover_state.id), "reason": "Please"},
            format="json",
        )
        response = session_client.post(
            decision_url(workspace.slug, created.data["id"]),
            {"decision": "reject", "comment": "Already registered"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["status"] == "rejected"
        assert response.data["decision_comment"] == "Already registered"
        approved_issue.refresh_from_db()
        assert approved_issue.state_id == gate_config.approved_state_id
        assert not ApprovalRecord.objects.filter(issue=approved_issue).exists()

    @pytest.mark.django_db
    def test_a_non_approver_cannot_decide(
        self, workspace, project, approved_issue, handover_state, gate_config, member
    ):
        created = client_for(member).post(
            reopen_requests_url(workspace.slug, project.id, approved_issue.id),
            {"state_id": str(handover_state.id), "reason": "Please"},
            format="json",
        )
        response = client_for(member).post(
            decision_url(workspace.slug, created.data["id"]), {"decision": "approve"}, format="json"
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        approved_issue.refresh_from_db()
        assert approved_issue.state_id == gate_config.approved_state_id

    @pytest.mark.django_db
    def test_a_decided_request_cannot_be_decided_again(
        self, session_client, workspace, project, approved_issue, handover_state, gate_config, member
    ):
        created = client_for(member).post(
            reopen_requests_url(workspace.slug, project.id, approved_issue.id),
            {"state_id": str(handover_state.id), "reason": "Please"},
            format="json",
        )
        url = decision_url(workspace.slug, created.data["id"])
        assert session_client.post(url, {"decision": "reject"}, format="json").status_code == status.HTTP_200_OK
        assert session_client.post(url, {"decision": "approve"}, format="json").status_code == 400

    @pytest.mark.django_db
    def test_accepting_a_stale_request_is_refused(
        self, session_client, workspace, project, approved_issue, handover_state, gate_config, member
    ):
        created = client_for(member).post(
            reopen_requests_url(workspace.slug, project.id, approved_issue.id),
            {"state_id": str(handover_state.id), "reason": "Please"},
            format="json",
        )
        # moved back some other way meanwhile
        Issue.objects.filter(pk=approved_issue.pk).update(state=handover_state)
        response = session_client.post(
            decision_url(workspace.slug, created.data["id"]), {"decision": "approve"}, format="json"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert ApprovalReopenRequest.objects.get(pk=created.data["id"]).status == "pending"


@pytest.mark.contract
class TestWorkspaceApprovalsPage:
    @pytest.mark.django_db
    def test_pending_queue_spans_projects_and_names_project_and_module(
        self, session_client, workspace, project, pending_approval_state, gate_config, create_user
    ):
        issue = Issue.objects.create(
            name="Waiting", workspace=workspace, project=project, state=pending_approval_state, created_by=create_user
        )
        module = Module.objects.create(name="Pune Deeds", project=project, workspace=workspace, created_by=create_user)
        ModuleIssue.objects.create(module=module, issue=issue, project=project, workspace=workspace)

        other = Project.objects.create(name="Other Project", identifier="OTP", workspace=workspace, created_by=create_user)
        ProjectMember.objects.create(project=other, member=create_user, role=20, is_active=True)
        other_pending = make_state(name="Pending Approval", workspace=workspace, project=other, group="started", sequence=40000)
        other_approved = make_state(name="Approved", workspace=workspace, project=other, group="completed", sequence=50000)
        ApprovalGateConfig.objects.create(
            project=other, workspace=workspace, pending_approval_state=other_pending, approved_state=other_approved
        )
        Issue.objects.create(name="Also waiting", workspace=workspace, project=other, state=other_pending, created_by=create_user)

        response = session_client.get(f"/api/workspaces/{workspace.slug}/approvals/pending/")

        assert response.status_code == status.HTTP_200_OK
        by_name = {row["name"]: row for row in response.data}
        assert set(by_name) == {"Waiting", "Also waiting"}
        assert by_name["Waiting"]["project_name"] == "Reopen Project"
        assert by_name["Waiting"]["modules"] == [{"id": str(module.id), "name": "Pune Deeds"}]
        assert by_name["Waiting"]["approved_state_id"] == str(gate_config.approved_state_id)
        assert by_name["Also waiting"]["project_name"] == "Other Project"

    @pytest.mark.django_db
    def test_members_see_nothing_from_projects_they_do_not_approve_for(
        self, workspace, project, pending_approval_state, gate_config, member, create_user
    ):
        Issue.objects.create(
            name="Waiting", workspace=workspace, project=project, state=pending_approval_state, created_by=create_user
        )
        response = client_for(member).get(f"/api/workspaces/{workspace.slug}/approvals/pending/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data == []

        response = client_for(member).get(f"/api/workspaces/{workspace.slug}/approvals/reopen-requests/")
        assert response.data == []
