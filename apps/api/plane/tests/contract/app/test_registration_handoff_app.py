# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Registration hand-off: moving a work item into the project's configured
registration state (or creating it there) must name an eligible registrar,
or the request is rejected with 400 — before anything is written or
emailed. On success the registrar is added as an assignee alongside whoever
was already assigned, and emailed once the change is committed.
"""

from unittest.mock import patch

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from plane.db.models import (
    Issue,
    IssueAssignee,
    Module,
    Project,
    ProjectMember,
    RegistrationHandoffConfig,
    RegistrationHandoffRecord,
    State,
    User,
    WorkspaceMember,
)
from plane.utils.registration_handoff import REGISTRATION_AGENT_REQUIRED

EMAIL_TASK = "plane.utils.registration_handoff.send_registration_agent_email"


def make_state(**kwargs):
    # State.save() overwrites `sequence` on insert (last + 15000) - pin it so
    # the workflow order these tests rely on is explicit
    sequence = kwargs.pop("sequence", None)
    state = State.objects.create(**kwargs)
    if sequence is not None:
        State.objects.filter(pk=state.pk).update(sequence=sequence)
        state.sequence = sequence
    return state


def make_member(workspace, project, email, role=15):
    # explicit username: User.objects.create() defaults it to "", which
    # collides with the create_user fixture's own blank-username row
    user = User.objects.create(email=email, username=email, first_name=email.split("@")[0])
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=role, is_active=True)
    ProjectMember.objects.create(project=project, member=user, role=role, is_active=True)
    return user


@pytest.fixture
def project(db, workspace, create_user):
    project = Project.objects.create(
        name="Registration Handoff Project", identifier="RHP", workspace=workspace, created_by=create_user
    )
    ProjectMember.objects.create(project=project, member=create_user, role=20, is_active=True)
    return project


@pytest.fixture
def drafting_state(db, workspace, project):
    return make_state(
        name="Drafting", workspace=workspace, project=project, group="backlog", default=True, sequence=10000
    )


@pytest.fixture
def registration_state(db, workspace, project):
    return make_state(
        name="Registration", workspace=workspace, project=project, group="started", sequence=20000
    )


@pytest.fixture
def eligible_agent(db, workspace, project):
    return make_member(workspace, project, "agent@plane.so")


@pytest.fixture
def ineligible_user(db, workspace, project):
    return make_member(workspace, project, "not-eligible@plane.so")


@pytest.fixture
def module(db, workspace, project, create_user):
    return Module.objects.create(name="Registration Module", project=project, workspace=workspace, created_by=create_user)


@pytest.fixture
def handoff_config(db, project, registration_state, eligible_agent):
    config = RegistrationHandoffConfig.objects.create(
        project=project, workspace=project.workspace, trigger_state=registration_state
    )
    config.eligible_agents.add(eligible_agent)
    return config


@pytest.fixture
def open_handoff_config(db, project, registration_state):
    # no eligible_agents restriction: any active Member/Admin
    return RegistrationHandoffConfig.objects.create(
        project=project, workspace=project.workspace, trigger_state=registration_state
    )


@pytest.fixture
def drafter_issue(db, workspace, project, drafting_state, create_user):
    issue = Issue.objects.create(
        name="A work item", workspace=workspace, project=project, state=drafting_state, created_by=create_user
    )
    IssueAssignee.objects.create(issue=issue, assignee=create_user, project=project, workspace=workspace)
    return issue


def issue_url(workspace_slug, project_id, pk):
    return f"/api/workspaces/{workspace_slug}/projects/{project_id}/issues/{pk}/"


def issues_url(workspace_slug, project_id):
    return f"/api/workspaces/{workspace_slug}/projects/{project_id}/issues/"


def assignee_ids(issue):
    return set(IssueAssignee.objects.filter(issue=issue).values_list("assignee_id", flat=True))


@pytest.mark.contract
class TestRegistrationHandoffOnStateTransition:
    @pytest.mark.django_db
    def test_transition_without_agent_is_rejected(
        self, session_client, workspace, project, registration_state, drafter_issue, handoff_config
    ):
        url = issue_url(workspace.slug, project.id, drafter_issue.id)

        with patch(EMAIL_TASK) as mock_email:
            response = session_client.patch(url, {"state_id": str(registration_state.id)}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, f"Got {response.status_code}: {response.data!r}"
        assert response.data.get("error_code") == REGISTRATION_AGENT_REQUIRED
        drafter_issue.refresh_from_db()
        assert drafter_issue.state_id != registration_state.id
        mock_email.delay.assert_not_called()

    @pytest.mark.django_db
    def test_transition_with_ineligible_agent_is_rejected(
        self, session_client, workspace, project, registration_state, drafter_issue, handoff_config, ineligible_user
    ):
        url = issue_url(workspace.slug, project.id, drafter_issue.id)

        response = session_client.patch(
            url,
            {"state_id": str(registration_state.id), "registration_agent_id": str(ineligible_user.id)},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, f"Got {response.status_code}: {response.data!r}"
        drafter_issue.refresh_from_db()
        assert drafter_issue.state_id != registration_state.id

    @pytest.mark.django_db
    def test_guest_cannot_be_named_registrar(
        self, session_client, workspace, project, registration_state, drafter_issue, open_handoff_config
    ):
        """Guests can't be assigned work items - naming one would email them
        without ever assigning them."""
        guest = make_member(workspace, project, "guest@plane.so", role=5)
        url = issue_url(workspace.slug, project.id, drafter_issue.id)

        response = session_client.patch(
            url,
            {"state_id": str(registration_state.id), "registration_agent_id": str(guest.id)},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, f"Got {response.status_code}: {response.data!r}"
        assert not RegistrationHandoffRecord.objects.filter(issue=drafter_issue).exists()

    @pytest.mark.django_db
    def test_transition_with_eligible_agent_assigns_keeps_drafter_and_emails_on_commit(
        self,
        session_client,
        workspace,
        project,
        registration_state,
        drafter_issue,
        handoff_config,
        eligible_agent,
        create_user,
        django_capture_on_commit_callbacks,
    ):
        url = issue_url(workspace.slug, project.id, drafter_issue.id)

        with (
            patch("plane.app.views.issue.base.issue_activity"),
            patch(EMAIL_TASK) as mock_email,
            django_capture_on_commit_callbacks(execute=True),
        ):
            response = session_client.patch(
                url,
                {"state_id": str(registration_state.id), "registration_agent_id": str(eligible_agent.id)},
                format="json",
            )

        assert response.status_code == status.HTTP_204_NO_CONTENT, f"Got {response.status_code}: {response.data!r}"
        drafter_issue.refresh_from_db()
        assert drafter_issue.state_id == registration_state.id
        assert {eligible_agent.id, create_user.id} <= assignee_ids(drafter_issue)
        assert RegistrationHandoffRecord.objects.get(issue=drafter_issue).agent_id == eligible_agent.id
        mock_email.delay.assert_called_once_with(
            issue_id=str(drafter_issue.id), agent_id=str(eligible_agent.id), actor_id=str(create_user.id)
        )

    @pytest.mark.django_db
    def test_assignees_sent_in_the_same_request_are_kept(
        self,
        session_client,
        workspace,
        project,
        registration_state,
        drafter_issue,
        handoff_config,
        eligible_agent,
        ineligible_user,
        create_user,
    ):
        """The registrar is added on top of the assignees being saved, not
        on top of the old ones - an assignee edit in the same request wins."""
        url = issue_url(workspace.slug, project.id, drafter_issue.id)

        with patch("plane.app.views.issue.base.issue_activity"), patch(EMAIL_TASK):
            response = session_client.patch(
                url,
                {
                    "state_id": str(registration_state.id),
                    "registration_agent_id": str(eligible_agent.id),
                    "assignee_ids": [str(ineligible_user.id)],
                },
                format="json",
            )

        assert response.status_code == status.HTTP_204_NO_CONTENT, f"Got {response.status_code}: {response.data!r}"
        assert assignee_ids(drafter_issue) == {eligible_agent.id, ineligible_user.id}

    @pytest.mark.django_db
    def test_request_failing_later_writes_no_record_and_sends_no_email(
        self,
        session_client,
        workspace,
        project,
        registration_state,
        drafter_issue,
        handoff_config,
        eligible_agent,
        django_capture_on_commit_callbacks,
    ):
        url = issue_url(workspace.slug, project.id, drafter_issue.id)

        with patch(EMAIL_TASK) as mock_email, django_capture_on_commit_callbacks(execute=True):
            response = session_client.patch(
                url,
                {
                    "state_id": str(registration_state.id),
                    "registration_agent_id": str(eligible_agent.id),
                    "priority": "not-a-priority",
                },
                format="json",
            )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, f"Got {response.status_code}: {response.data!r}"
        assert not RegistrationHandoffRecord.objects.filter(issue=drafter_issue).exists()
        mock_email.delay.assert_not_called()

    @pytest.mark.django_db
    def test_unrelated_field_update_does_not_require_agent(
        self, session_client, workspace, project, drafter_issue, handoff_config
    ):
        url = issue_url(workspace.slug, project.id, drafter_issue.id)

        with patch("plane.app.views.issue.base.issue_activity"):
            response = session_client.patch(url, {"priority": "high"}, format="json")

        assert response.status_code == status.HTTP_204_NO_CONTENT, f"Got {response.status_code}: {response.data!r}"

    @pytest.mark.django_db
    def test_no_config_means_no_restriction(
        self, session_client, workspace, project, registration_state, drafter_issue
    ):
        url = issue_url(workspace.slug, project.id, drafter_issue.id)

        with patch("plane.app.views.issue.base.issue_activity"):
            response = session_client.patch(url, {"state_id": str(registration_state.id)}, format="json")

        assert response.status_code == status.HTTP_204_NO_CONTENT, f"Got {response.status_code}: {response.data!r}"

    @pytest.mark.django_db
    def test_reentry_reuses_the_registrar_and_emails_again(
        self,
        session_client,
        workspace,
        project,
        drafting_state,
        registration_state,
        drafter_issue,
        handoff_config,
        eligible_agent,
        django_capture_on_commit_callbacks,
    ):
        url = issue_url(workspace.slug, project.id, drafter_issue.id)

        with (
            patch("plane.app.views.issue.base.issue_activity"),
            patch(EMAIL_TASK) as mock_email,
            django_capture_on_commit_callbacks(execute=True),
        ):
            first = session_client.patch(
                url,
                {"state_id": str(registration_state.id), "registration_agent_id": str(eligible_agent.id)},
                format="json",
            )
            assert first.status_code == status.HTTP_204_NO_CONTENT, f"Got {first.status_code}: {first.data!r}"

            out = session_client.patch(url, {"state_id": str(drafting_state.id)}, format="json")
            assert out.status_code == status.HTTP_204_NO_CONTENT, f"Got {out.status_code}: {out.data!r}"

            back = session_client.patch(url, {"state_id": str(registration_state.id)}, format="json")

        assert back.status_code == status.HTTP_204_NO_CONTENT, f"Got {back.status_code}: {back.data!r}"
        assert eligible_agent.id in assignee_ids(drafter_issue)
        assert RegistrationHandoffRecord.objects.filter(issue=drafter_issue).count() == 1
        assert mock_email.delay.call_count == 2, "the registrar is emailed on every entry"

    @pytest.mark.django_db
    def test_registrar_who_left_the_project_must_be_replaced_on_reentry(
        self,
        session_client,
        workspace,
        project,
        drafting_state,
        registration_state,
        drafter_issue,
        open_handoff_config,
        eligible_agent,
        ineligible_user,
    ):
        RegistrationHandoffRecord.objects.create(
            issue=drafter_issue, project=project, workspace=workspace, agent=eligible_agent
        )
        ProjectMember.objects.filter(project=project, member=eligible_agent).update(is_active=False)
        url = issue_url(workspace.slug, project.id, drafter_issue.id)

        response = session_client.patch(url, {"state_id": str(registration_state.id)}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST, f"Got {response.status_code}: {response.data!r}"
        assert response.data.get("error_code") == REGISTRATION_AGENT_REQUIRED

        with patch("plane.app.views.issue.base.issue_activity"), patch(EMAIL_TASK):
            response = session_client.patch(
                url,
                {"state_id": str(registration_state.id), "registration_agent_id": str(ineligible_user.id)},
                format="json",
            )
        assert response.status_code == status.HTTP_204_NO_CONTENT, f"Got {response.status_code}: {response.data!r}"
        assert RegistrationHandoffRecord.objects.get(issue=drafter_issue).agent_id == ineligible_user.id

    @pytest.mark.django_db
    def test_first_entry_still_requires_an_agent_after_other_transitions(
        self,
        session_client,
        workspace,
        project,
        drafting_state,
        registration_state,
        drafter_issue,
        handoff_config,
    ):
        url = issue_url(workspace.slug, project.id, drafter_issue.id)

        with patch("plane.app.views.issue.base.issue_activity"):
            session_client.patch(url, {"state_id": str(drafting_state.id)}, format="json")
            response = session_client.patch(url, {"state_id": str(registration_state.id)}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, f"Got {response.status_code}: {response.data!r}"
        assert not RegistrationHandoffRecord.objects.filter(issue=drafter_issue).exists()


@pytest.mark.contract
class TestRegistrationHandoffOnCreate:
    @pytest.mark.django_db
    def test_creating_straight_into_registration_requires_a_registrar(
        self, session_client, workspace, project, drafting_state, registration_state, module, handoff_config
    ):
        response = session_client.post(
            issues_url(workspace.slug, project.id),
            {"name": "Direct", "state_id": str(registration_state.id), "module_ids": [str(module.id)]},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, f"Got {response.status_code}: {response.data!r}"
        assert response.data.get("error_code") == REGISTRATION_AGENT_REQUIRED
        assert not Issue.objects.filter(name="Direct").exists()

    @pytest.mark.django_db
    def test_creating_straight_into_registration_with_a_registrar_assigns_and_emails(
        self,
        session_client,
        workspace,
        project,
        drafting_state,
        registration_state,
        module,
        handoff_config,
        eligible_agent,
        django_capture_on_commit_callbacks,
    ):
        with (
            patch("plane.app.views.issue.base.issue_activity"),
            patch(EMAIL_TASK) as mock_email,
            django_capture_on_commit_callbacks(execute=True),
        ):
            response = session_client.post(
                issues_url(workspace.slug, project.id),
                {
                    "name": "Direct",
                    "state_id": str(registration_state.id),
                    "module_ids": [str(module.id)],
                    "registration_agent_id": str(eligible_agent.id),
                },
                format="json",
            )
        assert response.status_code == status.HTTP_201_CREATED, f"Got {response.status_code}: {response.data!r}"
        issue = Issue.objects.get(name="Direct")
        assert eligible_agent.id in assignee_ids(issue)
        assert RegistrationHandoffRecord.objects.get(issue=issue).agent_id == eligible_agent.id
        mock_email.delay.assert_called_once()


@pytest.fixture
def after_registration_state(db, workspace, project):
    return make_state(name="Xerox and Binding", workspace=workspace, project=project, group="started", sequence=30000)


@pytest.fixture
def before_registration_state(db, workspace, project):
    return make_state(name="Draft Approval", workspace=workspace, project=project, group="started", sequence=15000)


@pytest.fixture
def cancelled_state(db, workspace, project):
    return make_state(name="Cancelled", workspace=workspace, project=project, group="cancelled", sequence=90000)


@pytest.mark.contract
class TestRegistrationCannotBeSkipped:
    @pytest.mark.django_db
    def test_jumping_past_registration_without_a_registrar_is_rejected(
        self, session_client, workspace, project, after_registration_state, drafter_issue, handoff_config
    ):
        url = issue_url(workspace.slug, project.id, drafter_issue.id)
        with patch(EMAIL_TASK) as mock_email:
            response = session_client.patch(url, {"state_id": str(after_registration_state.id)}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, f"Got {response.status_code}: {response.data!r}"
        assert response.data.get("error_code") == REGISTRATION_AGENT_REQUIRED
        assert "can't be skipped" in response.data["error"]
        drafter_issue.refresh_from_db()
        assert drafter_issue.state_id != after_registration_state.id
        mock_email.delay.assert_not_called()

    @pytest.mark.django_db
    def test_jumping_past_registration_with_a_registrar_hands_off_and_emails(
        self,
        session_client,
        workspace,
        project,
        after_registration_state,
        drafter_issue,
        handoff_config,
        eligible_agent,
        django_capture_on_commit_callbacks,
    ):
        url = issue_url(workspace.slug, project.id, drafter_issue.id)
        with (
            patch("plane.app.views.issue.base.issue_activity"),
            patch(EMAIL_TASK) as mock_email,
            django_capture_on_commit_callbacks(execute=True),
        ):
            response = session_client.patch(
                url,
                {"state_id": str(after_registration_state.id), "registration_agent_id": str(eligible_agent.id)},
                format="json",
            )

        assert response.status_code == status.HTTP_204_NO_CONTENT, f"Got {response.status_code}: {response.data!r}"
        drafter_issue.refresh_from_db()
        assert drafter_issue.state_id == after_registration_state.id
        assert eligible_agent.id in assignee_ids(drafter_issue)
        assert RegistrationHandoffRecord.objects.get(issue=drafter_issue).agent_id == eligible_agent.id
        mock_email.delay.assert_called_once()

    @pytest.mark.django_db
    def test_moves_before_registration_and_into_cancelled_need_no_registrar(
        self, session_client, workspace, project, before_registration_state, cancelled_state, drafter_issue, handoff_config
    ):
        url = issue_url(workspace.slug, project.id, drafter_issue.id)
        for target in (before_registration_state, cancelled_state):
            with patch("plane.app.views.issue.base.issue_activity"):
                response = session_client.patch(url, {"state_id": str(target.id)}, format="json")
            assert response.status_code == status.HTTP_204_NO_CONTENT, f"{target.name}: {response.data!r}"

    @pytest.mark.django_db
    def test_item_with_a_registrar_on_record_moves_on_freely(
        self, session_client, workspace, project, after_registration_state, drafter_issue, handoff_config, eligible_agent
    ):
        RegistrationHandoffRecord.objects.create(
            issue=drafter_issue, project=project, workspace=workspace, agent=eligible_agent
        )
        url = issue_url(workspace.slug, project.id, drafter_issue.id)
        with patch("plane.app.views.issue.base.issue_activity"), patch(EMAIL_TASK) as mock_email:
            response = session_client.patch(url, {"state_id": str(after_registration_state.id)}, format="json")
        assert response.status_code == status.HTTP_204_NO_CONTENT, f"Got {response.status_code}: {response.data!r}"
        mock_email.delay.assert_not_called()

    @pytest.mark.django_db
    def test_item_already_past_registration_is_not_re_asked_between_later_stages(
        self, session_client, workspace, project, registration_state, after_registration_state, drafter_issue, handoff_config
    ):
        # a work item that got past registration before this rule existed
        later_state = make_state(name="Closed", workspace=workspace, project=project, group="completed", sequence=40000)
        Issue.objects.filter(pk=drafter_issue.pk).update(state=after_registration_state)
        url = issue_url(workspace.slug, project.id, drafter_issue.id)
        with patch("plane.app.views.issue.base.issue_activity"):
            response = session_client.patch(url, {"state_id": str(later_state.id)}, format="json")
        assert response.status_code == status.HTTP_204_NO_CONTENT, f"Got {response.status_code}: {response.data!r}"

    @pytest.mark.django_db
    def test_creating_past_registration_requires_a_registrar(
        self, session_client, workspace, project, drafting_state, after_registration_state, module, handoff_config
    ):
        response = session_client.post(
            issues_url(workspace.slug, project.id),
            {"name": "Skipped", "state_id": str(after_registration_state.id), "module_ids": [str(module.id)]},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, f"Got {response.status_code}: {response.data!r}"
        assert response.data.get("error_code") == REGISTRATION_AGENT_REQUIRED
        assert not Issue.objects.filter(name="Skipped").exists()


@pytest.mark.contract
class TestRegistrationHandoffConfigEndpoint:
    @pytest.mark.django_db
    def test_guest_cannot_be_configured_as_eligible_registrar(
        self, workspace, project, registration_state, create_user
    ):
        guest = make_member(workspace, project, "guest2@plane.so", role=5)
        client = APIClient()
        client.force_authenticate(user=create_user)
        response = client.post(
            f"/api/workspaces/{workspace.slug}/projects/{project.id}/registration-handoff-config/",
            {"trigger_state_id": str(registration_state.id), "eligible_agent_ids": [str(guest.id)]},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, f"Got {response.status_code}: {response.data!r}"
