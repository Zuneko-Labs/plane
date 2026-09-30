/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { Fragment, useState } from "react";
import useSWR from "swr";
import { observer } from "mobx-react";
import { CheckCircle2, History, RotateCcw, Undo2 } from "lucide-react";
import { cn } from "@plane/utils";
import { htmlToPlainText } from "@/hooks/use-work-item-state-transition";
import type { TApprovalDecision } from "@/services/approval-gate.service";
import approvalGateService, { workspaceApprovalRecordsSWRKey } from "@/services/approval-gate.service";
import {
  ApprovalEmptyState,
  ApprovalLoadingState,
  formatApprovalDate,
  ModulesCell,
  ProjectCell,
  TD_CLASS,
  TH_CLASS,
  WorkItemCell,
  WorkItemHeaderCell,
  workItemLink,
} from "./approval-table-cells";

type Props = {
  workspaceSlug: string;
};

const DECISION_DETAILS: Record<TApprovalDecision, { label: string; icon: typeof CheckCircle2; className: string }> = {
  approved: { label: "Approved", icon: CheckCircle2, className: "bg-success-subtle text-success-primary" },
  sent_back: { label: "Sent back", icon: RotateCcw, className: "bg-warning-subtle text-warning-primary" },
  reopened: { label: "Reopened", icon: Undo2, className: "bg-danger-subtle text-danger-primary" },
};

/** The sign-off register of every project the user approves for. */
export const ApprovalRecordsTable = observer(function ApprovalRecordsTable({ workspaceSlug }: Props) {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const { data: records, isLoading } = useSWR(
    workspaceSlug ? workspaceApprovalRecordsSWRKey(workspaceSlug) : null,
    () => approvalGateService.fetchWorkspaceApprovalRecords(workspaceSlug)
  );

  if (isLoading) return <ApprovalLoadingState label="Loading sign-off register" />;

  if (!records || records.length === 0)
    return (
      <ApprovalEmptyState
        icon={<History className="h-6 w-6 text-tertiary" strokeWidth={1.5} />}
        title="No sign-offs yet"
        description="Approved, sent-back and reopened work items will show up here."
      />
    );

  return (
    <div className="vertical-scrollbar horizontal-scrollbar scrollbar-lg h-full w-full overflow-auto">
      <table className="w-full overflow-y-auto bg-surface-1">
        <thead className="sticky top-0 left-0 z-[12] border-b-[0.5px] border-subtle">
          <tr>
            <WorkItemHeaderCell />
            <th className={TH_CLASS}>Project</th>
            <th className={TH_CLASS}>Module</th>
            <th className={TH_CLASS}>Decision</th>
            <th className={TH_CLASS}>Signed off by</th>
            <th className={cn(TH_CLASS, "text-right")}>Comment</th>
          </tr>
        </thead>
        <tbody>
          {records.map((record) => {
            const decision = DECISION_DETAILS[record.decision] ?? DECISION_DETAILS.approved;
            const DecisionIcon = decision.icon;
            const isExpanded = expandedId === record.id;
            // comments are stored as HTML - show them as text only
            const comment = record.comment ? htmlToPlainText(record.comment) : "";
            return (
              <Fragment key={record.id}>
                <tr className="group">
                  <WorkItemCell
                    href={workItemLink(workspaceSlug, record.project, record.issue)}
                    projectIdentifier={record.project_identifier}
                    sequenceId={record.issue_sequence_id}
                    name={record.issue_name}
                  />
                  <ProjectCell name={record.project_name} />
                  <ModulesCell modules={record.modules} />
                  <td className={TD_CLASS}>
                    <span
                      className={cn(
                        "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-13 font-medium",
                        decision.className
                      )}
                    >
                      <DecisionIcon className="h-3.5 w-3.5" />
                      {decision.label}
                    </span>
                  </td>
                  <td className={cn(TD_CLASS, "text-tertiary")}>
                    {record.actor_name ?? record.actor_email} &middot; {formatApprovalDate(record.created_at)}
                  </td>
                  <td className="h-11 min-w-36 border-b-[0.5px] border-subtle px-4 text-right text-13">
                    {comment && (
                      <button
                        type="button"
                        onClick={() => setExpandedId(isExpanded ? null : record.id)}
                        className="text-13 font-medium text-accent-primary hover:underline"
                      >
                        {isExpanded ? "Hide comment" : "View comment"}
                      </button>
                    )}
                  </td>
                </tr>
                {comment && isExpanded && (
                  <tr>
                    <td colSpan={6} className="border-b-[0.5px] border-subtle px-page-x py-3">
                      <div className="rounded-md bg-layer-1 px-3 py-2 text-13 whitespace-pre-wrap text-secondary">
                        {comment}
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
});
