/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import useSWR from "swr";
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
import approvalGateService from "@/services/approval-gate.service";
import { useUserPermissions } from "@/hooks/store/user";

/**
 * The handover flow's sign-off states: only a project approver (Admin) may
 * move a work item into Approved or Sent Back — enforced server-side (see
 * plane.utils.approval), this hook is UX only (hides the states from the
 * picker, avoids a confusing 400 round-trip).
 */
export const useApprovalGateConfig = (workspaceSlug: string | undefined, projectId: string | undefined) => {
  const { allowPermissions } = useUserPermissions();
  const { data } = useSWR(
    workspaceSlug && projectId ? `APPROVAL_GATE_CONFIG_${workspaceSlug}_${projectId}` : null,
    workspaceSlug && projectId ? () => approvalGateService.fetchConfig(workspaceSlug, projectId) : null
  );

  const config = data?.[0];
  const isApprover = allowPermissions([EUserPermissions.ADMIN], EUserPermissionsLevel.PROJECT, workspaceSlug, projectId);

  return {
    config,
    isApprover,
    isApproverOnlyState: (stateId: string | null | undefined) =>
      !!config && (stateId === config.approved_state_id || stateId === config.sent_back_state_id),
    isSentBackState: (stateId: string | null | undefined) => !!config && stateId === config.sent_back_state_id,
  };
};
