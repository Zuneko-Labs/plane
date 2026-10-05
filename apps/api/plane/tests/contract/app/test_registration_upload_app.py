# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
The registrar of a work item in the registration state uploading a file —
in a comment (image or document) or in the Attachments section — moves the
work item on to the next state. Nobody else's uploads do.
"""

from unittest.mock import patch

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from plane.db.models import FileAsset, Issue, RegistrationHandoffRecord

# shared fixtures for the registration hand-off flow
from plane.tests.contract.app.test_registration_handoff_app import (  # noqa: F401
    drafting_state,
    eligible_agent,
    handoff_config,
    make_state,
    project,
    registration_state,
)

METADATA_TASK = "plane.app.views.issue.attachment.get_asset_object_metadata"
DOC_LINK = (
    '<p><a href="http://localhost:8000/api/assets/v2/workspaces/ws/projects/p/download/'
    '3f2a1b0c-1d2e-4f50-8a6b-7c8d9e0f1a2b/?ext=pdf">deed.pdf</a></p>'
)
IMAGE = '<image-component src="5b6c7d8e-9f0a-4b1c-8d2e-3f4a5b6c7d8e" width="200"></image-component>'


@pytest.fixture
def next_state(db, workspace, project):  # noqa: F811
    return make_state(name="Xerox and Binding", workspace=workspace, project=project, group="started", sequence=30000)


@pytest.fixture
def registrar_issue(db, workspace, project, registration_state, handoff_config, eligible_agent, create_user):  # noqa: F811
    issue = Issue.objects.create(
        name="In registration", workspace=workspace, project=project, state=registration_state, created_by=create_user
    )
    RegistrationHandoffRecord.objects.create(issue=issue, project=project, workspace=workspace, agent=eligible_agent)
    return issue


@pytest.fixture
def registrar_client(eligible_agent):  # noqa: F811
    client = APIClient()
    client.force_authenticate(user=eligible_agent)
    return client


def comments_url(workspace_slug, project_id, issue_id):
    return f"/api/workspaces/{workspace_slug}/projects/{project_id}/issues/{issue_id}/comments/"


def attachment_url(workspace_slug, project_id, issue_id, pk):
    return f"/api/assets/v2/workspaces/{workspace_slug}/projects/{project_id}/issues/{issue_id}/attachments/{pk}/"


def make_attachment(issue, user):
    return FileAsset.objects.create(
        attributes={"name": "deed.pdf", "type": "application/pdf", "size": 10},
        asset=f"{issue.workspace_id}/deed.pdf",
        size=10,
        workspace=issue.workspace,
        project=issue.project,
        issue=issue,
        created_by=user,
        entity_type=FileAsset.EntityTypeContext.ISSUE_ATTACHMENT,
    )


def state_of(issue):
    issue.refresh_from_db()
    return issue.state_id


@pytest.mark.contract
class TestRegistrarUploadAdvancesState:
    @pytest.mark.django_db
    @pytest.mark.parametrize("html", [DOC_LINK, f"<p>done</p>{IMAGE}"])
    def test_registrar_comment_with_file_moves_to_next_state(
        self, registrar_client, workspace, project, registrar_issue, next_state, html
    ):
        response = registrar_client.post(
            comments_url(workspace.slug, project.id, registrar_issue.id), {"comment_html": html}, format="json"
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["state_advanced"] is True
        assert state_of(registrar_issue) == next_state.id

    @pytest.mark.django_db
    def test_plain_text_comment_does_not_move(
        self, registrar_client, workspace, project, registrar_issue, registration_state, next_state
    ):
        response = registrar_client.post(
            comments_url(workspace.slug, project.id, registrar_issue.id),
            {"comment_html": "<p>on my way</p>"},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["state_advanced"] is False
        assert state_of(registrar_issue) == registration_state.id

    @pytest.mark.django_db
    def test_someone_else_uploading_does_not_move(
        self, session_client, workspace, project, registrar_issue, registration_state, next_state
    ):
        response = session_client.post(
            comments_url(workspace.slug, project.id, registrar_issue.id), {"comment_html": DOC_LINK}, format="json"
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["state_advanced"] is False
        assert state_of(registrar_issue) == registration_state.id

    @pytest.mark.django_db
    def test_not_in_registration_does_not_move(
        self, registrar_client, workspace, project, registrar_issue, drafting_state, next_state
    ):
        Issue.objects.filter(pk=registrar_issue.pk).update(state=drafting_state)
        response = registrar_client.post(
            comments_url(workspace.slug, project.id, registrar_issue.id), {"comment_html": DOC_LINK}, format="json"
        )
        assert response.data["state_advanced"] is False
        assert state_of(registrar_issue) == drafting_state.id

    @pytest.mark.django_db
    def test_no_state_after_registration_does_not_move(
        self, registrar_client, workspace, project, registrar_issue, registration_state
    ):
        response = registrar_client.post(
            comments_url(workspace.slug, project.id, registrar_issue.id), {"comment_html": DOC_LINK}, format="json"
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["state_advanced"] is False
        assert state_of(registrar_issue) == registration_state.id

    @pytest.mark.django_db
    def test_triage_and_cancelled_states_are_skipped(
        self, registrar_client, workspace, project, registrar_issue, next_state
    ):
        make_state(name="Triage", workspace=workspace, project=project, group="triage", sequence=25000)
        make_state(name="Cancelled", workspace=workspace, project=project, group="cancelled", sequence=26000)
        registrar_client.post(
            comments_url(workspace.slug, project.id, registrar_issue.id), {"comment_html": DOC_LINK}, format="json"
        )
        assert state_of(registrar_issue) == next_state.id

    @pytest.mark.django_db
    def test_editing_comment_moves_only_when_a_file_is_added(
        self, registrar_client, workspace, project, registrar_issue, registration_state, next_state
    ):
        url = comments_url(workspace.slug, project.id, registrar_issue.id)
        # comment with a file posted while the work item was elsewhere
        Issue.objects.filter(pk=registrar_issue.pk).update(state=next_state)
        created = registrar_client.post(url, {"comment_html": DOC_LINK}, format="json")
        Issue.objects.filter(pk=registrar_issue.pk).update(state=registration_state)
        comment_url = f"{url}{created.data['id']}/"

        text_edit = registrar_client.patch(comment_url, {"comment_html": f"{DOC_LINK}<p>note</p>"}, format="json")
        assert text_edit.data["state_advanced"] is False
        assert state_of(registrar_issue) == registration_state.id

        file_edit = registrar_client.patch(comment_url, {"comment_html": f"{DOC_LINK}{IMAGE}"}, format="json")
        assert file_edit.data["state_advanced"] is True
        assert state_of(registrar_issue) == next_state.id

    @pytest.mark.django_db
    def test_registrar_attachment_upload_moves_once(
        self, registrar_client, workspace, project, registrar_issue, next_state, eligible_agent
    ):
        attachment = make_attachment(registrar_issue, eligible_agent)
        url = attachment_url(workspace.slug, project.id, registrar_issue.id, attachment.id)
        with patch(METADATA_TASK):
            response = registrar_client.patch(url, {}, format="json")
            assert response.status_code == status.HTTP_200_OK
            assert response.data["state_advanced"] is True
            assert state_of(registrar_issue) == next_state.id

            again = registrar_client.patch(url, {}, format="json")
            assert again.data["state_advanced"] is False

    @pytest.mark.django_db
    def test_attachment_by_someone_else_does_not_move(
        self, session_client, workspace, project, registrar_issue, registration_state, next_state, create_user
    ):
        attachment = make_attachment(registrar_issue, create_user)
        with patch(METADATA_TASK):
            response = session_client.patch(
                attachment_url(workspace.slug, project.id, registrar_issue.id, attachment.id), {}, format="json"
            )
        assert response.data["state_advanced"] is False
        assert state_of(registrar_issue) == registration_state.id
