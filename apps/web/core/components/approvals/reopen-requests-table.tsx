/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { Fragment, useState } from "react";
import useSWR, { mutate as globalMutate } from "swr";
import { observer } from "mobx-react";
import { ArrowRight, RotateCcw } from "lucide-react";
import { setToast, TOAST_TYPE } from "@plane/propel/toast";
import { Button } from "@plane/ui";
import { cn } from "@plane/utils";
import { ApprovalSentBackModal } from "@/components/issues/approval-sent-back-modal";
import { REGISTRATION_AGENT_REQUIRED } from "@/hooks/use-registration-handoff-config";
import { htmlToPlainText } from "@/hooks/use-work-item-state-transition";
import type { TReopenRequest, TReopenRequestStatus } from "@/services/approval-gate.service";
import approvalGateService, {
  workspaceApprovalRecordsSWRKey,
  workspaceReopenRequestsSWRKey,
} from "@/services/approval-gate.service";
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
import { ProjectRegistrarModal } from "./project-registrar-modal";

type Props = {
  workspaceSlug: string;
};

const STATUS_FILTERS: { key: TReopenRequestStatus | "all"; label: string }[] = [
  { key: "pending", label: "Waiting" },
  { key: "all", label: "All" },
];

const StatusBadge = ({ status }: { status: TReopenRequestStatus }) => (
  <span
    className={cn("inline-flex items-center rounded-full px-2 py-0.5 text-13 font-medium", {
      "bg-warning-subtle text-warning-primary": status === "pending",
      "bg-success-subtle text-success-primary": status === "approved",
      "bg-danger-subtle text-danger-primary": status === "rejected",
    })}
  >
    {status === "pending" ? "Waiting" : status === "approved" ? "Accepted" : "Rejected"}
  </span>
);

/**
 * Requests to take an approved work item back to an earlier stage, across
 * the projects the user approves for. Accepting moves the work item (with
 * the reason on record); rejecting leaves it where it is.
 */
export const ReopenRequestsTable = observer(function ReopenRequestsTable({ workspaceSlug }: Props) {
  const [statusFilter, setStatusFilter] = useState<TReopenRequestStatus | "all">("pending");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [decidingId, setDecidingId] = useState<string | null>(null);
  const [rejectRequest, setRejectRequest] = useState<TReopenRequest | null>(null);
  const [registrarRequest, setRegistrarRequest] = useState<TReopenRequest | null>(null);

  const swrKey = workspaceSlug ? workspaceReopenRequestsSWRKey(workspaceSlug, statusFilter) : null;
  const { data, isLoading, mutate } = useSWR(
    swrKey,
    () => approvalGateService.fetchWorkspaceReopenRequests(workspaceSlug, statusFilter),
    { refreshInterval: 30000 }
  );
  const requests = data ?? [];

  const afterDecision = async () => {
    await mutate();
    // the other filter and the sign-off register are stale now too
    await globalMutate(workspaceReopenRequestsSWRKey(workspaceSlug, statusFilter === "all" ? "pending" : "all"));
    await globalMutate(workspaceApprovalRecordsSWRKey(workspaceSlug));
  };

  const accept = async (request: TReopenRequest, registrationAgentId?: string) => {
    await approvalGateService.decideReopenRequest(workspaceSlug, request.id, {
      decision: "approve",
      ...(registrationAgentId ? { registration_agent_id: registrationAgentId } : {}),
    });
    await afterDecision();
    setToast({
      type: TOAST_TYPE.SUCCESS,
      title: "Reopen accepted",
      message: `"${request.issue_name}" was moved back to "${request.to_state_name ?? "the requested state"}".`,
    });
  };

  const handleAccept = async (request: TReopenRequest) => {
    setDecidingId(request.id);
    try {
      await accept(request);
    } catch (error: any) {
      // moving back skips the registration state with no registrar on record
      if (error?.error_code === REGISTRATION_AGENT_REQUIRED) {
        setRegistrarRequest(request);
        return;
      }
      setToast({
        type: TOAST_TYPE.ERROR,
        title: "Couldn't accept",
        message: error?.error ?? "The reopen request could not be accepted. Please try again.",
      });
    } finally {
      setDecidingId(null);
    }
  };

  const handleRejectSubmit = async (commentHtml: string) => {
    if (!rejectRequest) return;
    await approvalGateService.decideReopenRequest(workspaceSlug, rejectRequest.id, {
      decision: "reject",
      comment: htmlToPlainText(commentHtml),
    });
    await afterDecision();
    setRejectRequest(null);
  };

  const filterTabs = (
    <div className="flex items-center gap-1 border-b-[0.5px] border-subtle px-page-x py-2">
      {STATUS_FILTERS.map((filter) => (
        <button
          key={filter.key}
          type="button"
          onClick={() => setStatusFilter(filter.key)}
          className={cn("rounded-sm px-2 py-1 text-13 font-medium text-tertiary hover:bg-layer-1", {
            "bg-layer-1 text-primary": statusFilter === filter.key,
          })}
        >
          {filter.label}
        </button>
      ))}
    </div>
  );

  let content;
  if (isLoading) content = <ApprovalLoadingState label="Loading reopen requests" />;
  else if (requests.length === 0)
    content = (
      <ApprovalEmptyState
        icon={<RotateCcw className="h-6 w-6 text-tertiary" strokeWidth={1.5} />}
        title={statusFilter === "pending" ? "No reopen requests waiting" : "No reopen requests yet"}
        description="Requests to move an approved work item back to an earlier stage show up here."
      />
    );
  else
    content = (
      <div className="vertical-scrollbar horizontal-scrollbar scrollbar-lg h-full w-full overflow-auto">
        <table className="w-full overflow-y-auto bg-surface-1">
          <thead className="sticky top-0 left-0 z-[12] border-b-[0.5px] border-subtle">
            <tr>
              <WorkItemHeaderCell />
              <th className={TH_CLASS}>Project</th>
              <th className={TH_CLASS}>Module</th>
              <th className={TH_CLASS}>Move</th>
              <th className={TH_CLASS}>Requested by</th>
              <th className={TH_CLASS}>Reason</th>
              <th className={cn(TH_CLASS, "text-right")}>{statusFilter === "pending" ? "Actions" : "Status"}</th>
            </tr>
          </thead>
          <tbody>
            {requests.map((request) => {
              const isExpanded = expandedId === request.id;
              return (
                <Fragment key={request.id}>
                  <tr className="group">
                    <WorkItemCell
                      href={workItemLink(workspaceSlug, request.project_id, request.issue_id)}
                      projectIdentifier={request.project_identifier}
                      sequenceId={request.issue_sequence_id}
                      name={request.issue_name}
                    />
                    <ProjectCell name={request.project_name} />
                    <ModulesCell modules={request.modules} />
                    <td className={TD_CLASS}>
                      <div className="flex items-center gap-1.5 text-secondary">
                        <span className="truncate">{request.from_state_name ?? "-"}</span>
                        <ArrowRight className="h-3 w-3 flex-shrink-0 text-tertiary" />
                        <span className="truncate font-medium text-primary">
                          {request.to_state_name ?? "(deleted state)"}
                        </span>
                      </div>
                    </td>
                    <td className={cn(TD_CLASS, "text-tertiary")}>
                      {request.requested_by_name ?? "-"} &middot; {formatApprovalDate(request.created_at)}
                    </td>
                    <td className={TD_CLASS}>
                      <button
                        type="button"
                        onClick={() => setExpandedId(isExpanded ? null : request.id)}
                        className="block max-w-60 truncate text-left text-secondary hover:underline"
                      >
                        {request.reason}
                      </button>
                    </td>
                    <td className="h-11 min-w-36 border-b-[0.5px] border-subtle px-4 text-13">
                      <div className="flex items-center justify-end gap-2">
                        {request.status === "pending" ? (
                          <>
                            <Button size="sm" variant="neutral-primary" onClick={() => setRejectRequest(request)}>
                              Reject
                            </Button>
                            <Button
                              size="sm"
                              variant="primary"
                              loading={decidingId === request.id}
                              onClick={() => handleAccept(request)}
                            >
                              Accept
                            </Button>
                          </>
                        ) : (
                          <StatusBadge status={request.status} />
                        )}
                      </div>
                    </td>
                  </tr>
                  {isExpanded && (
                    <tr>
                      <td colSpan={7} className="border-b-[0.5px] border-subtle px-page-x py-3">
                        <div className="space-y-2 rounded-md bg-layer-1 px-3 py-2 text-13 text-secondary">
                          <p className="whitespace-pre-wrap">
                            <span className="font-medium text-primary">Reason: </span>
                            {request.reason}
                          </p>
                          {request.status !== "pending" && (
                            <p className="whitespace-pre-wrap">
                              <span className="font-medium text-primary">
                                {request.status === "approved" ? "Accepted" : "Rejected"} by{" "}
                                {request.decided_by_name ?? "-"}
                                {request.decided_at ? ` · ${formatApprovalDate(request.decided_at)}` : ""}
                                {request.decision_comment ? ": " : ""}
                              </span>
                              {request.decision_comment}
                            </p>
                          )}
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

  return (
    <div className="flex h-full w-full flex-col overflow-hidden">
      {filterTabs}
      <div className="h-full w-full overflow-hidden">{content}</div>

      <ApprovalSentBackModal
        title="Reject reopen request"
        description="The work item stays approved. Let the requester know why."
        placeholder="Explain why the work item stays where it is"
        submitLabel="Reject"
        errorMessage="Could not reject the request. Please try again."
        isOpen={!!rejectRequest}
        handleClose={() => setRejectRequest(null)}
        onSubmit={handleRejectSubmit}
      />
      <ProjectRegistrarModal
        workspaceSlug={workspaceSlug}
        projectId={registrarRequest?.project_id ?? null}
        handleClose={() => setRegistrarRequest(null)}
        onSubmit={async (agentId) => {
          if (!registrarRequest) return;
          await accept(registrarRequest, agentId);
          setRegistrarRequest(null);
        }}
      />
    </div>
  );
});
