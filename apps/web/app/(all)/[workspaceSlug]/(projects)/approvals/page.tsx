/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import useSWR from "swr";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
import { Header, EHeaderVariant } from "@plane/ui";
import { cn } from "@plane/utils";
import { ApprovalQueueTable, ApprovalRecordsTable, ReopenRequestsTable } from "@/components/approvals";
import { PageHead } from "@/components/core/page-title";
import { useIsApproverInAnyProject } from "@/hooks/use-is-approver";
import approvalGateService, {
  workspacePendingApprovalsSWRKey,
  workspaceReopenRequestsSWRKey,
} from "@/services/approval-gate.service";

type TApprovalTab = "queue" | "reopen" | "records";

/**
 * One approvals page for the whole workspace: every work item waiting on the
 * user across all the projects they approve for (project Admin), requests to
 * reopen approved work items, and the sign-off register.
 */
function WorkspaceApprovalsPage() {
  const { workspaceSlug: routeWorkspaceSlug } = useParams();
  const workspaceSlug = routeWorkspaceSlug?.toString() ?? "";
  const isApprover = useIsApproverInAnyProject(workspaceSlug);
  const [activeTab, setActiveTab] = useState<TApprovalTab>("queue");

  // same keys as the tables, so the tab counts stay in step with them
  const { data: pending } = useSWR(
    workspaceSlug && isApprover ? workspacePendingApprovalsSWRKey(workspaceSlug) : null,
    () => approvalGateService.fetchWorkspacePendingApprovals(workspaceSlug),
    { refreshInterval: 30000 }
  );
  const { data: reopenRequests } = useSWR(
    workspaceSlug && isApprover ? workspaceReopenRequestsSWRKey(workspaceSlug, "pending") : null,
    () => approvalGateService.fetchWorkspaceReopenRequests(workspaceSlug, "pending"),
    { refreshInterval: 30000 }
  );

  if (!isApprover) {
    return (
      <>
        <PageHead title="Approvals" />
        <div className="flex h-full w-full flex-col items-center justify-center gap-2 text-center">
          <h3 className="text-lg font-medium text-primary">No approvals for you</h3>
          <p className="text-13 text-tertiary">Only project admins approve work items.</p>
        </div>
      </>
    );
  }

  const tabs: { key: TApprovalTab; label: string; count?: number }[] = [
    { key: "queue", label: "Pending Approval", count: pending?.length },
    { key: "reopen", label: "Reopen Requests", count: reopenRequests?.length },
    { key: "records", label: "Sign-Off Register" },
  ];

  return (
    <>
      <PageHead title="Approvals" />
      <div className="relative flex h-full w-full flex-col overflow-hidden">
        <Header variant={EHeaderVariant.SECONDARY}>
          <Header.LeftItem>
            <div className="relative flex h-full items-center">
              {tabs.map((tab) => (
                <button
                  key={tab.key}
                  type="button"
                  onClick={() => setActiveTab(tab.key)}
                  className="flex h-full flex-col"
                >
                  <div
                    className={cn("flex flex-1 items-center justify-center gap-1.5 px-4 text-13 font-medium", {
                      "text-accent-primary": tab.key === activeTab,
                    })}
                  >
                    {tab.label}
                    {!!tab.count && (
                      <span className="rounded-full bg-layer-1 px-1.5 text-11 text-secondary">{tab.count}</span>
                    )}
                  </div>
                  <div
                    className={cn("w-full rounded-t border-t-2 border-transparent transition-all", {
                      "border-accent-strong": tab.key === activeTab,
                    })}
                  />
                </button>
              ))}
            </div>
          </Header.LeftItem>
        </Header>

        <div className="h-full w-full overflow-hidden">
          {activeTab === "queue" && <ApprovalQueueTable workspaceSlug={workspaceSlug} />}
          {activeTab === "reopen" && <ReopenRequestsTable workspaceSlug={workspaceSlug} />}
          {activeTab === "records" && <ApprovalRecordsTable workspaceSlug={workspaceSlug} />}
        </div>
      </div>
    </>
  );
}

export default observer(WorkspaceApprovalsPage);
