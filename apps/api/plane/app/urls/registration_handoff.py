# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.app.views import RegistrationHandoffConfigViewSet

urlpatterns = [
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/registration-handoff-config/",
        RegistrationHandoffConfigViewSet.as_view({"get": "list", "post": "create"}),
        name="registration-handoff-config",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/registration-handoff-config/<uuid:pk>/",
        RegistrationHandoffConfigViewSet.as_view({"patch": "partial_update", "delete": "destroy"}),
        name="registration-handoff-config",
    ),
]
