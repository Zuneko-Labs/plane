/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import useSWR from "swr";
import type { IState } from "@plane/types";
import { useMember } from "@/hooks/store/use-member";
import { useProjectState } from "@/hooks/store/use-project-state";
import registrationHandoffService from "@/services/registration-handoff.service";

/** Returned by the server when a registrar must be (re)named - see plane.utils.registration_handoff. */
export const REGISTRATION_AGENT_REQUIRED = "registration_agent_required";

// never "after" the registration state: triage sits outside the flow, and
// cancelling is not a step forward (mirrors plane.utils.registration_handoff)
const NON_FORWARD_STATE_GROUPS = new Set(["triage", "cancelled"]);

const isAtOrPastRegistration = (state: IState | undefined, triggerState: IState) =>
  !!state &&
  (state.id === triggerState.id ||
    (!NON_FORWARD_STATE_GROUPS.has(state.group) && state.sequence > triggerState.sequence));

/**
 * Whether moving from `fromStateId` (undefined when creating) into
 * `toStateId` has to name a registrar — the client mirror of
 * plane.utils.registration_handoff.plan_registration_handoff:
 *  - entering the registration state for the first time, or
 *  - skipping it: jumping from before it (or creating) straight to a later
 *    state, with no registrar on record yet.
 * On re-entry with a registrar on record the server reuses it (and asks
 * again only if that registrar is no longer eligible).
 */
export const getNeedsRegistrar = (args: {
  triggerStateId: string | null | undefined;
  states: IState[] | undefined;
  fromStateId: string | null | undefined;
  toStateId: string | null | undefined;
  hasRegistrationHandoff: boolean | undefined;
}) => {
  const { triggerStateId, states, fromStateId, toStateId, hasRegistrationHandoff } = args;
  if (!triggerStateId || !toStateId || toStateId === fromStateId || hasRegistrationHandoff) return false;
  if (toStateId === triggerStateId) return true;
  const triggerState = states?.find((state) => state.id === triggerStateId);
  if (!triggerState) return false;
  const toState = states?.find((state) => state.id === toStateId);
  if (!isAtOrPastRegistration(toState, triggerState)) return false;
  const fromState = fromStateId ? states?.find((state) => state.id === fromStateId) : undefined;
  return !isAtOrPastRegistration(fromState, triggerState);
};

/**
 * The project's configured "registration" state — moving a work item into
 * it, or skipping past it, requires naming a registrar (see
 * RegistrationAgentModal and `needsRegistrar`). A project with no config
 * row never needs one, i.e. no restriction.
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

  const { getProjectStates } = useProjectState();
  const projectStates = getProjectStates(projectId);

  const config = data?.[0];
  const memberIds = projectId ? (getProjectMemberIds(projectId, false) ?? []) : [];
  const configuredIds = config?.eligible_agent_ids ?? [];
  const eligibleAgentIds =
    configuredIds.length > 0 ? memberIds.filter((memberId) => configuredIds.includes(memberId)) : memberIds;

  return {
    triggerStateId: config?.trigger_state_id,
    eligibleAgentIds,
    needsRegistrar: (
      fromStateId: string | null | undefined,
      toStateId: string | null | undefined,
      hasRegistrationHandoff: boolean | undefined
    ) =>
      getNeedsRegistrar({
        triggerStateId: config?.trigger_state_id,
        states: projectStates,
        fromStateId,
        toStateId,
        hasRegistrationHandoff,
      }),
  };
};
