/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import useSWR from "swr";
import { observer } from "mobx-react";
import { CheckCircle2 } from "lucide-react";
import { ISSUE_PRIORITIES } from "@plane/constants";
import { DueDatePropertyIcon, PriorityIcon } from "@plane/propel/icons";
import { setToast, TOAST_TYPE } from "@plane/propel/toast";
import { Tooltip } from "@plane/propel/tooltip";
import type { TIssue } from "@plane/types";
import { Avatar, AvatarGroup, Button } from "@plane/ui";
import { cn, getFileURL, renderFormattedDate } from "@plane/utils";
import { ApprovalSentBackModal } from "@/components/issues/approval-sent-back-modal";
import { useMember } from "@/hooks/store/use-member";
import { REGISTRATION_AGENT_REQUIRED } from "@/hooks/use-registration-handoff-config";
import type { TWorkspacePendingApproval } from "@/services/approval-gate.service";
import approvalGateService, { workspacePendingApprovalsSWRKey } from "@/services/approval-gate.service";
import { IssueService } from "@/services/issue/issue.service";
import {
  ApprovalEmptyState,
  ApprovalLoadingState,
  ModulesCell,
  ProjectCell,
  TD_CLASS,
  TH_CLASS,
  WorkItemCell,
  WorkItemHeaderCell,
  workItemLink,
} from "./approval-table-cells";
import { ProjectRegistrarModal } from "./project-registrar-modal";

const issueService = new IssueService();

type Props = {
  workspaceSlug: string;
};

const ApprovalQueueRow = observer(function ApprovalQueueRow(props: {
  workspaceSlug: string;
  item: TWorkspacePendingApproval;
  isApproving: boolean;
  onApprove: () => void;
  onSendBack: () => void;
}) {
  const { workspaceSlug, item, isApproving, onApprove, onSendBack } = props;
  const { getUserDetails } = useMember();

  const priorityDetails = ISSUE_PRIORITIES.find((p) => p.key === item.priority);
  const assignees = item.assignee_ids.map((id) => getUserDetails(id)).filter(Boolean);
  const isOverdue = !!item.target_date && new Date(item.target_date) < new Date(new Date().toDateString());

  return (
    <tr className="group">
      <WorkItemCell
        href={workItemLink(workspaceSlug, item.project_id, item.id)}
        projectIdentifier={item.project_identifier}
        sequenceId={item.sequence_id}
        name={item.name}
      />
      <ProjectCell name={item.project_name} />
      <ModulesCell modules={item.modules} />
      <td className={TD_CLASS}>
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
      <td className={TD_CLASS}>
        <div className="flex items-center gap-1.5">
          <div className={cn({ "rounded-sm border border-priority-urgent p-0.5": item.priority === "urgent" })}>
            <PriorityIcon priority={item.priority ?? "none"} size={12} className="flex-shrink-0" />
          </div>
          <span
            className={cn("truncate", {
              "text-secondary": item.priority && item.priority !== "none",
              "text-placeholder": !item.priority || item.priority === "none",
            })}
          >
            {priorityDetails?.title ?? "None"}
          </span>
        </div>
      </td>
      <td className={TD_CLASS}>
        {item.target_date ? (
          <div className={cn("flex items-center gap-1.5", { "text-danger-primary": isOverdue })}>
            <DueDatePropertyIcon className="h-3 w-3 flex-shrink-0" />
            <span>{renderFormattedDate(item.target_date)}</span>
          </div>
        ) : (
          <span className="text-tertiary">No due date</span>
        )}
      </td>
      <td className={TD_CLASS}>
        {item.labels.length > 0 ? (
          <Tooltip tooltipContent={item.labels.map((label) => label.name).join(", ")}>
            <div className="flex items-center gap-1.5">
              {item.labels.length === 1 ? (
                <>
                  <span
                    className="h-2 w-2 flex-shrink-0 rounded-full"
                    style={{ backgroundColor: item.labels[0].color ?? "#000000" }}
                  />
                  <span className="truncate">{item.labels[0].name}</span>
                </>
              ) : (
                <span>{item.labels.length} labels</span>
              )}
            </div>
          </Tooltip>
        ) : (
          <span className="text-tertiary">No labels</span>
        )}
      </td>
      <td className="h-11 min-w-36 border-b-[0.5px] border-subtle px-4 text-13">
        <div className="flex items-center justify-end gap-2">
          {item.sent_back_state_id && (
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
});

/**
 * Every work item waiting in Pending Approval across the projects the user
 * approves for. The server returns only those projects, and enforces the
 * approver rule on every move regardless.
 */
export const ApprovalQueueTable = observer(function ApprovalQueueTable({ workspaceSlug }: Props) {
  const [sendBackItem, setSendBackItem] = useState<TWorkspacePendingApproval | null>(null);
  const [registrarItem, setRegistrarItem] = useState<TWorkspacePendingApproval | null>(null);
  const [approvingId, setApprovingId] = useState<string | null>(null);

  const { data, isLoading, mutate } = useSWR(
    workspaceSlug ? workspacePendingApprovalsSWRKey(workspaceSlug) : null,
    () => approvalGateService.fetchWorkspacePendingApprovals(workspaceSlug),
    { refreshInterval: 30000 }
  );
  const items = data ?? [];

  const removeItem = (id: string) =>
    mutate((current) => (current ?? []).filter((item) => item.id !== id), { revalidate: false });

  const approve = async (item: TWorkspacePendingApproval, registrationAgentId?: string) => {
    const payload: Partial<TIssue> & { registration_agent_id?: string } = { state_id: item.approved_state_id };
    if (registrationAgentId) {
      // Not TIssue fields - the server reads them off the raw request body
      payload.registration_agent_id = registrationAgentId;
      payload.assignee_ids = Array.from(new Set([...item.assignee_ids, registrationAgentId]));
    }
    await issueService.patchIssue(workspaceSlug, item.project_id, item.id, payload as Partial<TIssue>);
    await removeItem(item.id);
    setToast({ type: TOAST_TYPE.SUCCESS, title: "Approved", message: `"${item.name}" was approved.` });
  };

  const handleApprove = async (item: TWorkspacePendingApproval) => {
    setApprovingId(item.id);
    try {
      await approve(item);
    } catch (error: any) {
      // registration was skipped on the way here - name a registrar first
      if (error?.error_code === REGISTRATION_AGENT_REQUIRED) {
        setRegistrarItem(item);
        return;
      }
      setToast({
        type: TOAST_TYPE.ERROR,
        title: "Couldn't approve",
        message: error?.error ?? "The work item could not be approved. Please try again.",
      });
    } finally {
      setApprovingId(null);
    }
  };

  const handleSentBackSubmit = async (commentHtml: string) => {
    if (!sendBackItem?.sent_back_state_id) return;
    await issueService.patchIssue(workspaceSlug, sendBackItem.project_id, sendBackItem.id, {
      state_id: sendBackItem.sent_back_state_id,
      approval_comment_html: commentHtml,
    } as Partial<TIssue>);
    await removeItem(sendBackItem.id);
    setSendBackItem(null);
  };

  if (isLoading) return <ApprovalLoadingState label="Loading approval queue" />;

  if (items.length === 0)
    return (
      <ApprovalEmptyState
        icon={<CheckCircle2 className="h-6 w-6 text-tertiary" strokeWidth={1.5} />}
        title="No pending approvals"
        description="Nothing is waiting on you in any of your projects."
      />
    );

  return (
    <>
      <div className="vertical-scrollbar horizontal-scrollbar scrollbar-lg h-full w-full overflow-auto">
        <table className="w-full overflow-y-auto bg-surface-1">
          <thead className="sticky top-0 left-0 z-[12] border-b-[0.5px] border-subtle">
            <tr>
              <WorkItemHeaderCell />
              <th className={TH_CLASS}>Project</th>
              <th className={TH_CLASS}>Module</th>
              <th className={TH_CLASS}>Assignees</th>
              <th className={TH_CLASS}>Priority</th>
              <th className={TH_CLASS}>Due date</th>
              <th className={TH_CLASS}>Labels</th>
              <th className={cn(TH_CLASS, "text-right")}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <ApprovalQueueRow
                key={item.id}
                workspaceSlug={workspaceSlug}
                item={item}
                isApproving={approvingId === item.id}
                onApprove={() => handleApprove(item)}
                onSendBack={() => setSendBackItem(item)}
              />
            ))}
          </tbody>
        </table>
      </div>

      <ApprovalSentBackModal
        isOpen={!!sendBackItem}
        handleClose={() => setSendBackItem(null)}
        onSubmit={handleSentBackSubmit}
      />
      <ProjectRegistrarModal
        workspaceSlug={workspaceSlug}
        projectId={registrarItem?.project_id ?? null}
        handleClose={() => setRegistrarItem(null)}
        onSubmit={async (agentId) => {
          if (!registrarItem) return;
          await approve(registrarItem, agentId);
          setRegistrarItem(null);
        }}
      />
    </>
  );
});
