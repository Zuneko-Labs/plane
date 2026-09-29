/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import useSWR from "swr";
import { useMember } from "@/hooks/store/use-member";
import registrationHandoffService from "@/services/registration-handoff.service";

/** Returned by the server when a registrar must be (re)named - see plane.utils.registration_handoff. */
export const REGISTRATION_AGENT_REQUIRED = "registration_agent_required";

/**
 * Whether the given state is the project's configured "registration"
 * state — moving a work item into it requires naming a registrar (see
 * RegistrationAgentModal). A project with no config row returns
 * `isGatedState` always false, i.e. no restriction.
 *
 * `eligibleAgentIds` mirrors the server: active project Members/Admins
 * (guests can't be assigned work items), narrowed to the configured pool
 * when there is one.
 */
export const useRegistrationHandoffConfig = (workspaceSlug: string | undefined, projectId: string | undefined) => {
  const { data } = useSWR(
    workspaceSlug && projectId ? `REGISTRATION_HANDOFF_CONFIG_${workspaceSlug}_${projectId}` : null,
    workspaceSlug && projectId ? () => registrationHandoffService.fetchConfig(workspaceSlug, projectId) : null
  );

  const {
    project: { getProjectMemberIds },
  } = useMember();

  const config = data?.[0];
  const memberIds = projectId ? (getProjectMemberIds(projectId, false) ?? []) : [];
  const configuredIds = config?.eligible_agent_ids ?? [];
  const eligibleAgentIds =
    configuredIds.length > 0 ? memberIds.filter((memberId) => configuredIds.includes(memberId)) : memberIds;

  return {
    triggerStateId: config?.trigger_state_id,
    eligibleAgentIds,
    isGatedState: (stateId: string | null | undefined) => !!config && stateId === config.trigger_state_id,
  };
};
