# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from unittest import mock

import pytest
from rest_framework import status

from plane.db.models import EventLog, Issue, IssueComment, Project, ProjectMember, State


@pytest.fixture
def project(db, workspace, create_user):
    """Create a test project with the requesting user as an active member."""
    project = Project.objects.create(
        name="Test Project",
        identifier="TP",
        workspace=workspace,
        created_by=create_user,
    )
    ProjectMember.objects.create(
        project=project,
        member=create_user,
        role=20,  # Admin
        is_active=True,
    )
    return project


@pytest.fixture
def state(db, workspace, project):
    return State.objects.create(
        name="Todo",
        project=project,
        workspace=workspace,
        group="backlog",
        default=True,
    )


@pytest.fixture
def issue(db, workspace, project, state, create_user):
    return Issue.objects.create(
        name="Test Issue",
        workspace=workspace,
        project=project,
        state=state,
        created_by=create_user,
    )


@pytest.mark.contract
class TestIssueListOrderByInjection:
    """Regression tests for GHSA-p885-6jpg-cr2p on the work-item list
    endpoint: GET /api/v1/workspaces/{slug}/projects/{project_id}/issues/.

    The raw ``order_by`` query parameter fell through the endpoint's hardcoded
    branch logic to ``issue_queryset.order_by(order_by_param)``, letting an
    attacker order by sensitive related columns (blind oracle) or crash the
    endpoint with an unknown field (HTTP 500). The fix sanitizes the parameter
    against ISSUE_ORDER_BY_ALLOWLIST before the branch logic runs.
    """

    def get_url(self, workspace_slug, project_id):
        return f"/api/v1/workspaces/{workspace_slug}/projects/{project_id}/issues/"

    @pytest.mark.django_db
    def test_invalid_order_by_does_not_500(self, api_key_client, workspace, project, issue):
        """Unknown field used to raise FieldError → HTTP 500; now sanitized to
        the safe default and returns 200 (DoS half of the advisory)."""
        url = self.get_url(workspace.slug, project.id)
        response = api_key_client.get(url, {"order_by": "not_a_field"})

        assert response.status_code == status.HTTP_200_OK, f"Got {response.status_code}: {response.data!r}"

    @pytest.mark.django_db
    def test_relational_order_by_injection_does_not_500(self, api_key_client, workspace, project, issue):
        """Ordering by a related-table column (``created_by__password``) used to
        reach ``.order_by()`` raw, forming a blind ordering oracle. It is now
        neutralized to the safe default. (Deterministic neutralization is
        asserted in tests/unit/utils/test_order_by_sanitize.py.)"""
        url = self.get_url(workspace.slug, project.id)
        response = api_key_client.get(url, {"order_by": "created_by__password"})

        assert response.status_code == status.HTTP_200_OK, f"Got {response.status_code}: {response.data!r}"

    @pytest.mark.django_db
    def test_legitimate_order_by_still_works(self, api_key_client, workspace, project, issue):
        """A valid, allowlisted ordering value continues to return 200 —
        the sanitizer must not break legitimate ordering."""
        url = self.get_url(workspace.slug, project.id)

        for value in ["-created_at", "priority", "state__group", "sequence_id"]:
            response = api_key_client.get(url, {"order_by": value})
            assert response.status_code == status.HTTP_200_OK, (
                f"order_by={value!r} got {response.status_code}: {response.data!r}"
            )


@pytest.mark.contract
class TestIssueOutboxWiring:
    """Phase 4 outbox-wiring regressions for api/views/issue.py — the
    largest, highest-merge-risk file in the sync architecture plan. Covers
    the endpoints actually reachable via URL routing (create, patch, and
    the comment sub-resource); the ``put`` upsert method on
    IssueListCreateAPIEndpoint is pre-existing dead code — no URL pattern
    registers PUT for it — and is out of scope here."""

    def get_url(self, workspace_slug, project_id):
        return f"/api/v1/workspaces/{workspace_slug}/projects/{project_id}/issues/"

    def get_detail_url(self, workspace_slug, project_id, pk):
        return f"/api/v1/workspaces/{workspace_slug}/projects/{project_id}/issues/{pk}/"

    def get_comment_url(self, workspace_slug, project_id, issue_id):
        return f"/api/v1/workspaces/{workspace_slug}/projects/{project_id}/issues/{issue_id}/comments/"

    @pytest.mark.django_db
    def test_create_issue_writes_an_outbox_event(self, api_key_client, workspace, project, state):
        url = self.get_url(workspace.slug, project.id)
        response = api_key_client.post(url, {"name": "New Issue"}, format="json")

        assert response.status_code == status.HTTP_201_CREATED, f"Got {response.status_code}: {response.data!r}"
        event = EventLog.objects.get(entity_type="issue", entity_id=response.data["id"])
        assert event.event_type == "issue.created"
        assert event.workspace_id == workspace.id
        assert event.project_id == project.id
        assert event.dispatch_seq is None

    @pytest.mark.django_db
    def test_patch_issue_records_a_diff(self, api_key_client, workspace, project, issue):
        url = self.get_detail_url(workspace.slug, project.id, issue.id)
        response = api_key_client.patch(url, {"name": "Renamed"}, format="json")

        assert response.status_code == status.HTTP_200_OK, f"Got {response.status_code}: {response.data!r}"
        event = EventLog.objects.filter(entity_type="issue", entity_id=issue.id, event_type="issue.updated").get()
        assert event.changes == {"name": {"old": "Test Issue", "new": "Renamed"}}

    @pytest.mark.django_db
    def test_no_outbox_event_survives_a_rolled_back_create(self, api_key_client, workspace, project, state):
        url = self.get_url(workspace.slug, project.id)

        with mock.patch(
            "plane.api.views.issue.write_model_event",
            side_effect=RuntimeError("forced failure for rollback test"),
        ):
            response = api_key_client.post(url, {"name": "Rollback Probe"}, format="json")

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR, (
            f"Got {response.status_code}: {response.data!r}"
        )
        assert Issue.objects.filter(name="Rollback Probe").count() == 0
        assert EventLog.objects.count() == 0

    @pytest.mark.django_db
    def test_create_comment_writes_an_outbox_event(self, api_key_client, workspace, project, issue):
        url = self.get_comment_url(workspace.slug, project.id, issue.id)
        response = api_key_client.post(url, {"comment_html": "<p>hello</p>"}, format="json")

        assert response.status_code == status.HTTP_201_CREATED, f"Got {response.status_code}: {response.data!r}"
        event = EventLog.objects.get(entity_type="issue_comment", entity_id=response.data["id"])
        assert event.event_type == "issue_comment.created"
        assert event.workspace_id == workspace.id
        assert event.project_id == project.id

    @pytest.mark.django_db
    def test_update_comment_records_a_diff(self, api_key_client, workspace, project, issue, create_user):
        comment = IssueComment.objects.create(
            project=project,
            workspace=workspace,
            issue=issue,
            actor=create_user,
            comment_html="<p>original</p>",
        )
        url = f"{self.get_comment_url(workspace.slug, project.id, issue.id)}{comment.id}/"
        response = api_key_client.patch(url, {"comment_html": "<p>edited</p>"}, format="json")

        assert response.status_code == status.HTTP_200_OK, f"Got {response.status_code}: {response.data!r}"
        event = EventLog.objects.filter(
            entity_type="issue_comment", entity_id=comment.id, event_type="issue_comment.updated"
        ).get()
        assert event.changes is not None
