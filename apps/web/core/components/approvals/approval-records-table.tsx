/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import useSWR from "swr";
import { observer } from "mobx-react";
import { CheckCircle2, History, RotateCcw } from "lucide-react";
import approvalGateService from "@/services/approval-gate.service";

interface IApprovalRecordsTableProps {
  workspaceSlug: string;
  projectId: string;
}

export const ApprovalRecordsTable = observer(({ workspaceSlug, projectId }: IApprovalRecordsTableProps) => {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const { data: records, isLoading } = useSWR(
    workspaceSlug && projectId ? `APPROVAL_RECORDS_${workspaceSlug}_${projectId}` : null,
    () => approvalGateService.fetchRecords(workspaceSlug, projectId)
  );

  const formatDate = (dateString: string) =>
    new Date(dateString).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-custom-text-300">
        Loading sign-off register&hellip;
      </div>
    );
  }

  if (!records || records.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 py-16 text-center">
        <div className="flex h-14 w-14 items-center justify-center rounded-full bg-custom-background-80">
          <History className="h-6 w-6 text-custom-text-300" strokeWidth={1.5} />
        </div>
        <div>
          <h3 className="text-base font-medium text-custom-text-100">No sign-offs yet</h3>
          <p className="mt-1 text-sm text-custom-text-300">Approved or sent-back work items will show up here.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2 px-4 py-3">
      {records.map((record) => {
        const isApproved = record.decision === "approved";
        return (
          <div
            key={record.id}
            className="flex flex-col gap-2 rounded-md border border-custom-border-200 bg-custom-background-100 px-4 py-3"
          >
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2.5">
                <span
                  className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full ${
                    isApproved ? "bg-green-500/10 text-green-600" : "bg-amber-500/10 text-amber-600"
                  }`}
                >
                  {isApproved ? <CheckCircle2 className="h-3.5 w-3.5" /> : <RotateCcw className="h-3.5 w-3.5" />}
                </span>
                <div>
                  <span className="text-sm font-medium text-custom-text-100">
                    #{record.issue_sequence_id} {record.issue_name}
                  </span>
                  <p className="text-xs text-custom-text-300">
                    {isApproved ? "Approved" : "Sent back"} by {record.actor_email} &middot;{" "}
                    {formatDate(record.created_at)}
                  </p>
                </div>
              </div>
              {record.comment && (
                <button
                  onClick={() => setExpandedId(expandedId === record.id ? null : record.id)}
                  className="shrink-0 text-xs font-medium text-custom-primary-100 hover:underline"
                >
                  {expandedId === record.id ? "Hide comment" : "View comment"}
                </button>
              )}
            </div>
            {record.comment && expandedId === record.id && (
              <div
                className="ml-8 rounded-md bg-custom-background-90 px-3 py-2 text-sm text-custom-text-200"
                dangerouslySetInnerHTML={{ __html: record.comment }}
              />
            )}
          </div>
        );
      })}
    </div>
  );
});
