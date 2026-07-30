# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.app.views import (
    ComplianceApplicabilityEndpoint,
    ComplianceCategoryEndpoint,
    ComplianceGenerateEndpoint,
    ComplianceTemplateEndpoint,
)


urlpatterns = [
    path(
        "workspaces/<str:slug>/compliance-categories/",
        ComplianceCategoryEndpoint.as_view(),
        name="compliance-categories",
    ),
    path(
        "workspaces/<str:slug>/compliance-categories/<uuid:pk>/",
        ComplianceCategoryEndpoint.as_view(),
        name="compliance-categories",
    ),
    path(
        "workspaces/<str:slug>/compliance-templates/",
        ComplianceTemplateEndpoint.as_view(),
        name="compliance-templates",
    ),
    path(
        "workspaces/<str:slug>/compliance-templates/generate/",
        ComplianceGenerateEndpoint.as_view(),
        name="compliance-templates-generate",
    ),
    path(
        "workspaces/<str:slug>/compliance-templates/<uuid:pk>/",
        ComplianceTemplateEndpoint.as_view(),
        name="compliance-templates",
    ),
    path(
        "workspaces/<str:slug>/compliance-templates/<uuid:pk>/applicability/",
        ComplianceApplicabilityEndpoint.as_view(),
        name="compliance-templates-applicability",
    ),
]
