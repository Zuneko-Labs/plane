# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Handover approval gate: only a project Admin (approver) may move a work
item into the configured Approved or Sent Back state, and Sent Back always
requires a comment — enforced server-side, before anything is written.
"""

from unittest.mock import patch

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from plane.db.models import (
    ApprovalGateConfig,
    ApprovalRecord,
    Issue,
    IssueComment,
    Project,
    ProjectMember,
    State,
    User,
    WorkspaceMember,
)


@pytest.fixture
def project(db, workspace, create_user):
    project = Project.objects.create(
        name="Handover Project", identifier="HOP", workspace=workspace, created_by=create_user
    )
    # create_user is the approver (Admin) for this project
    ProjectMember.objects.create(project=project, member=create_user, role=20, is_active=True)
    return project


@pytest.fixture
def handover_state(db, workspace, project):
    return State.objects.create(name="Handover", workspace=workspace, project=project, group="started", default=True)


@pytest.fixture
def pending_approval_state(db, workspace, project):
    return State.objects.create(name="Pending Approval", workspace=workspace, project=project, group="started")


@pytest.fixture
def approved_state(db, workspace, project):
    return State.objects.create(name="Approved", workspace=workspace, project=project, group="completed")


@pytest.fixture
def sent_back_state(db, workspace, project):
    return State.objects.create(name="Sent Back", workspace=workspace, project=project, group="started")


@pytest.fixture
def non_approver(db, workspace, project):
    # explicit username: User.objects.create() defaults it to "", which
    # collides with the create_user fixture's own blank-username row under
    # this project's unique constraint.
    user = User.objects.create(
        email="non-approver@plane.so", username="non-approver@plane.so", first_name="Non", last_name="Approver"
    )
    # the app API's allow_permission(creator=True) path checks WorkspaceMember
    # before it ever looks at project role, so this is required too.
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=15, is_active=True)
    ProjectMember.objects.create(project=project, member=user, role=15, is_active=True)
    return user


@pytest.fixture
def gate_config(db, project, pending_approval_state, approved_state, sent_back_state):
    return ApprovalGateConfig.objects.create(
        project=project,
        workspace=project.workspace,
        pending_approval_state=pending_approval_state,
        approved_state=approved_state,
        sent_back_state=sent_back_state,
    )


def approval_gate_config_url(workspace_slug, project_id):
    return f"/api/workspaces/{workspace_slug}/projects/{project_id}/approval-gate-config/"


@pytest.fixture
def handover_issue(db, workspace, project, handover_state, create_user):
    return Issue.objects.create(
        name="A work item", workspace=workspace, project=project, state=handover_state, created_by=create_user
    )


def issue_url(workspace_slug, project_id, pk):
    return f"/api/workspaces/{workspace_slug}/projects/{project_id}/issues/{pk}/"


@pytest.mark.contract
class TestApprovalGateOnStateTransition:
    @pytest.mark.django_db
    def test_non_approver_reaching_approved_is_redirected_to_pending(
        self,
        api_client,
        workspace,
        project,
        handover_issue,
        approved_state,
        pending_approval_state,
        gate_config,
        non_approver,
    ):
        """A member can't decide Approved themselves — the move still
        succeeds, it just lands in Pending Approval and notifies the
        project's approvers instead of being rejected."""
        api_client.force_authenticate(user=non_approver)
        url = issue_url(workspace.slug, project.id, handover_issue.id)

        with (
            patch("plane.app.views.issue.base.issue_activity"),
            patch("plane.app.views.issue.base.notify_pending_approval") as mock_notify,
        ):
            response = api_client.patch(url, {"state_id": str(approved_state.id)}, format="json")

        assert response.status_code == status.HTTP_204_NO_CONTENT, f"Got {response.status_code}: {response.data!r}"
        handover_issue.refresh_from_db()
        assert handover_issue.state_id == pending_approval_state.id
        mock_notify.delay.assert_called_once()
        assert not ApprovalRecord.objects.filter(issue=handover_issue).exists()

    @pytest.mark.django_db
    def test_moving_into_the_sent_back_state_as_normal_work_is_not_gated(
        self, api_client, workspace, project, handover_issue, sent_back_state, non_approver, gate_config
    ):
        """The Sent Back state doubles as an ordinary workflow stage — the
        default mapping puts it on "Xerox and Binding", which sits
        mid-workflow, well before Pending Approval. A member moving a work
        item into it is just doing the next piece of work: no redirect, no
        comment demanded, nothing logged as a rejection."""
        api_client.force_authenticate(user=non_approver)
        url = issue_url(workspace.slug, project.id, handover_issue.id)

        with patch("plane.app.views.issue.base.issue_activity"):
            response = api_client.patch(url, {"state_id": str(sent_back_state.id)}, format="json")

        assert response.status_code == status.HTTP_204_NO_CONTENT, f"Got {response.status_code}: {response.data!r}"
        handover_issue.refresh_from_db()
        assert handover_issue.state_id == sent_back_state.id
        assert not ApprovalRecord.objects.filter(issue=handover_issue).exists()
        assert not IssueComment.objects.filter(issue=handover_issue).exists()

    @pytest.mark.django_db
    def test_approver_moving_into_sent_back_from_elsewhere_needs_no_comment(
        self, session_client, workspace, project, handover_issue, sent_back_state, gate_config
    ):
        """Even for an approver, entering that stage from somewhere other
        than Pending Approval is normal work, not a rejection."""
        url = issue_url(workspace.slug, project.id, handover_issue.id)

        with patch("plane.app.views.issue.base.issue_activity"):
            response = session_client.patch(url, {"state_id": str(sent_back_state.id)}, format="json")

        assert response.status_code == status.HTTP_204_NO_CONTENT, f"Got {response.status_code}: {response.data!r}"
        handover_issue.refresh_from_db()
        assert handover_issue.state_id == sent_back_state.id
        assert not ApprovalRecord.objects.filter(issue=handover_issue).exists()

    @pytest.mark.django_db
    def test_member_pulling_an_item_back_out_of_pending_approval_is_not_a_rejection(
        self, api_client, workspace, project, handover_issue, sent_back_state, pending_approval_state, gate_config, non_approver
    ):
        """Only an approver can reject. A member moving a work item out of
        Pending Approval is just moving it backwards in the workflow — it
        goes through, with no sign-off record written."""
        Issue.objects.filter(pk=handover_issue.id).update(state=pending_approval_state)
        api_client.force_authenticate(user=non_approver)
        url = issue_url(workspace.slug, project.id, handover_issue.id)

        with patch("plane.app.views.issue.base.issue_activity"):
            response = api_client.patch(url, {"state_id": str(sent_back_state.id)}, format="json")

        assert response.status_code == status.HTTP_204_NO_CONTENT, f"Got {response.status_code}: {response.data!r}"
        handover_issue.refresh_from_db()
        assert handover_issue.state_id == sent_back_state.id
        assert not ApprovalRecord.objects.filter(issue=handover_issue).exists()

    @pytest.mark.django_db
    def test_approver_can_reach_approved_and_register_is_written(
        self, session_client, workspace, project, handover_issue, approved_state, gate_config
    ):
        url = issue_url(workspace.slug, project.id, handover_issue.id)

        with patch("plane.app.views.issue.base.issue_activity"):
            response = session_client.patch(url, {"state_id": str(approved_state.id)}, format="json")

        assert response.status_code == status.HTTP_204_NO_CONTENT, f"Got {response.status_code}: {response.data!r}"
        handover_issue.refresh_from_db()
        assert handover_issue.state_id == approved_state.id

        record = ApprovalRecord.objects.get(issue=handover_issue)
        assert record.decision == ApprovalRecord.Decision.APPROVED

    @pytest.mark.django_db
    def test_approver_sent_back_without_comment_is_refused(
        self, session_client, workspace, project, handover_issue, sent_back_state, pending_approval_state, gate_config
    ):
        """A rejection — approver, out of Pending Approval — must say why."""
        Issue.objects.filter(pk=handover_issue.id).update(state=pending_approval_state)
        url = issue_url(workspace.slug, project.id, handover_issue.id)

        response = session_client.patch(url, {"state_id": str(sent_back_state.id)}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, f"Got {response.status_code}: {response.data!r}"
        handover_issue.refresh_from_db()
        assert handover_issue.state_id != sent_back_state.id
        assert not ApprovalRecord.objects.filter(issue=handover_issue).exists()

    @pytest.mark.django_db
    def test_approver_sent_back_with_comment_succeeds_and_writes_comment_and_register(
        self, session_client, workspace, project, handover_issue, sent_back_state, pending_approval_state, gate_config
    ):
        Issue.objects.filter(pk=handover_issue.id).update(state=pending_approval_state)
        url = issue_url(workspace.slug, project.id, handover_issue.id)

        with patch("plane.app.views.issue.base.issue_activity"):
            response = session_client.patch(
                url,
                {"state_id": str(sent_back_state.id), "approval_comment_html": "<p>please fix the totals</p>"},
                format="json",
            )

        assert response.status_code == status.HTTP_204_NO_CONTENT, f"Got {response.status_code}: {response.data!r}"
        handover_issue.refresh_from_db()
        assert handover_issue.state_id == sent_back_state.id

        assert IssueComment.objects.filter(issue=handover_issue, comment_html="<p>please fix the totals</p>").exists()

        record = ApprovalRecord.objects.get(issue=handover_issue)
        assert record.decision == ApprovalRecord.Decision.SENT_BACK
        assert record.comment == "<p>please fix the totals</p>"

    @pytest.mark.django_db
    def test_unrelated_field_update_does_not_require_approver(
        self, api_client, workspace, project, handover_issue, gate_config, non_approver
    ):
        """Only an actual transition INTO Approved/Sent Back is gated —
        Handover and Pending Approval stay open to anyone."""
        api_client.force_authenticate(user=non_approver)
        url = issue_url(workspace.slug, project.id, handover_issue.id)

        with patch("plane.app.views.issue.base.issue_activity"):
            response = api_client.patch(url, {"priority": "high"}, format="json")

        assert response.status_code == status.HTTP_204_NO_CONTENT, f"Got {response.status_code}: {response.data!r}"

    @pytest.mark.django_db
    def test_anyone_can_enter_pending_approval(
        self, api_client, workspace, project, handover_issue, pending_approval_state, gate_config, non_approver
    ):
        api_client.force_authenticate(user=non_approver)
        url = issue_url(workspace.slug, project.id, handover_issue.id)

        with (
            patch("plane.app.views.issue.base.issue_activity"),
            patch("plane.app.views.issue.base.notify_pending_approval") as mock_notify,
        ):
            response = api_client.patch(url, {"state_id": str(pending_approval_state.id)}, format="json")

        assert response.status_code == status.HTTP_204_NO_CONTENT, f"Got {response.status_code}: {response.data!r}"
        handover_issue.refresh_from_db()
        assert handover_issue.state_id == pending_approval_state.id
        mock_notify.delay.assert_called_once()

    @pytest.mark.django_db
    def test_states_not_named_for_the_gate_are_unrestricted_with_no_config(
        self, api_client, workspace, project, handover_issue, non_approver
    ):
        """No ApprovalGateConfig row AND no state named for one of the gate
        roles means the gate simply doesn't apply — it's a default, not a
        blanket constraint."""
        unrelated_completed_state = State.objects.create(
            name="Closed", workspace=workspace, project=project, group="completed"
        )
        api_client.force_authenticate(user=non_approver)
        url = issue_url(workspace.slug, project.id, handover_issue.id)

        with patch("plane.app.views.issue.base.issue_activity"):
            response = api_client.patch(url, {"state_id": str(unrelated_completed_state.id)}, format="json")

        assert response.status_code == status.HTTP_204_NO_CONTENT, f"Got {response.status_code}: {response.data!r}"

    @pytest.mark.django_db
    def test_gate_applies_by_state_name_with_no_explicit_config(
        self, session_client, workspace, project, handover_issue, sent_back_state, pending_approval_state
    ):
        """Zero setup required: a project with states literally named
        "Pending Approval" and "Sent Back" is gated automatically, with no
        ApprovalGateConfig row at all — that's what makes this on by
        default."""
        Issue.objects.filter(pk=handover_issue.id).update(state=pending_approval_state)
        url = issue_url(workspace.slug, project.id, handover_issue.id)

        response = session_client.patch(url, {"state_id": str(sent_back_state.id)}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, f"Got {response.status_code}: {response.data!r}"
        assert "comment" in response.data.get("error", "")

    @pytest.mark.django_db
    def test_gate_applies_by_real_workflow_aliases_with_no_sent_back_state(
        self, api_client, workspace, project, handover_issue, non_approver, create_user
    ):
        """The client's actual department workflows use "Sent for Approval"
        and "Handedover" (see apply_department_workflows.py), not the
        ticket's literal names, and have no rejection step at all. The gate
        must still apply by default on real projects like these — Approved
        gating active, Sent Back simply absent (not an error).

        Uses two separate APIClient instances rather than the api_client /
        session_client fixtures together — those two share one underlying
        client object (session_client just force_authenticates api_client),
        so switching users on one silently switches the other too.
        """
        sent_for_approval = State.objects.create(
            name="Sent for Approval", workspace=workspace, project=project, group="started"
        )
        handedover = State.objects.create(name="Handedover", workspace=workspace, project=project, group="completed")

        url = issue_url(workspace.slug, project.id, handover_issue.id)

        non_approver_client = APIClient()
        non_approver_client.force_authenticate(user=non_approver)

        # non-approver still can't decide "Handedover" themselves — redirected
        # into "Sent for Approval" (aliases Pending Approval) instead
        with (
            patch("plane.app.views.issue.base.issue_activity"),
            patch("plane.app.views.issue.base.notify_pending_approval") as mock_notify,
        ):
            response = non_approver_client.patch(url, {"state_id": str(handedover.id)}, format="json")
        assert response.status_code == status.HTTP_204_NO_CONTENT, f"Got {response.status_code}: {response.data!r}"
        handover_issue.refresh_from_db()
        assert handover_issue.state_id == sent_for_approval.id
        mock_notify.delay.assert_called_once()

        # reset directly (not through the API) so the next check is a real
        # transition into "Sent for Approval", not a no-op on a state it's
        # already in from the redirect above
        Issue.objects.filter(pk=handover_issue.id).update(state=handedover)
        handover_issue.refresh_from_db()

        # non-approver can freely enter "Sent for Approval" (aliases Pending Approval)
        with (
            patch("plane.app.views.issue.base.issue_activity"),
            patch("plane.app.views.issue.base.notify_pending_approval") as mock_notify,
        ):
            response = non_approver_client.patch(url, {"state_id": str(sent_for_approval.id)}, format="json")
        assert response.status_code == status.HTTP_204_NO_CONTENT, f"Got {response.status_code}: {response.data!r}"
        mock_notify.delay.assert_called_once()

        # approver (create_user, role=Admin per the project fixture) reaches
        # "Handedover" with no comment required — this workflow has no Sent
        # Back state, so nothing demands one
        approver_client = APIClient()
        approver_client.force_authenticate(user=create_user)
        with patch("plane.app.views.issue.base.issue_activity"):
            response = approver_client.patch(url, {"state_id": str(handedover.id)}, format="json")
        assert response.status_code == status.HTTP_204_NO_CONTENT, f"Got {response.status_code}: {response.data!r}"


@pytest.mark.contract
class TestApprovalGateToggle:
    @pytest.mark.django_db
    def test_disabled_gate_lets_a_member_move_straight_to_approved(
        self, api_client, workspace, project, handover_issue, approved_state, gate_config, non_approver
    ):
        gate_config.is_enabled = False
        gate_config.save()

        api_client.force_authenticate(user=non_approver)
        url = issue_url(workspace.slug, project.id, handover_issue.id)

        with patch("plane.app.views.issue.base.issue_activity"):
            response = api_client.patch(url, {"state_id": str(approved_state.id)}, format="json")

        assert response.status_code == status.HTTP_204_NO_CONTENT, f"Got {response.status_code}: {response.data!r}"
        handover_issue.refresh_from_db()
        assert handover_issue.state_id == approved_state.id
        assert not ApprovalRecord.objects.filter(issue=handover_issue).exists()

    @pytest.mark.django_db
    def test_disabled_gate_lets_an_admin_send_back_with_no_comment(
        self, session_client, workspace, project, handover_issue, sent_back_state, pending_approval_state, gate_config
    ):
        gate_config.is_enabled = False
        gate_config.save()

        Issue.objects.filter(pk=handover_issue.id).update(state=pending_approval_state)
        url = issue_url(workspace.slug, project.id, handover_issue.id)

        with patch("plane.app.views.issue.base.issue_activity"):
            response = session_client.patch(url, {"state_id": str(sent_back_state.id)}, format="json")

        assert response.status_code == status.HTTP_204_NO_CONTENT, f"Got {response.status_code}: {response.data!r}"
        handover_issue.refresh_from_db()
        assert handover_issue.state_id == sent_back_state.id
        assert not IssueComment.objects.filter(issue=handover_issue).exists()
        assert not ApprovalRecord.objects.filter(issue=handover_issue).exists()

    @pytest.mark.django_db
    def test_re_enabling_the_gate_restores_the_redirect(
        self, api_client, workspace, project, handover_issue, approved_state, pending_approval_state, gate_config, non_approver
    ):
        gate_config.is_enabled = False
        gate_config.save()
        gate_config.is_enabled = True
        gate_config.save()

        api_client.force_authenticate(user=non_approver)
        url = issue_url(workspace.slug, project.id, handover_issue.id)

        with (
            patch("plane.app.views.issue.base.issue_activity"),
            patch("plane.app.views.issue.base.notify_pending_approval") as mock_notify,
        ):
            response = api_client.patch(url, {"state_id": str(approved_state.id)}, format="json")

        assert response.status_code == status.HTTP_204_NO_CONTENT, f"Got {response.status_code}: {response.data!r}"
        handover_issue.refresh_from_db()
        assert handover_issue.state_id == pending_approval_state.id
        mock_notify.delay.assert_called_once()


@pytest.mark.contract
class TestApprovalGateConfigEndpoint:
    @pytest.mark.django_db
    def test_posting_twice_updates_one_row_instead_of_creating_a_second(
        self, session_client, workspace, project, pending_approval_state, approved_state, sent_back_state
    ):
        url = approval_gate_config_url(workspace.slug, project.id)
        payload = {
            "pending_approval_state_id": str(pending_approval_state.id),
            "approved_state_id": str(approved_state.id),
            "sent_back_state_id": str(sent_back_state.id),
        }

        first = session_client.post(url, payload, format="json")
        assert first.status_code == status.HTTP_201_CREATED, f"Got {first.status_code}: {first.data!r}"

        second = session_client.post(url, {**payload, "is_enabled": False}, format="json")
        assert second.status_code == status.HTTP_200_OK, f"Got {second.status_code}: {second.data!r}"

        assert ApprovalGateConfig.objects.filter(project=project, deleted_at__isnull=True).count() == 1
        config = ApprovalGateConfig.objects.get(project=project, deleted_at__isnull=True)
        assert config.is_enabled is False

    @pytest.mark.django_db
    def test_enabling_with_no_approved_or_sent_back_state_is_rejected(
        self, session_client, workspace, project, pending_approval_state
    ):
        url = approval_gate_config_url(workspace.slug, project.id)
        response = session_client.post(
            url, {"is_enabled": True, "pending_approval_state_id": str(pending_approval_state.id)}, format="json"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, f"Got {response.status_code}: {response.data!r}"


@pytest.mark.contract
class TestApprovalGateDefaultsOnProjectCreation:
    @pytest.mark.django_db
    def test_new_project_gets_an_enabled_gate_over_the_default_states(self, session_client, workspace):
        response = session_client.post(
            f"/api/workspaces/{workspace.slug}/projects/",
            {"name": "New Handover Project", "identifier": "NHP"},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, f"Got {response.status_code}: {response.data!r}"

        config = ApprovalGateConfig.objects.get(project_id=response.data["id"])
        assert config.is_enabled is True
        assert config.pending_approval_state.name == "Closed"
        assert config.approved_state.name == "Excel entry and Handover"
        assert config.sent_back_state.name == "Xerox and Binding"
