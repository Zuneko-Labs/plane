/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { Fragment, useState } from "react";
import useSWR from "swr";
import { observer } from "mobx-react";
import { CheckCircle2, History, RotateCcw } from "lucide-react";
import { cn } from "@plane/utils";
import approvalGateService from "@/services/approval-gate.service";

interface IApprovalRecordsTableProps {
  workspaceSlug: string;
  projectId: string;
}

const formatDate = (dateString: string) =>
  new Date(dateString).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });

export const ApprovalRecordsTable = observer(({ workspaceSlug, projectId }: IApprovalRecordsTableProps) => {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const { data: records, isLoading } = useSWR(
    workspaceSlug && projectId ? `APPROVAL_RECORDS_${workspaceSlug}_${projectId}` : null,
    () => approvalGateService.fetchRecords(workspaceSlug, projectId)
  );

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center text-13 text-tertiary">
        Loading sign-off register&hellip;
      </div>
    );
  }

  if (!records || records.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 py-16 text-center">
        <div className="flex h-14 w-14 items-center justify-center rounded-full bg-layer-1">
          <History className="h-6 w-6 text-tertiary" strokeWidth={1.5} />
        </div>
        <div>
          <h3 className="text-base font-medium text-primary">No sign-offs yet</h3>
          <p className="mt-1 text-13 text-tertiary">Approved or sent-back work items will show up here.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="vertical-scrollbar horizontal-scrollbar scrollbar-lg h-full w-full overflow-auto">
      <table className="w-full overflow-y-auto bg-surface-1">
        <thead className="sticky top-0 left-0 z-[12] border-b-[0.5px] border-subtle">
          <tr>
            <th className="left-0 z-[15] h-11 min-w-60 border-r-[0.5px] border-subtle bg-layer-1 text-13 font-medium md:sticky">
              <div className="flex h-full w-full items-center px-page-x">Work items</div>
            </th>
            <th className="h-11 min-w-36 border border-t-0 border-b-0 border-subtle bg-layer-1 px-4 text-left text-13 font-medium">
              Decision
            </th>
            <th className="h-11 min-w-36 border border-t-0 border-b-0 border-subtle bg-layer-1 px-4 text-left text-13 font-medium">
              Signed off by
            </th>
            <th className="h-11 min-w-36 border border-t-0 border-b-0 border-subtle bg-layer-1 px-4 text-right text-13 font-medium">
              Comment
            </th>
          </tr>
        </thead>
        <tbody>
          {records.map((record) => {
            const isApproved = record.decision === "approved";
            const isExpanded = expandedId === record.id;
            return (
              <Fragment key={record.id}>
                <tr className="group">
                  <td className="left-0 z-[15] h-11 min-w-60 border-r-[0.5px] border-b-[0.5px] border-subtle bg-surface-1 md:sticky">
                    <div className="flex h-full w-full items-center gap-2 px-page-x">
                      <span className="flex-shrink-0 text-13 text-tertiary">#{record.issue_sequence_id}</span>
                      <span className="truncate text-13 text-primary">{record.issue_name}</span>
                    </div>
                  </td>
                  <td className="h-11 min-w-36 border-r-[0.5px] border-b-[0.5px] border-subtle px-4 text-13">
                    <span
                      className={cn("inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-13 font-medium", {
                        "bg-success-subtle text-success-primary": isApproved,
                        "bg-warning-subtle text-warning-primary": !isApproved,
                      })}
                    >
                      {isApproved ? <CheckCircle2 className="h-3.5 w-3.5" /> : <RotateCcw className="h-3.5 w-3.5" />}
                      {isApproved ? "Approved" : "Sent back"}
                    </span>
                  </td>
                  <td className="h-11 min-w-36 border-r-[0.5px] border-b-[0.5px] border-subtle px-4 text-13 text-tertiary">
                    {record.actor_email} &middot; {formatDate(record.created_at)}
                  </td>
                  <td className="h-11 min-w-36 border-b-[0.5px] border-subtle px-4 text-right text-13">
                    {record.comment && (
                      <button
                        onClick={() => setExpandedId(isExpanded ? null : record.id)}
                        className="text-13 font-medium text-accent-primary hover:underline"
                      >
                        {isExpanded ? "Hide comment" : "View comment"}
                      </button>
                    )}
                  </td>
                </tr>
                {record.comment && isExpanded && (
                  <tr>
                    <td colSpan={4} className="border-b-[0.5px] border-subtle px-page-x py-3">
                      <div
                        className="rounded-md bg-layer-1 px-3 py-2 text-13 text-secondary"
                        dangerouslySetInnerHTML={{ __html: record.comment }}
                      />
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
