/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

"use client";

import { useState } from "react";
import { observer } from "mobx-react";
import { EUserPermissionsLevel } from "@plane/constants";
import { EUserProjectRoles } from "@plane/types";
import { Header, EHeaderVariant } from "@plane/ui";
import { cn } from "@plane/utils";
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
        <h3 className="text-lg font-medium text-primary">Access denied</h3>
        <p className="text-13 text-tertiary">Only project admins can access the approval queue.</p>
      </div>
    );
  }

  if (!config || !config.is_enabled || !config.pending_approval_state_id || !config.approved_state_id) {
    return (
      <div className="flex h-full w-full flex-col items-center justify-center gap-2 text-center">
        <h3 className="text-lg font-medium text-primary">Approval gate not configured</h3>
        <p className="text-13 text-tertiary">
          Turn on the approval gate in project settings &rarr; Automations, with a Pending Approval and an Approved
          state, to use this feature.
        </p>
      </div>
    );
  }

  const approvalTabs: { key: "queue" | "records"; label: string }[] = [
    { key: "queue", label: "Pending Approval" },
    { key: "records", label: "Sign-Off Register" },
  ];

  return (
    <>
      <PageHead title={pageTitle} />
      <div className="relative flex h-full w-full flex-col overflow-hidden">
        <Header variant={EHeaderVariant.SECONDARY}>
          <Header.LeftItem>
            <div className="relative flex h-full items-center">
              {approvalTabs.map((tab) => (
                <button key={tab.key} onClick={() => setActiveTab(tab.key)} className="flex h-full flex-col">
                  <div
                    className={cn(`flex flex-1 items-center justify-center px-4 text-13 font-medium transition-all`, {
                      "text-accent-primary": tab.key === activeTab,
                    })}
                  >
                    {tab.label}
                  </div>
                  <div
                    className={cn(`w-full rounded-t border-t-2 border-transparent transition-all`, {
                      "border-accent-strong": tab.key === activeTab,
                    })}
                  />
                </button>
              ))}
            </div>
          </Header.LeftItem>
        </Header>

        <div className="h-full w-full overflow-hidden">
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
