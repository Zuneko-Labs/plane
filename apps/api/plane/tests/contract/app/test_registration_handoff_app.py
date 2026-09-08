# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Registration hand-off: moving a work item into the project's configured
registration state must name an eligible agent, or the transition is
rejected with 400 — before anything is written. On success the agent is
added as an assignee alongside whoever was already assigned (the drafter
stays on).
"""

from unittest.mock import patch

import pytest
from rest_framework import status

from plane.db.models import (
    Issue,
    IssueAssignee,
    Project,
    ProjectMember,
    RegistrationHandoffConfig,
    RegistrationHandoffRecord,
    State,
    User,
)


@pytest.fixture
def project(db, workspace, create_user):
    project = Project.objects.create(
        name="Registration Handoff Project", identifier="RHP", workspace=workspace, created_by=create_user
    )
    ProjectMember.objects.create(project=project, member=create_user, role=20, is_active=True)
    return project


@pytest.fixture
def drafting_state(db, workspace, project):
    return State.objects.create(name="Drafting", workspace=workspace, project=project, group="backlog", default=True)


@pytest.fixture
def registration_state(db, workspace, project):
    return State.objects.create(name="Sent for Registration", workspace=workspace, project=project, group="started")


@pytest.fixture
def eligible_agent(db, project):
    user = User.objects.create(email="agent@plane.so", first_name="Agent", last_name="Eligible")
    ProjectMember.objects.create(project=project, member=user, role=15, is_active=True)
    return user


@pytest.fixture
def ineligible_user(db, project):
    user = User.objects.create(email="not-eligible@plane.so", first_name="Not", last_name="Eligible")
    ProjectMember.objects.create(project=project, member=user, role=15, is_active=True)
    return user


@pytest.fixture
def handoff_config(db, project, registration_state, eligible_agent):
    config = RegistrationHandoffConfig.objects.create(
        project=project, workspace=project.workspace, trigger_state=registration_state
    )
    config.eligible_agents.add(eligible_agent)
    return config


@pytest.fixture
def drafter_issue(db, workspace, project, drafting_state, create_user):
    issue = Issue.objects.create(
        name="A work item", workspace=workspace, project=project, state=drafting_state, created_by=create_user
    )
    IssueAssignee.objects.create(issue=issue, assignee=create_user, project=project, workspace=workspace)
    return issue


def issue_url(workspace_slug, project_id, pk):
    return f"/api/workspaces/{workspace_slug}/projects/{project_id}/issues/{pk}/"


@pytest.mark.contract
class TestRegistrationHandoffOnStateTransition:
    @pytest.mark.django_db
    def test_transition_without_agent_is_rejected(
        self, session_client, workspace, project, registration_state, drafter_issue, handoff_config
    ):
        url = issue_url(workspace.slug, project.id, drafter_issue.id)

        response = session_client.patch(url, {"state_id": str(registration_state.id)}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, f"Got {response.status_code}: {response.data!r}"
        assert "registration_agent_id" in response.data.get("error", "")
        drafter_issue.refresh_from_db()
        assert drafter_issue.state_id != registration_state.id

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
    def test_transition_with_eligible_agent_succeeds_and_keeps_drafter(
        self,
        session_client,
        workspace,
        project,
        registration_state,
        drafter_issue,
        handoff_config,
        eligible_agent,
        create_user,
    ):
        url = issue_url(workspace.slug, project.id, drafter_issue.id)

        with patch("plane.app.views.issue.base.issue_activity"):
            response = session_client.patch(
                url,
                {"state_id": str(registration_state.id), "registration_agent_id": str(eligible_agent.id)},
                format="json",
            )

        assert response.status_code == status.HTTP_200_OK, f"Got {response.status_code}: {response.data!r}"
        drafter_issue.refresh_from_db()
        assert drafter_issue.state_id == registration_state.id

        assignee_ids = set(IssueAssignee.objects.filter(issue=drafter_issue).values_list("assignee_id", flat=True))
        assert eligible_agent.id in assignee_ids, "agent must be assigned"
        assert create_user.id in assignee_ids, "drafter must stay assigned"

    @pytest.mark.django_db
    def test_unrelated_field_update_does_not_require_agent(
        self, session_client, workspace, project, drafter_issue, handoff_config
    ):
        """Only an actual transition INTO the trigger state is gated —
        editing anything else, or re-saving the same state, is unaffected."""
        url = issue_url(workspace.slug, project.id, drafter_issue.id)

        with patch("plane.app.views.issue.base.issue_activity"):
            response = session_client.patch(url, {"priority": "high"}, format="json")

        assert response.status_code == status.HTTP_200_OK, f"Got {response.status_code}: {response.data!r}"

    @pytest.mark.django_db
    def test_no_config_means_no_restriction(
        self, session_client, workspace, project, registration_state, drafter_issue
    ):
        """A project with no RegistrationHandoffConfig row is unaffected —
        this rolls out per project, not as a blanket constraint."""
        url = issue_url(workspace.slug, project.id, drafter_issue.id)

        with patch("plane.app.views.issue.base.issue_activity"):
            response = session_client.patch(url, {"state_id": str(registration_state.id)}, format="json")

        assert response.status_code == status.HTTP_200_OK, f"Got {response.status_code}: {response.data!r}"

    @pytest.mark.django_db
    def test_reentry_does_not_require_a_new_agent(
        self,
        session_client,
        workspace,
        project,
        drafting_state,
        registration_state,
        drafter_issue,
        handoff_config,
        eligible_agent,
    ):
        """Naming an agent is a once-per-work-item step. Moving out of the
        registration state and back in must NOT re-prompt — the same
        physical person is still responsible for the sub-registrar trip.
        """
        url = issue_url(workspace.slug, project.id, drafter_issue.id)

        with patch("plane.app.views.issue.base.issue_activity"):
            # first entry: agent named
            first = session_client.patch(
                url,
                {"state_id": str(registration_state.id), "registration_agent_id": str(eligible_agent.id)},
                format="json",
            )
            assert first.status_code == status.HTTP_200_OK, f"Got {first.status_code}: {first.data!r}"

            # back out to drafting
            out = session_client.patch(url, {"state_id": str(drafting_state.id)}, format="json")
            assert out.status_code == status.HTTP_200_OK, f"Got {out.status_code}: {out.data!r}"

            # re-entry with NO registration_agent_id - this used to 400
            back = session_client.patch(url, {"state_id": str(registration_state.id)}, format="json")

        assert back.status_code == status.HTTP_200_OK, f"Got {back.status_code}: {back.data!r}"
        drafter_issue.refresh_from_db()
        assert drafter_issue.state_id == registration_state.id

        # the original agent is still on the item, and only one record exists
        assignee_ids = set(IssueAssignee.objects.filter(issue=drafter_issue).values_list("assignee_id", flat=True))
        assert eligible_agent.id in assignee_ids, "original agent must stay assigned on re-entry"
        assert RegistrationHandoffRecord.objects.filter(issue=drafter_issue).count() == 1

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
        """Unrelated state churn must not be mistaken for a prior handoff —
        the gate still applies on the genuine first entry."""
        url = issue_url(workspace.slug, project.id, drafter_issue.id)

        with patch("plane.app.views.issue.base.issue_activity"):
            session_client.patch(url, {"state_id": str(drafting_state.id)}, format="json")
            response = session_client.patch(url, {"state_id": str(registration_state.id)}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, f"Got {response.status_code}: {response.data!r}"
        assert not RegistrationHandoffRecord.objects.filter(issue=drafter_issue).exists()
