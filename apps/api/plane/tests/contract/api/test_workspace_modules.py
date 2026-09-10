# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Workspace-level modules endpoint — lists modules across every project in a
workspace in one call (instead of one call per project), with an optional
`updated_at__gte` filter for incremental sync.
"""

from datetime import timedelta
from urllib.parse import urlencode

import pytest
from django.utils import timezone
from rest_framework import status

from plane.db.models import Module, Project, ProjectMember, User, Workspace
from plane.db.models.api import APIToken


def _get_url(workspace_slug, **params):
    url = f"/api/v1/workspaces/{workspace_slug}/modules/"
    if params:
        url += f"?{urlencode(params)}"
    return url


@pytest.fixture
def project_a(db, workspace, create_user):
    project = Project.objects.create(
        name="Project A", identifier="PJA", workspace=workspace, created_by=create_user, module_view=True
    )
    ProjectMember.objects.create(project=project, member=create_user, role=20, is_active=True)
    return project


@pytest.fixture
def project_b(db, workspace, create_user):
    project = Project.objects.create(
        name="Project B", identifier="PJB", workspace=workspace, created_by=create_user, module_view=True
    )
    ProjectMember.objects.create(project=project, member=create_user, role=20, is_active=True)
    return project


@pytest.mark.contract
class TestWorkspaceModuleListAPIEndpoint:
    @pytest.mark.django_db
    def test_lists_modules_across_multiple_projects(self, api_key_client, workspace, project_a, project_b):
        Module.objects.create(name="Module A1", project=project_a, workspace=workspace)
        Module.objects.create(name="Module B1", project=project_b, workspace=workspace)

        response = api_key_client.get(_get_url(workspace.slug))

        assert response.status_code == status.HTTP_200_OK, f"Got {response.status_code}: {response.data!r}"
        names = {m["name"] for m in response.data["results"]}
        assert names == {"Module A1", "Module B1"}

    @pytest.mark.django_db
    def test_archived_modules_are_excluded(self, api_key_client, workspace, project_a):
        Module.objects.create(name="Active", project=project_a, workspace=workspace)
        Module.objects.create(name="Archived", project=project_a, workspace=workspace, archived_at=timezone.now())

        response = api_key_client.get(_get_url(workspace.slug))

        assert response.status_code == status.HTTP_200_OK
        names = {m["name"] for m in response.data["results"]}
        assert names == {"Active"}

    @pytest.mark.django_db
    def test_updated_at_gte_filters_out_stale_modules(self, api_key_client, workspace, project_a):
        old = Module.objects.create(name="Old", project=project_a, workspace=workspace)
        recent = Module.objects.create(name="Recent", project=project_a, workspace=workspace)

        cutoff = timezone.now()
        Module.objects.filter(pk=old.pk).update(updated_at=cutoff - timedelta(days=1))
        Module.objects.filter(pk=recent.pk).update(updated_at=cutoff + timedelta(days=1))

        response = api_key_client.get(_get_url(workspace.slug, **{"updated_at__gte": cutoff.isoformat()}))

        assert response.status_code == status.HTTP_200_OK, f"Got {response.status_code}: {response.data!r}"
        names = {m["name"] for m in response.data["results"]}
        assert names == {"Recent"}

    @pytest.mark.django_db
    def test_omitting_the_filter_returns_everything(self, api_key_client, workspace, project_a):
        Module.objects.create(name="One", project=project_a, workspace=workspace)
        Module.objects.create(name="Two", project=project_a, workspace=workspace)

        response = api_key_client.get(_get_url(workspace.slug))

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 2

    @pytest.mark.django_db
    def test_invalid_updated_at_gte_returns_400(self, api_key_client, workspace, project_a):
        response = api_key_client.get(_get_url(workspace.slug, **{"updated_at__gte": "not-a-date"}))

        assert response.status_code == status.HTTP_400_BAD_REQUEST, f"Got {response.status_code}: {response.data!r}"

    @pytest.mark.django_db
    def test_non_member_is_forbidden(self, api_client, workspace, project_a):
        outsider = User.objects.create(email="outsider@plane.so", username="outsider")
        token = APIToken.objects.create(user=outsider, label="Outsider Token", token="outsider-token-workspace-mods")
        api_client.credentials(HTTP_X_API_KEY=token.token)

        response = api_client.get(_get_url(workspace.slug))

        assert response.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.django_db
    def test_workspace_scoping_is_enforced(self, api_key_client, workspace, project_a, create_user):
        other_workspace = Workspace.objects.create(name="Other Workspace", owner=create_user, slug="other-ws-mods")
        from plane.db.models import WorkspaceMember

        WorkspaceMember.objects.create(workspace=other_workspace, member=create_user, role=20)
        other_project = Project.objects.create(
            name="Other Project", identifier="OTP", workspace=other_workspace, created_by=create_user
        )

        Module.objects.create(name="Mine", project=project_a, workspace=workspace)
        Module.objects.create(name="TheirsNotMine", project=other_project, workspace=other_workspace)

        response = api_key_client.get(_get_url(workspace.slug))

        assert response.status_code == status.HTTP_200_OK
        names = {m["name"] for m in response.data["results"]}
        assert names == {"Mine"}
