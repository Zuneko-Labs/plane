# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.app.views import (
    ApprovalGateConfigViewSet,
    ApprovalRecordListEndpoint,
    IssueReopenRequestEndpoint,
    WorkspaceApprovalRecordEndpoint,
    WorkspacePendingApprovalEndpoint,
    WorkspaceReopenRequestDecisionEndpoint,
    WorkspaceReopenRequestEndpoint,
)

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
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/issues/<uuid:issue_id>/reopen-requests/",
        IssueReopenRequestEndpoint.as_view(),
        name="issue-reopen-requests",
    ),
    # workspace-wide approvals page (every project the user approves for)
    path(
        "workspaces/<str:slug>/approvals/pending/",
        WorkspacePendingApprovalEndpoint.as_view(),
        name="workspace-pending-approvals",
    ),
    path(
        "workspaces/<str:slug>/approvals/records/",
        WorkspaceApprovalRecordEndpoint.as_view(),
        name="workspace-approval-records",
    ),
    path(
        "workspaces/<str:slug>/approvals/reopen-requests/",
        WorkspaceReopenRequestEndpoint.as_view(),
        name="workspace-reopen-requests",
    ),
    path(
        "workspaces/<str:slug>/approvals/reopen-requests/<uuid:pk>/decision/",
        WorkspaceReopenRequestDecisionEndpoint.as_view(),
        name="workspace-reopen-request-decision",
    ),
]
