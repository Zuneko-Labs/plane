/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import useSWR from "swr";
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
import { TOAST_TYPE } from "@plane/propel/toast";
import type { IState } from "@plane/types";
import approvalGateService, { approvalGateConfigSWRKey } from "@/services/approval-gate.service";
import { useProjectState } from "@/hooks/store/use-project-state";
import { useUserPermissions } from "@/hooks/store/user";

// never "further along" than Pending Approval: triage sits outside the
// flow, and cancelling is not a step forward (mirrors plane.utils.approval)
const NON_FORWARD_STATE_GROUPS = new Set(["triage", "cancelled"]);

type TApprovalGateStateIds = {
  pending_approval_state_id?: string | null;
  approved_state_id?: string | null;
  is_enabled?: boolean;
};

/** States only an approver may move a work item into, and only from Pending Approval. */
export const getPastPendingStateIds = (config: TApprovalGateStateIds | undefined, states: IState[] | undefined) => {
  const ids = new Set<string>();
  if (!config || config.is_enabled === false) return ids;
  if (config.approved_state_id) ids.add(config.approved_state_id);
  const pendingState = states?.find((state) => state.id === config.pending_approval_state_id);
  if (pendingState)
    for (const state of states ?? [])
      if (!NON_FORWARD_STATE_GROUPS.has(state.group) && state.sequence > pendingState.sequence) ids.add(state.id);
  return ids;
};

/**
 * Why moving from `fromStateId` (undefined when creating) into `toStateId`
 * is refused, or null when it is allowed — the client mirror of
 * plane.utils.approval.evaluate_approval_gate.
 */
export const getApprovalTransitionError = (args: {
  config: TApprovalGateStateIds | undefined;
  states: IState[] | undefined;
  isApprover: boolean;
  fromStateId: string | null | undefined;
  toStateId: string | null | undefined;
}) => {
  const { config, states, isApprover, fromStateId, toStateId } = args;
  const pastPendingStateIds = getPastPendingStateIds(config, states);
  if (!toStateId || toStateId === fromStateId || !pastPendingStateIds.has(toStateId)) return null;
  if (fromStateId && pastPendingStateIds.has(fromStateId)) return null; // already signed off
  const pendingStateId = config?.pending_approval_state_id;
  const pendingName = states?.find((state) => state.id === pendingStateId)?.name;
  const targetName = states?.find((state) => state.id === toStateId)?.name ?? "this state";
  if (!pendingStateId) return isApprover ? null : `Only a project approver can move a work item to "${targetName}".`;
  if (fromStateId !== pendingStateId)
    return `A work item must be sent to "${pendingName}" and approved before it can move to "${targetName}".`;
  if (!isApprover) return `Only a project approver can move a work item past "${pendingName}".`;
  return null;
};

/**
 * Shown wherever a work item is moved into the Pending Approval state, so
 * the person who moved it can see it has gone to the project's approvers
 * rather than just changing status.
 */
export const SENT_FOR_APPROVAL_TOAST = {
  type: TOAST_TYPE.INFO,
  title: "Sent for approval",
  message: "A project approver will review this work item.",
} as const;

/**
 * The handover approval gate, mirrored from the server (see
 * plane.utils.approval.evaluate_approval_gate) — the server enforces it on
 * every entry point, this hook is UX only (hides states that can't be
 * picked, explains a refused move without a 400 round-trip).
 *
 * Pending Approval is a hard stop for everyone: a state after it (higher
 * sequence, or the Approved state itself) can only be reached from Pending
 * Approval, and only by an approver; a work item can't be created past it.
 * Anyone may send a work item into Pending Approval or pull it back out.
 *
 * The Sent Back state doubles as an ordinary workflow stage ("Xerox and
 * Binding" by default), so moving into it is a rejection (comment required)
 * only when an approver bounces a work item out of Pending Approval. Hence
 * `isSentBackTransition` takes the state the item is coming *from*.
 */
export const useApprovalGateConfig = (workspaceSlug: string | undefined, projectId: string | undefined) => {
  const { allowPermissions } = useUserPermissions();
  const { data } = useSWR(
    workspaceSlug && projectId ? approvalGateConfigSWRKey(workspaceSlug, projectId) : null,
    workspaceSlug && projectId ? () => approvalGateService.fetchConfig(workspaceSlug, projectId) : null
  );

  const { getProjectStates } = useProjectState();
  const projectStates = getProjectStates(projectId);

  const config = data?.[0];
  const isEnabled = config?.is_enabled ?? true;
  const isApprover = allowPermissions(
    [EUserPermissions.ADMIN],
    EUserPermissionsLevel.PROJECT,
    workspaceSlug,
    projectId
  );
  /**
   * Why moving from `fromStateId` (undefined when creating) into
   * `toStateId` is refused, or null when it is allowed.
   */
  const getTransitionError = (fromStateId: string | null | undefined, toStateId: string | null | undefined) =>
    getApprovalTransitionError({ config, states: projectStates, isApprover, fromStateId, toStateId });

  return {
    config,
    isApprover,
    getTransitionError,
    isTransitionAllowed: (fromStateId: string | null | undefined, toStateId: string | null | undefined) =>
      getTransitionError(fromStateId, toStateId) === null,
    // Moving a work item into Pending Approval IS the act of submitting it
    // for sign-off — the server notifies the project's approvers (see
    // plane.bgtasks.notification_task.notify_pending_approval). Callers use
    // this to confirm that to the person who moved it.
    isSendForApprovalTransition: (fromStateId: string | null | undefined, toStateId: string | null | undefined) =>
      !!config &&
      isEnabled &&
      !!config.pending_approval_state_id &&
      toStateId === config.pending_approval_state_id &&
      fromStateId !== config.pending_approval_state_id,
    isSentBackTransition: (fromStateId: string | null | undefined, toStateId: string | null | undefined) =>
      !!config &&
      isEnabled &&
      isApprover &&
      !!config.sent_back_state_id &&
      !!config.pending_approval_state_id &&
      toStateId === config.sent_back_state_id &&
      fromStateId === config.pending_approval_state_id,
  };
};
