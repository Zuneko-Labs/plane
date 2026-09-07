/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
import useSWR from "swr";
import { observer } from "mobx-react";
import { CheckCircle2 } from "lucide-react";
import { ISSUE_PRIORITIES } from "@plane/constants";
import { DueDatePropertyIcon, PriorityIcon } from "@plane/propel/icons";
import { Tooltip } from "@plane/propel/tooltip";
import { Avatar, AvatarGroup, Button } from "@plane/ui";
import type { TIssue } from "@plane/types";
import { cn, getFileURL, renderFormattedDate, shouldHighlightIssueDueDate } from "@plane/utils";
import { IssueService } from "@/services/issue/issue.service";
import { ApprovalSentBackModal } from "@/components/issues/approval-sent-back-modal";
import { useLabel } from "@/hooks/store/use-label";
import { useMember } from "@/hooks/store/use-member";
import { useModule } from "@/hooks/store/use-module";
import { useProjectState } from "@/hooks/store/use-project-state";

interface IApprovalQueueTableProps {
  workspaceSlug: string;
  projectId: string;
  pendingStateId: string;
  approvedStateId: string;
  sentBackStateId: string | null;
}

const issueService = new IssueService();

interface IApprovalQueueRowProps {
  issue: TIssue;
  itemLink: string;
  isApproving: boolean;
  canSendBack: boolean;
  onApprove: () => void;
  onSendBack: () => void;
}

const ApprovalQueueRow = observer(
  ({ issue, itemLink, isApproving, canSendBack, onApprove, onSendBack }: IApprovalQueueRowProps) => {
    const { getUserDetails } = useMember();
    const { getModuleById } = useModule();
    const { getLabelById } = useLabel();
    const { getStateById } = useProjectState();

    const priorityDetails = ISSUE_PRIORITIES.find((p) => p.key === issue.priority);
    const assignees = (issue.assignee_ids ?? []).map((id) => getUserDetails(id)).filter(Boolean);
    const modules = (issue.module_ids ?? []).map((id) => getModuleById(id)).filter(Boolean);
    const labels = (issue.label_ids ?? []).map((id) => getLabelById(id)).filter(Boolean);
    const isDueDateOverdue = shouldHighlightIssueDueDate(issue.target_date, getStateById(issue.state_id)?.group);

    return (
      <tr className="group">
        {/* work item — sticky first column, mirrors the spreadsheet layout */}
        <td className="left-0 z-[15] h-11 min-w-60 border-r-[0.5px] border-b-[0.5px] border-subtle bg-surface-1 md:sticky">
          <a href={itemLink} className="flex h-full w-full items-center gap-2 px-page-x hover:underline">
            <span className="flex-shrink-0 text-13 text-tertiary">{issue.sequence_id}</span>
            <span className="truncate text-13 text-primary">{issue.name}</span>
          </a>
        </td>
        <td className="h-11 min-w-36 border-r-[0.5px] border-b-[0.5px] border-subtle px-4 text-13">
          {assignees.length > 0 ? (
            <div className="flex items-center gap-1.5">
              <AvatarGroup size="md">
                {assignees.map((user) => (
                  <Avatar key={user?.id} name={user?.display_name} src={getFileURL(user?.avatar_url ?? "")} />
                ))}
              </AvatarGroup>
              <span className="truncate text-secondary">
                {assignees.length === 1 ? assignees[0]?.display_name : `${assignees.length} members`}
              </span>
            </div>
          ) : (
            <span className="text-tertiary">Unassigned</span>
          )}
        </td>
        <td className="h-11 min-w-36 border-r-[0.5px] border-b-[0.5px] border-subtle px-4 text-13">
          <div className="flex items-center gap-1.5">
            <div
              className={cn({
                // highlight just the icon, matching the priority dropdown's treatment
                "rounded-sm border border-priority-urgent p-0.5": issue.priority === "urgent",
              })}
            >
              <PriorityIcon priority={issue.priority} size={12} className="flex-shrink-0" />
            </div>
            <span
              className={cn("truncate", {
                "text-secondary": issue.priority && issue.priority !== "none",
                "text-placeholder": !issue.priority || issue.priority === "none",
              })}
            >
              {priorityDetails?.title ?? "None"}
            </span>
          </div>
        </td>
        <td className="h-11 min-w-36 border-r-[0.5px] border-b-[0.5px] border-subtle px-4 text-13">
          {issue.target_date ? (
            <div
              className={cn("flex items-center gap-1.5", {
                "text-danger-primary": isDueDateOverdue,
              })}
            >
              <DueDatePropertyIcon className="h-3 w-3 flex-shrink-0" />
              <span>{renderFormattedDate(issue.target_date)}</span>
            </div>
          ) : (
            <span className="text-tertiary">No due date</span>
          )}
        </td>
        <td className="h-11 min-w-36 border-r-[0.5px] border-b-[0.5px] border-subtle px-4 text-13">
          {modules.length > 0 ? (
            <Tooltip tooltipContent={modules.map((m) => m?.name).join(", ")}>
              <span className="block truncate">
                {modules.length === 1 ? modules[0]?.name : `${modules.length} modules`}
              </span>
            </Tooltip>
          ) : (
            <span className="text-tertiary">No module</span>
          )}
        </td>
        <td className="h-11 min-w-36 border-r-[0.5px] border-b-[0.5px] border-subtle px-4 text-13">
          {labels.length > 0 ? (
            <Tooltip tooltipContent={labels.map((l) => l?.name).join(", ")}>
              <div className="flex items-center gap-1.5">
                {labels.length === 1 ? (
                  <>
                    <span
                      className="h-2 w-2 flex-shrink-0 rounded-full"
                      style={{ backgroundColor: labels[0]?.color ?? "#000000" }}
                    />
                    <span className="truncate">{labels[0]?.name}</span>
                  </>
                ) : (
                  <span>{labels.length} labels</span>
                )}
              </div>
            </Tooltip>
          ) : (
            <span className="text-tertiary">No labels</span>
          )}
        </td>
        <td className="h-11 min-w-36 border-b-[0.5px] border-subtle px-4 text-13">
          <div className="flex items-center justify-end gap-2">
            {canSendBack && (
              <Button size="sm" variant="neutral-primary" onClick={onSendBack}>
                Send back
              </Button>
            )}
            <Button size="sm" variant="primary" loading={isApproving} onClick={onApprove}>
              Approve
            </Button>
          </div>
        </td>
      </tr>
    );
  }
);

export const ApprovalQueueTable = observer(
  ({ workspaceSlug, projectId, pendingStateId, approvedStateId, sentBackStateId }: IApprovalQueueTableProps) => {
    const [issues, setIssues] = useState<TIssue[]>([]);
    const [selectedIssue, setSelectedIssue] = useState<TIssue | null>(null);
    const [approvingId, setApprovingId] = useState<string | null>(null);

    const { data, isLoading } = useSWR(
      workspaceSlug && projectId ? `PENDING_APPROVAL_ISSUES_${workspaceSlug}_${projectId}_${pendingStateId}` : null,
      async () => {
        const response: any = await issueService.getIssuesWithParams(workspaceSlug, projectId, {});
        const flat: TIssue[] = Array.isArray(response) ? response : (response?.results ?? []);
        return flat.filter((issue) => issue.state_id === pendingStateId);
      },
      { refreshInterval: 30000 }
    );

    useEffect(() => {
      if (data) setIssues(data);
    }, [data]);

    const handleApprove = async (issue: TIssue) => {
      setApprovingId(issue.id);
      try {
        await issueService.patchIssue(workspaceSlug, projectId, issue.id, { state_id: approvedStateId });
        setIssues((prev) => prev.filter((i) => i.id !== issue.id));
      } catch (error) {
        console.error("Failed to approve:", error);
      } finally {
        setApprovingId(null);
      }
    };

    const handleSentBackSubmit = async (commentHtml: string) => {
      if (!selectedIssue || !sentBackStateId) return;
      await issueService.patchIssue(workspaceSlug, projectId, selectedIssue.id, {
        state_id: sentBackStateId,
        approval_comment_html: commentHtml,
      } as Partial<TIssue>);
      setIssues((prev) => prev.filter((i) => i.id !== selectedIssue.id));
      setSelectedIssue(null);
    };

    if (isLoading) {
      return (
        <div className="flex h-full items-center justify-center text-13 text-tertiary">
          Loading approval queue&hellip;
        </div>
      );
    }

    if (issues.length === 0) {
      return (
        <div className="flex h-full flex-col items-center justify-center gap-3 py-16 text-center">
          <div className="flex h-14 w-14 items-center justify-center rounded-full bg-layer-1">
            <CheckCircle2 className="h-6 w-6 text-tertiary" strokeWidth={1.5} />
          </div>
          <div>
            <h3 className="text-base font-medium text-primary">No pending approvals</h3>
            <p className="mt-1 text-13 text-tertiary">All work items have been reviewed. Nice and tidy.</p>
          </div>
        </div>
      );
    }

    return (
      <>
        <div className="vertical-scrollbar horizontal-scrollbar scrollbar-lg h-full w-full overflow-auto">
          <table className="w-full overflow-y-auto bg-surface-1">
            <thead className="sticky top-0 left-0 z-[12] border-b-[0.5px] border-subtle">
              <tr>
                <th className="left-0 z-[15] h-11 min-w-60 border-r-[0.5px] border-subtle bg-layer-1 text-13 font-medium md:sticky">
                  <div className="flex h-full w-full items-center px-page-x">Work items</div>
                </th>
                <th className="h-11 min-w-36 border border-t-0 border-b-0 border-subtle bg-layer-1 px-4 text-left text-13 font-medium">
                  Assignees
                </th>
                <th className="h-11 min-w-36 border border-t-0 border-b-0 border-subtle bg-layer-1 px-4 text-left text-13 font-medium">
                  Priority
                </th>
                <th className="h-11 min-w-36 border border-t-0 border-b-0 border-subtle bg-layer-1 px-4 text-left text-13 font-medium">
                  Due date
                </th>
                <th className="h-11 min-w-36 border border-t-0 border-b-0 border-subtle bg-layer-1 px-4 text-left text-13 font-medium">
                  Modules
                </th>
                <th className="h-11 min-w-36 border border-t-0 border-b-0 border-subtle bg-layer-1 px-4 text-left text-13 font-medium">
                  Labels
                </th>
                <th className="h-11 min-w-36 border border-t-0 border-b-0 border-subtle bg-layer-1 px-4 text-right text-13 font-medium">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody>
              {issues.map((issue) => (
                <ApprovalQueueRow
                  key={issue.id}
                  issue={issue}
                  itemLink={`/${workspaceSlug}/projects/${projectId}/issues/${issue.id}`}
                  isApproving={approvingId === issue.id}
                  canSendBack={!!sentBackStateId}
                  onApprove={() => handleApprove(issue)}
                  onSendBack={() => setSelectedIssue(issue)}
                />
              ))}
            </tbody>
          </table>
        </div>

        <ApprovalSentBackModal
          isOpen={!!selectedIssue}
          handleClose={() => setSelectedIssue(null)}
          onSubmit={handleSentBackSubmit}
        />
      </>
    );
  }
);
