/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { Command } from "cmdk";
import { observer } from "mobx-react";
// plane types
import { useParams } from "next/navigation";
import type { TIssue } from "@plane/types";
import { Spinner } from "@plane/ui";
// hooks
import { useProjectState } from "@/hooks/store/use-project-state";
import { useApprovalGateConfig } from "@/hooks/use-approval-gate-config";
import { useRegistrationHandoffConfig } from "@/hooks/use-registration-handoff-config";
// local imports
import { PowerKProjectStatesMenuItems } from "@/plane-web/components/command-palette/power-k/pages/context-based/work-item/state-menu-item";

type Props = {
  handleSelect: (stateId: string) => void;
  workItemDetails: TIssue;
};

export const PowerKProjectStatesMenu = observer(function PowerKProjectStatesMenu(props: Props) {
  const { workItemDetails } = props;
  // router
  const { workspaceSlug } = useParams();
  // store hooks
  const { getProjectStateIds, getStateById } = useProjectState();
  const projectId = workItemDetails.project_id ?? undefined;
  const { isTransitionAllowed, isSentBackTransition, isReopenTransition } = useApprovalGateConfig(
    workspaceSlug?.toString(),
    projectId
  );
  const { needsRegistrar } = useRegistrationHandoffConfig(workspaceSlug?.toString(), projectId);
  // derived values
  const projectStateIds = projectId ? getProjectStateIds(projectId) : undefined;
  const projectStates = projectStateIds ? projectStateIds.map((stateId) => getStateById(stateId)) : undefined;
  // The palette closes on select, so it can't ask for a registrar, a
  // send-back comment or a reopen reason - those moves (and ones the
  // approval gate refuses) are left to the state dropdown, which can.
  const fromStateId = workItemDetails.state_id;
  const filteredProjectStates = projectStates
    ? projectStates.filter(
        (state): state is NonNullable<typeof state> =>
          !!state &&
          (state.id === fromStateId ||
            (isTransitionAllowed(fromStateId, state.id) &&
              !needsRegistrar(fromStateId, state.id, workItemDetails.has_registration_handoff) &&
              !isReopenTransition(fromStateId, state.id) &&
              !isSentBackTransition(fromStateId, state.id)))
      )
    : undefined;

  if (!filteredProjectStates) return <Spinner />;

  return (
    <Command.Group>
      <PowerKProjectStatesMenuItems
        {...props}
        projectId={workItemDetails.project_id ?? undefined}
        selectedStateId={workItemDetails.state_id ?? undefined}
        states={filteredProjectStates}
        workspaceSlug={workspaceSlug?.toString()}
      />
    </Command.Group>
  );
});
