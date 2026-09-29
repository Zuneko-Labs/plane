/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { setToast, TOAST_TYPE } from "@plane/propel/toast";
import type { TIssue } from "@plane/types";
// components
import { ApprovalSentBackModal } from "@/components/issues/approval-sent-back-modal";
import { RegistrationAgentModal } from "@/components/issues/registration-agent-modal";
// hooks
import { SENT_FOR_APPROVAL_TOAST, useApprovalGateConfig } from "@/hooks/use-approval-gate-config";
import { REGISTRATION_AGENT_REQUIRED, useRegistrationHandoffConfig } from "@/hooks/use-registration-handoff-config";

type TStateTransitionWorkItem = Pick<TIssue, "id" | "state_id"> &
  Partial<Pick<TIssue, "assignee_ids" | "has_registration_handoff">>;

type TUseWorkItemStateTransitionArgs = {
  workspaceSlug: string | undefined;
  projectId: string | null | undefined;
  workItem: TStateTransitionWorkItem | undefined;
  /** Persists the change (optimistic store update + PATCH). Must reject on API errors. */
  onUpdate: (data: Partial<TIssue>) => Promise<unknown>;
};

const getErrorBody = (error: unknown): { error?: string; error_code?: string } | undefined => {
  if (!error || typeof error !== "object") return undefined;
  const maybeResponse = (error as { response?: { data?: unknown } }).response?.data;
  const body = (maybeResponse ?? error) as { error?: unknown; error_code?: unknown };
  return {
    error: typeof body.error === "string" ? body.error : undefined,
    error_code: typeof body.error_code === "string" ? body.error_code : undefined,
  };
};

/**
 * One place every state-change surface (list/kanban properties, peek view,
 * detail sidebar, spreadsheet, sub-issues, relations, command palette) goes
 * through, so the handover approval gate and the registration handoff
 * behave the same everywhere:
 *  - a move the approval gate refuses is explained with a toast, no request;
 *  - moving into the registration state asks for a registrar (and again if
 *    the server says the one on record is no longer eligible);
 *  - an approver bouncing a work item out of Pending Approval asks for a
 *    comment;
 *  - entering Pending Approval confirms it went to the approvers.
 * The server enforces all of it regardless (see plane.utils.state_transition).
 *
 * Render `stateTransitionModals` next to the surface.
 */
export const useWorkItemStateTransition = (args: TUseWorkItemStateTransitionArgs) => {
  const { workspaceSlug, projectId, workItem, onUpdate } = args;
  const [pendingRegistrationStateId, setPendingRegistrationStateId] = useState<string | null>(null);
  const [pendingSentBackStateId, setPendingSentBackStateId] = useState<string | null>(null);

  const { getTransitionError, isTransitionAllowed, isSentBackTransition, isSendForApprovalTransition } =
    useApprovalGateConfig(workspaceSlug, projectId ?? undefined);
  const { isGatedState, eligibleAgentIds } = useRegistrationHandoffConfig(workspaceSlug, projectId ?? undefined);

  const showError = (message: string) => setToast({ type: TOAST_TYPE.ERROR, title: "Can't move work item", message });

  /** `fromModal`: the modal shows its own error toast and stays open. */
  const submit = async (stateId: string, data: Partial<TIssue>, fromModal = false) => {
    const sendsForApproval = isSendForApprovalTransition(workItem?.state_id, stateId);
    try {
      await onUpdate({ state_id: stateId, ...data });
      if (sendsForApproval) setToast(SENT_FOR_APPROVAL_TOAST);
    } catch (error) {
      const body = getErrorBody(error);
      if (body?.error_code === REGISTRATION_AGENT_REQUIRED && !("registration_agent_id" in data)) {
        // the registrar on record is gone (left the project, removed from
        // the pool) - ask for a new one instead of failing
        setPendingRegistrationStateId(stateId);
        return;
      }
      if (!fromModal) showError(body?.error ?? "The state could not be changed. Please try again.");
      throw error;
    }
  };

  const changeState = async (stateId: string | null | undefined) => {
    if (!workItem || !stateId || stateId === workItem.state_id) return;

    const transitionError = getTransitionError(workItem.state_id, stateId);
    if (transitionError) {
      showError(transitionError);
      return;
    }
    // only the first handoff needs a registrar; a work item that already
    // has one keeps it on re-entry (server re-asks if it's no longer valid)
    if (isGatedState(stateId) && !workItem.has_registration_handoff) {
      setPendingRegistrationStateId(stateId);
      return;
    }
    if (isSentBackTransition(workItem.state_id, stateId)) {
      setPendingSentBackStateId(stateId);
      return;
    }
    await submit(stateId, {}).catch(() => undefined);
  };

  const stateTransitionModals = (
    <>
      <RegistrationAgentModal
        isOpen={!!pendingRegistrationStateId}
        handleClose={() => setPendingRegistrationStateId(null)}
        workspaceSlug={workspaceSlug ?? ""}
        projectId={projectId ?? ""}
        eligibleAgentIds={eligibleAgentIds}
        onSubmit={async (agentId) => {
          if (!pendingRegistrationStateId) return;
          await submit(
            pendingRegistrationStateId,
            {
              // Not TIssue fields — one-shot instructions the backend reads off
              // the raw request body (see plane.utils.registration_handoff).
              registration_agent_id: agentId,
              // the server adds the registrar on top of the assignees sent, so
              // sending them here also shows the registrar right away
              assignee_ids: Array.from(new Set([...(workItem?.assignee_ids ?? []), agentId])),
              // the PATCH returns no body - mirror the record the server wrote
              // so the next move into the state doesn't re-prompt
              has_registration_handoff: true,
            } as Partial<TIssue>,
            true
          );
        }}
      />
      <ApprovalSentBackModal
        isOpen={!!pendingSentBackStateId}
        handleClose={() => setPendingSentBackStateId(null)}
        onSubmit={async (commentHtml) => {
          if (!pendingSentBackStateId) return;
          await submit(
            pendingSentBackStateId,
            {
              // Not a TIssue field — read off the raw request body (see plane.utils.approval).
              approval_comment_html: commentHtml,
            } as Partial<TIssue>,
            true
          );
        }}
      />
    </>
  );

  return { changeState, isTransitionAllowed, stateTransitionModals };
};
