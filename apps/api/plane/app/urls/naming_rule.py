# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.app.views import WorkItemNamingRuleViewSet

urlpatterns = [
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/naming-rules/",
        WorkItemNamingRuleViewSet.as_view({"get": "list", "post": "create"}),
        name="work-item-naming-rules",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/naming-rules/<uuid:pk>/",
        WorkItemNamingRuleViewSet.as_view({"patch": "partial_update", "delete": "destroy"}),
        name="work-item-naming-rules",
    ),
]
