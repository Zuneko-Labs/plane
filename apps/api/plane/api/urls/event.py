# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.api.views import WorkspaceEventsAPIEndpoint, WorkspaceEventsCheckpointAPIEndpoint

urlpatterns = [
    path(
        "workspaces/<str:slug>/events/checkpoint/",
        WorkspaceEventsCheckpointAPIEndpoint.as_view(http_method_names=["get"]),
        name="workspace-events-checkpoint",
    ),
    path(
        "workspaces/<str:slug>/events/",
        WorkspaceEventsAPIEndpoint.as_view(http_method_names=["get"]),
        name="workspace-events",
    ),
]
