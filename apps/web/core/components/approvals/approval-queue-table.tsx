/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
import useSWR from "swr";
import { observer } from "mobx-react";
import { CheckCircle2, Inbox } from "lucide-react";
import { PriorityIcon } from "@plane/propel/icons";
import { Avatar, AvatarGroup, Button } from "@plane/ui";
import type { TIssue } from "@plane/types";
import { IssueService } from "@/services/issue/issue.service";
import { ApprovalSentBackModal } from "@/components/issues/approval-sent-back-modal";
import { useMember } from "@/hooks/store/use-member";

interface IApprovalQueueTableProps {
  workspaceSlug: string;
  projectId: string;
  pendingStateId: string;
  approvedStateId: string;
  sentBackStateId: string | null;
}

const issueService = new IssueService();

export const ApprovalQueueTable = observer(
  ({ workspaceSlug, projectId, pendingStateId, approvedStateId, sentBackStateId }: IApprovalQueueTableProps) => {
    const { getUserDetails } = useMember();
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
        <div className="flex h-full items-center justify-center text-sm text-custom-text-300">
          Loading approval queue&hellip;
        </div>
      );
    }

    if (issues.length === 0) {
      return (
        <div className="flex h-full flex-col items-center justify-center gap-3 py-16 text-center">
          <div className="flex h-14 w-14 items-center justify-center rounded-full bg-custom-background-80">
            <CheckCircle2 className="h-6 w-6 text-custom-text-300" strokeWidth={1.5} />
          </div>
          <div>
            <h3 className="text-base font-medium text-custom-text-100">No pending approvals</h3>
            <p className="mt-1 text-sm text-custom-text-300">All work items have been reviewed. Nice and tidy.</p>
          </div>
        </div>
      );
    }

    return (
      <>
        <div className="overflow-x-auto px-4 py-3">
          <table className="w-full border-separate border-spacing-y-1.5">
            <thead>
              <tr className="text-xs font-medium uppercase tracking-wide text-custom-text-300">
                <th className="px-3 pb-2 text-left">Work item</th>
                <th className="px-3 pb-2 text-left">Assignees</th>
                <th className="px-3 pb-2 text-left">Priority</th>
                <th className="px-3 pb-2 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {issues.map((issue) => (
                <tr key={issue.id} className="group rounded-md bg-custom-background-100 shadow-sm">
                  <td className="rounded-l-md border border-r-0 border-custom-border-200 px-3 py-3">
                    <a
                      href={`/${workspaceSlug}/projects/${projectId}/issues/${issue.id}`}
                      className="flex flex-col gap-0.5 hover:underline"
                    >
                      <span className="text-xs text-custom-text-300">#{issue.sequence_id}</span>
                      <span className="text-sm font-medium text-custom-text-100">{issue.name}</span>
                    </a>
                  </td>
                  <td className="border-y border-custom-border-200 px-3 py-3">
                    {issue.assignee_ids?.length ? (
                      <AvatarGroup size="md">
                        {issue.assignee_ids.map((id) => {
                          const user = getUserDetails(id);
                          return <Avatar key={id} name={user?.display_name} src={user?.avatar_url} />;
                        })}
                      </AvatarGroup>
                    ) : (
                      <span className="text-sm text-custom-text-300">Unassigned</span>
                    )}
                  </td>
                  <td className="border-y border-custom-border-200 px-3 py-3">
                    <PriorityIcon priority={issue.priority} withContainer size={12} />
                  </td>
                  <td className="rounded-r-md border border-l-0 border-custom-border-200 px-3 py-3">
                    <div className="flex justify-end gap-2">
                      {sentBackStateId && (
                        <Button size="sm" variant="neutral-primary" onClick={() => setSelectedIssue(issue)}>
                          Send back
                        </Button>
                      )}
                      <Button
                        size="sm"
                        variant="primary"
                        loading={approvingId === issue.id}
                        onClick={() => handleApprove(issue)}
                      >
                        Approve
                      </Button>
                    </div>
                  </td>
                </tr>
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
