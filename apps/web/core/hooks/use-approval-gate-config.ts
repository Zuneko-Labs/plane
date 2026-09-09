/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import useSWR from "swr";
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
import { TOAST_TYPE } from "@plane/propel/toast";
import approvalGateService, { approvalGateConfigSWRKey } from "@/services/approval-gate.service";
import { useUserPermissions } from "@/hooks/store/user";

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
 * The handover flow's sign-off states — enforced server-side (see
 * plane.utils.approval), this hook is UX only (hides the state from the
 * picker, avoids a confusing 400 round-trip).
 *
 * Only Approved is approver-only to enter. The Sent Back state doubles as
 * an ordinary workflow stage ("Xerox and Binding" by default), so moving
 * into it is gated only when it is an actual rejection — an approver
 * bouncing a work item back out of Pending Approval. Hence
 * `isSentBackTransition` takes the state the item is coming *from*.
 */
export const useApprovalGateConfig = (workspaceSlug: string | undefined, projectId: string | undefined) => {
  const { allowPermissions } = useUserPermissions();
  const { data } = useSWR(
    workspaceSlug && projectId ? approvalGateConfigSWRKey(workspaceSlug, projectId) : null,
    workspaceSlug && projectId ? () => approvalGateService.fetchConfig(workspaceSlug, projectId) : null
  );

  const config = data?.[0];
  const isEnabled = config?.is_enabled ?? true;
  const isApprover = allowPermissions(
    [EUserPermissions.ADMIN],
    EUserPermissionsLevel.PROJECT,
    workspaceSlug,
    projectId
  );

  return {
    config,
    isApprover,
    isApproverOnlyState: (stateId: string | null | undefined) =>
      !!config && isEnabled && !!config.approved_state_id && stateId === config.approved_state_id,
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
