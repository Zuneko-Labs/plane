# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Handover approval gate: every work item passes through Pending Approval,
and only a project Admin (approver) can move one past it, only from it - on
every entry point (app/external API create, update, upsert). Sent Back by
an approver requires a comment. Enforced server-side, before anything is
written.
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
    Module,
    Project,
    ProjectMember,
    State,
    User,
    WorkspaceMember,
)


def make_state(**kwargs):
    # State.save() overwrites `sequence` on insert (last + 15000) - pin it so
    # the workflow order these tests rely on is explicit
    sequence = kwargs.pop("sequence", None)
    state = State.objects.create(**kwargs)
    if sequence is not None:
        State.objects.filter(pk=state.pk).update(sequence=sequence)
        state.sequence = sequence
    return state


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
    return make_state(
        name="Handover", workspace=workspace, project=project, group="started", default=True, sequence=20000
    )


@pytest.fixture
def pending_approval_state(db, workspace, project):
    return make_state(
        name="Pending Approval", workspace=workspace, project=project, group="started", sequence=40000
    )


@pytest.fixture
def approved_state(db, workspace, project):
    return make_state(
        name="Approved", workspace=workspace, project=project, group="completed", sequence=50000
    )


@pytest.fixture
def sent_back_state(db, workspace, project):
    return make_state(
        name="Sent Back", workspace=workspace, project=project, group="started", sequence=30000
    )


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


@pytest.fixture
def module(db, workspace, project, create_user):
    return Module.objects.create(name="Handover Module", project=project, workspace=workspace, created_by=create_user)


@pytest.fixture
def draft_verified_state(db, workspace, project):
    # a stage between Pending Approval and Approved - also past the gate
    return make_state(
        name="Draft verified", workspace=workspace, project=project, group="started", sequence=45000
    )


@pytest.fixture
def after_approved_state(db, workspace, project):
    return make_state(
        name="Archived Copy", workspace=workspace, project=project, group="completed", sequence=60000
    )


def issues_url(workspace_slug, project_id):
    return f"/api/workspaces/{workspace_slug}/projects/{project_id}/issues/"


def v1_issue_url(workspace_slug, project_id, pk=None):
    base = f"/api/v1/workspaces/{workspace_slug}/projects/{project_id}/issues/"
    return f"{base}{pk}/" if pk else base


def client_for(user):
    # a fresh client per user: api_client / session_client share one object
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.mark.contract
class TestApprovalGateOnStateTransition:
    @pytest.mark.django_db
    def test_member_cannot_skip_pending_approval(
        self, workspace, project, handover_issue, approved_state, gate_config, non_approver
    ):
        """No silent redirect: skipping Pending Approval is refused and
        nothing changes."""
        url = issue_url(workspace.slug, project.id, handover_issue.id)
        response = client_for(non_approver).patch(url, {"state_id": str(approved_state.id)}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, f"Got {response.status_code}: {response.data!r}"
        handover_issue.refresh_from_db()
        assert handover_issue.state_id != approved_state.id
        assert not ApprovalRecord.objects.filter(issue=handover_issue).exists()

    @pytest.mark.django_db
    def test_admin_cannot_skip_pending_approval_either(
        self, workspace, project, handover_issue, approved_state, gate_config, create_user
    ):
        url = issue_url(workspace.slug, project.id, handover_issue.id)
        response = client_for(create_user).patch(url, {"state_id": str(approved_state.id)}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, f"Got {response.status_code}: {response.data!r}"
        handover_issue.refresh_from_db()
        assert handover_issue.state_id != approved_state.id

    @pytest.mark.django_db
    def test_any_state_after_pending_approval_is_gated_not_just_approved(
        self,
        workspace,
        project,
        handover_issue,
        pending_approval_state,
        draft_verified_state,
        gate_config,
        non_approver,
        create_user,
    ):
        url = issue_url(workspace.slug, project.id, handover_issue.id)

        # skipping straight to it - refused for everyone
        for user in (non_approver, create_user):
            response = client_for(user).patch(url, {"state_id": str(draft_verified_state.id)}, format="json")
            assert response.status_code == status.HTTP_400_BAD_REQUEST, f"Got {response.status_code}: {response.data!r}"

        # from Pending Approval - member refused
        Issue.objects.filter(pk=handover_issue.id).update(state=pending_approval_state)
        response = client_for(non_approver).patch(url, {"state_id": str(draft_verified_state.id)}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST, f"Got {response.status_code}: {response.data!r}"
        handover_issue.refresh_from_db()
        assert handover_issue.state_id == pending_approval_state.id

    @pytest.mark.django_db
    def test_member_cannot_approve_from_pending_approval(
        self, workspace, project, handover_issue, pending_approval_state, approved_state, gate_config, non_approver
    ):
        Issue.objects.filter(pk=handover_issue.id).update(state=pending_approval_state)
        url = issue_url(workspace.slug, project.id, handover_issue.id)

        response = client_for(non_approver).patch(url, {"state_id": str(approved_state.id)}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, f"Got {response.status_code}: {response.data!r}"
        handover_issue.refresh_from_db()
        assert handover_issue.state_id == pending_approval_state.id

    @pytest.mark.django_db
    def test_approver_approves_from_pending_approval_and_register_is_written(
        self, workspace, project, handover_issue, pending_approval_state, approved_state, gate_config, create_user
    ):
        Issue.objects.filter(pk=handover_issue.id).update(state=pending_approval_state)
        url = issue_url(workspace.slug, project.id, handover_issue.id)

        with patch("plane.app.views.issue.base.issue_activity"):
            response = client_for(create_user).patch(url, {"state_id": str(approved_state.id)}, format="json")

        assert response.status_code == status.HTTP_204_NO_CONTENT, f"Got {response.status_code}: {response.data!r}"
        handover_issue.refresh_from_db()
        assert handover_issue.state_id == approved_state.id
        record = ApprovalRecord.objects.get(issue=handover_issue)
        assert record.decision == ApprovalRecord.Decision.APPROVED

    @pytest.mark.django_db
    def test_moves_between_states_already_past_the_gate_are_free(
        self, workspace, project, handover_issue, approved_state, after_approved_state, gate_config, non_approver
    ):
        Issue.objects.filter(pk=handover_issue.id).update(state=approved_state)
        url = issue_url(workspace.slug, project.id, handover_issue.id)

        with patch("plane.app.views.issue.base.issue_activity"):
            response = client_for(non_approver).patch(url, {"state_id": str(after_approved_state.id)}, format="json")

        assert response.status_code == status.HTTP_204_NO_CONTENT, f"Got {response.status_code}: {response.data!r}"

    @pytest.mark.django_db
    def test_state_alias_key_cannot_bypass_the_gate(
        self, workspace, project, handover_issue, approved_state, gate_config, non_approver
    ):
        """The serializer also writes the model's own `state` field - sending
        that instead of `state_id` must hit the same gate."""
        url = issue_url(workspace.slug, project.id, handover_issue.id)
        response = client_for(non_approver).patch(url, {"state": str(approved_state.id)}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, f"Got {response.status_code}: {response.data!r}"
        handover_issue.refresh_from_db()
        assert handover_issue.state_id != approved_state.id

    @pytest.mark.django_db
    def test_moving_into_the_sent_back_state_as_normal_work_is_not_gated(
        self, workspace, project, handover_issue, sent_back_state, non_approver, gate_config
    ):
        """The Sent Back state doubles as an ordinary workflow stage before
        Pending Approval - moving into it is normal work."""
        url = issue_url(workspace.slug, project.id, handover_issue.id)

        with patch("plane.app.views.issue.base.issue_activity"):
            response = client_for(non_approver).patch(url, {"state_id": str(sent_back_state.id)}, format="json")

        assert response.status_code == status.HTTP_204_NO_CONTENT, f"Got {response.status_code}: {response.data!r}"
        assert not ApprovalRecord.objects.filter(issue=handover_issue).exists()
        assert not IssueComment.objects.filter(issue=handover_issue).exists()

    @pytest.mark.django_db
    def test_member_pulling_an_item_back_out_of_pending_approval_is_allowed(
        self,
        workspace,
        project,
        handover_issue,
        handover_state,
        sent_back_state,
        pending_approval_state,
        gate_config,
        non_approver,
    ):
        url = issue_url(workspace.slug, project.id, handover_issue.id)

        for target in (sent_back_state, handover_state):
            Issue.objects.filter(pk=handover_issue.id).update(state=pending_approval_state)
            with patch("plane.app.views.issue.base.issue_activity"):
                response = client_for(non_approver).patch(url, {"state_id": str(target.id)}, format="json")
            assert response.status_code == status.HTTP_204_NO_CONTENT, f"Got {response.status_code}: {response.data!r}"
            handover_issue.refresh_from_db()
            assert handover_issue.state_id == target.id
        assert not ApprovalRecord.objects.filter(issue=handover_issue).exists()

    @pytest.mark.django_db
    def test_approver_sent_back_without_comment_is_refused(
        self, workspace, project, handover_issue, sent_back_state, pending_approval_state, gate_config, create_user
    ):
        Issue.objects.filter(pk=handover_issue.id).update(state=pending_approval_state)
        url = issue_url(workspace.slug, project.id, handover_issue.id)

        response = client_for(create_user).patch(url, {"state_id": str(sent_back_state.id)}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, f"Got {response.status_code}: {response.data!r}"
        handover_issue.refresh_from_db()
        assert handover_issue.state_id == pending_approval_state.id

    @pytest.mark.django_db
    def test_approver_sent_back_with_comment_writes_comment_and_register(
        self, workspace, project, handover_issue, sent_back_state, pending_approval_state, gate_config, create_user
    ):
        Issue.objects.filter(pk=handover_issue.id).update(state=pending_approval_state)
        url = issue_url(workspace.slug, project.id, handover_issue.id)

        with patch("plane.app.views.issue.base.issue_activity"):
            response = client_for(create_user).patch(
                url,
                {"state_id": str(sent_back_state.id), "approval_comment_html": "<p>please fix the totals</p>"},
                format="json",
            )

        assert response.status_code == status.HTTP_204_NO_CONTENT, f"Got {response.status_code}: {response.data!r}"
        assert IssueComment.objects.filter(issue=handover_issue, comment_html="<p>please fix the totals</p>").exists()
        record = ApprovalRecord.objects.get(issue=handover_issue)
        assert record.decision == ApprovalRecord.Decision.SENT_BACK

    @pytest.mark.django_db
    def test_unrelated_field_update_is_not_gated(self, workspace, project, handover_issue, gate_config, non_approver):
        url = issue_url(workspace.slug, project.id, handover_issue.id)
        with patch("plane.app.views.issue.base.issue_activity"):
            response = client_for(non_approver).patch(url, {"priority": "high"}, format="json")
        assert response.status_code == status.HTTP_204_NO_CONTENT, f"Got {response.status_code}: {response.data!r}"

    @pytest.mark.django_db
    def test_anyone_can_enter_pending_approval_and_approvers_are_notified_on_commit(
        self,
        workspace,
        project,
        handover_issue,
        pending_approval_state,
        gate_config,
        non_approver,
        django_capture_on_commit_callbacks,
    ):
        url = issue_url(workspace.slug, project.id, handover_issue.id)

        with (
            patch("plane.app.views.issue.base.issue_activity"),
            patch("plane.utils.state_transition.notify_pending_approval") as mock_notify,
            django_capture_on_commit_callbacks(execute=True),
        ):
            response = client_for(non_approver).patch(url, {"state_id": str(pending_approval_state.id)}, format="json")

        assert response.status_code == status.HTTP_204_NO_CONTENT, f"Got {response.status_code}: {response.data!r}"
        handover_issue.refresh_from_db()
        assert handover_issue.state_id == pending_approval_state.id
        mock_notify.delay.assert_called_once()

    @pytest.mark.django_db
    def test_states_not_named_for_the_gate_are_unrestricted_with_no_config(
        self, workspace, project, handover_issue, non_approver
    ):
        unrelated_state = make_state(name="Filed", workspace=workspace, project=project, group="completed")
        url = issue_url(workspace.slug, project.id, handover_issue.id)
        with patch("plane.app.views.issue.base.issue_activity"):
            response = client_for(non_approver).patch(url, {"state_id": str(unrelated_state.id)}, format="json")
        assert response.status_code == status.HTTP_204_NO_CONTENT, f"Got {response.status_code}: {response.data!r}"

    @pytest.mark.django_db
    def test_gate_applies_by_state_name_with_no_explicit_config(
        self, workspace, project, handover_issue, sent_back_state, pending_approval_state, create_user
    ):
        Issue.objects.filter(pk=handover_issue.id).update(state=pending_approval_state)
        url = issue_url(workspace.slug, project.id, handover_issue.id)

        response = client_for(create_user).patch(url, {"state_id": str(sent_back_state.id)}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, f"Got {response.status_code}: {response.data!r}"
        assert "comment" in response.data.get("error", "")

    @pytest.mark.django_db
    def test_gate_applies_by_real_workflow_aliases(self, workspace, project, handover_issue, non_approver, create_user):
        """Department workflows name the roles "Sent for Approval" /
        "Handedover" and have no rejection step."""
        sent_for_approval = make_state(
            name="Sent for Approval", workspace=workspace, project=project, group="started", sequence=40000
        )
        handedover = make_state(
            name="Handedover", workspace=workspace, project=project, group="completed", sequence=50000
        )
        url = issue_url(workspace.slug, project.id, handover_issue.id)

        response = client_for(non_approver).patch(url, {"state_id": str(handedover.id)}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST, f"Got {response.status_code}: {response.data!r}"

        with patch("plane.app.views.issue.base.issue_activity"):
            response = client_for(non_approver).patch(url, {"state_id": str(sent_for_approval.id)}, format="json")
        assert response.status_code == status.HTTP_204_NO_CONTENT, f"Got {response.status_code}: {response.data!r}"

        with patch("plane.app.views.issue.base.issue_activity"):
            response = client_for(create_user).patch(url, {"state_id": str(handedover.id)}, format="json")
        assert response.status_code == status.HTTP_204_NO_CONTENT, f"Got {response.status_code}: {response.data!r}"


@pytest.mark.contract
class TestApprovalGateOnCreate:
    @pytest.mark.django_db
    def test_creating_past_pending_approval_is_refused_for_everyone(
        self,
        workspace,
        project,
        handover_state,
        approved_state,
        draft_verified_state,
        module,
        gate_config,
        non_approver,
        create_user,
    ):
        url = issues_url(workspace.slug, project.id)
        for user in (non_approver, create_user):
            for target in (approved_state, draft_verified_state):
                response = client_for(user).post(
                    url,
                    {"name": "Skipper", "state_id": str(target.id), "module_ids": [str(module.id)]},
                    format="json",
                )
                assert response.status_code == status.HTTP_400_BAD_REQUEST, (
                    f"Got {response.status_code}: {response.data!r}"
                )
        assert not Issue.objects.filter(name="Skipper").exists()

    @pytest.mark.django_db
    def test_creating_into_pending_approval_is_allowed(
        self, workspace, project, handover_state, pending_approval_state, module, gate_config, non_approver
    ):
        url = issues_url(workspace.slug, project.id)
        with patch("plane.app.views.issue.base.issue_activity"):
            response = client_for(non_approver).post(
                url,
                {"name": "Request", "state_id": str(pending_approval_state.id), "module_ids": [str(module.id)]},
                format="json",
            )
        assert response.status_code == status.HTTP_201_CREATED, f"Got {response.status_code}: {response.data!r}"


@pytest.mark.contract
class TestApprovalGateOnExternalApi:
    @pytest.mark.django_db
    def test_v1_patch_cannot_skip_pending_approval(
        self, api_key_client, workspace, project, handover_issue, approved_state, gate_config
    ):
        response = api_key_client.patch(
            v1_issue_url(workspace.slug, project.id, handover_issue.id), {"state": str(approved_state.id)}, format="json"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, f"Got {response.status_code}: {response.data!r}"
        handover_issue.refresh_from_db()
        assert handover_issue.state_id != approved_state.id

    @pytest.mark.django_db
    def test_v1_create_past_pending_approval_is_refused(
        self, api_key_client, workspace, project, handover_state, approved_state, module, gate_config
    ):
        response = api_key_client.post(
            v1_issue_url(workspace.slug, project.id),
            {"name": "Skipper", "state": str(approved_state.id), "module_ids": [str(module.id)]},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, f"Got {response.status_code}: {response.data!r}"



@pytest.mark.contract
class TestApprovalGateToggle:
    @pytest.mark.django_db
    def test_disabled_gate_lets_a_member_move_straight_to_approved(
        self, workspace, project, handover_issue, approved_state, gate_config, non_approver
    ):
        gate_config.is_enabled = False
        gate_config.save()

        url = issue_url(workspace.slug, project.id, handover_issue.id)
        with patch("plane.app.views.issue.base.issue_activity"):
            response = client_for(non_approver).patch(url, {"state_id": str(approved_state.id)}, format="json")

        assert response.status_code == status.HTTP_204_NO_CONTENT, f"Got {response.status_code}: {response.data!r}"
        assert not ApprovalRecord.objects.filter(issue=handover_issue).exists()

    @pytest.mark.django_db
    def test_disabled_gate_lets_an_admin_send_back_with_no_comment(
        self, workspace, project, handover_issue, sent_back_state, pending_approval_state, gate_config, create_user
    ):
        gate_config.is_enabled = False
        gate_config.save()
        Issue.objects.filter(pk=handover_issue.id).update(state=pending_approval_state)

        url = issue_url(workspace.slug, project.id, handover_issue.id)
        with patch("plane.app.views.issue.base.issue_activity"):
            response = client_for(create_user).patch(url, {"state_id": str(sent_back_state.id)}, format="json")

        assert response.status_code == status.HTTP_204_NO_CONTENT, f"Got {response.status_code}: {response.data!r}"
        assert not IssueComment.objects.filter(issue=handover_issue).exists()

    @pytest.mark.django_db
    def test_re_enabling_the_gate_restores_it(
        self, workspace, project, handover_issue, approved_state, gate_config, non_approver
    ):
        gate_config.is_enabled = False
        gate_config.save()
        gate_config.is_enabled = True
        gate_config.save()

        url = issue_url(workspace.slug, project.id, handover_issue.id)
        response = client_for(non_approver).patch(url, {"state_id": str(approved_state.id)}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST, f"Got {response.status_code}: {response.data!r}"


@pytest.mark.contract
class TestWorkflowStateDeletion:
    @pytest.mark.django_db
    def test_a_state_mapped_in_the_gate_cannot_be_deleted(
        self, workspace, project, pending_approval_state, gate_config, create_user
    ):
        response = client_for(create_user).delete(
            f"/api/workspaces/{workspace.slug}/projects/{project.id}/states/{pending_approval_state.id}/"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, f"Got {response.status_code}: {response.data!r}"
        assert ApprovalGateConfig.objects.filter(
            pk=gate_config.pk, pending_approval_state=pending_approval_state
        ).exists()


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
