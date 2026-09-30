/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { setToast, TOAST_TYPE } from "@plane/propel/toast";
import type { TIssue } from "@plane/types";
// components
import { ApprovalSentBackModal, REOPEN_REQUEST_COPY } from "@/components/issues/approval-sent-back-modal";
import { RegistrationAgentModal } from "@/components/issues/registration-agent-modal";
// hooks
import {
  REOPEN_APPROVAL_REQUIRED,
  SENT_FOR_APPROVAL_TOAST,
  useApprovalGateConfig,
} from "@/hooks/use-approval-gate-config";
import { REGISTRATION_AGENT_REQUIRED, useRegistrationHandoffConfig } from "@/hooks/use-registration-handoff-config";
// services
import approvalGateService from "@/services/approval-gate.service";

type TStateTransitionWorkItem = Pick<TIssue, "id" | "state_id"> &
  Partial<Pick<TIssue, "assignee_ids" | "has_registration_handoff">>;

type TUseWorkItemStateTransitionArgs = {
  workspaceSlug: string | undefined;
  projectId: string | null | undefined;
  workItem: TStateTransitionWorkItem | undefined;
  /** Persists the change (optimistic store update + PATCH). Must reject on API errors. */
  onUpdate: (data: Partial<TIssue>) => Promise<unknown>;
};

/** The reason modals hand back escaped HTML; reopen requests store plain text. */
export const htmlToPlainText = (html: string) =>
  new DOMParser()
    // keep paragraph breaks as line breaks
    .parseFromString(html.replace(/<\/p>\s*<p/g, "</p>\n<p"), "text/html")
    .body.textContent?.trim() ?? "";

export const REOPEN_REQUEST_SENT_TOAST = {
  type: TOAST_TYPE.SUCCESS,
  title: "Reopen requested",
  message: "A project approver has to accept it before the work item moves back.",
} as const;

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
 *  - moving into (or skipping past) the registration state asks for a
 *    registrar when none is on record;
 *  - an approver bouncing a work item out of Pending Approval asks for a
 *    comment;
 *  - moving a work item that is pending approval or approved back asks
 *    for a reopen request with a reason - for everyone, approvers
 *    included; the item stays put until an approver accepts it;
 *  - entering Pending Approval confirms it went to the approvers.
 * The server enforces all of it regardless (see plane.utils.state_transition).
 *
 * Render `stateTransitionModals` next to the surface.
 */
export const useWorkItemStateTransition = (args: TUseWorkItemStateTransitionArgs) => {
  const { workspaceSlug, projectId, workItem, onUpdate } = args;
  const [pendingRegistrationStateId, setPendingRegistrationStateId] = useState<string | null>(null);
  // what the move that ran into "name a registrar" already carried (e.g. a
  // reopen reason), re-sent together with the registrar
  const [pendingRegistrationExtra, setPendingRegistrationExtra] = useState<Partial<TIssue>>({});
  const [pendingSentBackStateId, setPendingSentBackStateId] = useState<string | null>(null);
  const [pendingReopenRequestStateId, setPendingReopenRequestStateId] = useState<string | null>(null);

  const {
    getTransitionError,
    isTransitionAllowed,
    isSentBackTransition,
    isSendForApprovalTransition,
    isReopenTransition,
  } = useApprovalGateConfig(workspaceSlug, projectId ?? undefined);
  const { needsRegistrar, eligibleAgentIds } = useRegistrationHandoffConfig(workspaceSlug, projectId ?? undefined);

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
        // the pool), or the move skips registration - ask for one instead
        // of failing
        setPendingRegistrationExtra(data);
        setPendingRegistrationStateId(stateId);
        return;
      }
      // the local config was stale - fall back to the reopen request
      if (body?.error_code === REOPEN_APPROVAL_REQUIRED && !fromModal) {
        setPendingReopenRequestStateId(stateId);
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
    // a work item pending approval or approved doesn't come back until an
    // approver accepts a reopen request (the approver's own Send Back is
    // the one exception - handled below)
    if (isReopenTransition(workItem.state_id, stateId)) {
      setPendingReopenRequestStateId(stateId);
      return;
    }
    // entering the registration state, or skipping past it, needs a
    // registrar - only the first time; a work item that already has one
    // keeps it (server re-asks if it's no longer valid)
    if (needsRegistrar(workItem.state_id, stateId, workItem.has_registration_handoff)) {
      setPendingRegistrationExtra({});
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
        handleClose={() => {
          setPendingRegistrationStateId(null);
          setPendingRegistrationExtra({});
        }}
        workspaceSlug={workspaceSlug ?? ""}
        projectId={projectId ?? ""}
        eligibleAgentIds={eligibleAgentIds}
        onSubmit={async (agentId) => {
          if (!pendingRegistrationStateId) return;
          await submit(
            pendingRegistrationStateId,
            {
              ...pendingRegistrationExtra,
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
      <ApprovalSentBackModal
        {...REOPEN_REQUEST_COPY}
        isOpen={!!pendingReopenRequestStateId}
        handleClose={() => setPendingReopenRequestStateId(null)}
        onSubmit={async (commentHtml) => {
          if (!pendingReopenRequestStateId || !workspaceSlug || !projectId || !workItem) return;
          await approvalGateService.createReopenRequest(workspaceSlug, projectId, workItem.id, {
            state_id: pendingReopenRequestStateId,
            reason: htmlToPlainText(commentHtml),
          });
          setToast(REOPEN_REQUEST_SENT_TOAST);
        }}
      />
    </>
  );

  return { changeState, isTransitionAllowed, stateTransitionModals };
};
