# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.app.views import ApprovalGateConfigViewSet, ApprovalRecordListEndpoint

urlpatterns = [
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/approval-gate-config/",
        ApprovalGateConfigViewSet.as_view({"get": "list", "post": "create"}),
        name="approval-gate-config",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/approval-gate-config/<uuid:pk>/",
        ApprovalGateConfigViewSet.as_view({"patch": "partial_update", "delete": "destroy"}),
        name="approval-gate-config",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/approval-records/",
        ApprovalRecordListEndpoint.as_view(),
        name="approval-records",
    ),
]
