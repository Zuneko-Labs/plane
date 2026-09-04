/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

"use client";

import { useState } from "react";
import { observer } from "mobx-react";
import { ShieldCheck } from "lucide-react";
import { EUserPermissionsLevel } from "@plane/constants";
import { EUserProjectRoles } from "@plane/types";
import { PageHead } from "@/components/core/page-title";
import { ApprovalQueueTable } from "@/components/approvals/approval-queue-table";
import { ApprovalRecordsTable } from "@/components/approvals/approval-records-table";
import { useProject } from "@/hooks/store/use-project";
import { useUserPermissions } from "@/hooks/store/user";
import { useApprovalGateConfig } from "@/hooks/use-approval-gate-config";

interface PageParams {
  workspaceSlug: string;
  projectId: string;
}

function ApprovalQueuePage({ params }: { params: PageParams }) {
  const { workspaceSlug, projectId } = params;
  const { getProjectById } = useProject();
  const { allowPermissions } = useUserPermissions();
  const { config } = useApprovalGateConfig(workspaceSlug, projectId);

  const [activeTab, setActiveTab] = useState<"queue" | "records">("queue");

  const project = getProjectById(projectId);
  const pageTitle = project?.name ? `${project?.name} - Approvals` : "Approvals";
  const isAdmin = allowPermissions([EUserProjectRoles.ADMIN], EUserPermissionsLevel.PROJECT);

  if (!isAdmin) {
    return (
      <div className="flex h-full w-full flex-col items-center justify-center gap-2 text-center">
        <h3 className="text-lg font-medium text-custom-text-100">Access denied</h3>
        <p className="text-sm text-custom-text-300">Only project admins can access the approval queue.</p>
      </div>
    );
  }

  if (!config || !config.pending_approval_state_id) {
    return (
      <div className="flex h-full w-full flex-col items-center justify-center gap-2 text-center">
        <h3 className="text-lg font-medium text-custom-text-100">Approval gate not configured</h3>
        <p className="text-sm text-custom-text-300">
          Set up the approval gate in project settings &rarr; Automations to use this feature.
        </p>
      </div>
    );
  }

  return (
    <>
      <PageHead title={pageTitle} />
      <div className="flex h-full flex-col">
        <div className="flex items-center gap-2.5 border-b border-custom-border-200 px-5 py-4">
          <div className="flex h-8 w-8 items-center justify-center rounded-md bg-custom-primary-100/10">
            <ShieldCheck className="h-4 w-4 text-custom-primary-100" strokeWidth={2} />
          </div>
          <div>
            <h2 className="text-base font-semibold text-custom-text-100">Approval Queue</h2>
            <p className="text-xs text-custom-text-300">Review work items awaiting sign-off for this project</p>
          </div>
        </div>

        <div className="flex gap-1 border-b border-custom-border-200 px-5 pt-3">
          <button
            onClick={() => setActiveTab("queue")}
            className={`rounded-t-md px-3 py-2 text-sm font-medium transition-colors ${
              activeTab === "queue"
                ? "border-b-2 border-custom-primary-100 text-custom-primary-100"
                : "border-b-2 border-transparent text-custom-text-300 hover:text-custom-text-100"
            }`}
          >
            Pending Approval
          </button>
          <button
            onClick={() => setActiveTab("records")}
            className={`rounded-t-md px-3 py-2 text-sm font-medium transition-colors ${
              activeTab === "records"
                ? "border-b-2 border-custom-primary-100 text-custom-primary-100"
                : "border-b-2 border-transparent text-custom-text-300 hover:text-custom-text-100"
            }`}
          >
            Sign-Off Register
          </button>
        </div>

        <div className="flex-1 overflow-auto">
          {activeTab === "queue" ? (
            <ApprovalQueueTable
              workspaceSlug={workspaceSlug}
              projectId={projectId}
              pendingStateId={config.pending_approval_state_id}
              approvedStateId={config.approved_state_id}
              sentBackStateId={config.sent_back_state_id}
            />
          ) : (
            <ApprovalRecordsTable workspaceSlug={workspaceSlug} projectId={projectId} />
          )}
        </div>
      </div>
    </>
  );
}

export default observer(ApprovalQueuePage);
