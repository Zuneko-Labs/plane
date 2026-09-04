/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import useSWR from "swr";
import registrationHandoffService from "@/services/registration-handoff.service";

/**
 * Whether the given state is the project's configured "registration"
 * state — moving a work item into it requires naming an eligible agent
 * (see RegistrationAgentModal). A project with no config row returns
 * `isGatedState` always false, i.e. no restriction.
 */
export const useRegistrationHandoffConfig = (workspaceSlug: string | undefined, projectId: string | undefined) => {
  const { data } = useSWR(
    workspaceSlug && projectId ? `REGISTRATION_HANDOFF_CONFIG_${workspaceSlug}_${projectId}` : null,
    workspaceSlug && projectId ? () => registrationHandoffService.fetchConfig(workspaceSlug, projectId) : null
  );

  const config = data?.[0];

  return {
    triggerStateId: config?.trigger_state_id,
    eligibleAgentIds: config?.eligible_agent_ids ?? [],
    isGatedState: (stateId: string | null | undefined) => !!config && stateId === config.trigger_state_id,
  };
};
