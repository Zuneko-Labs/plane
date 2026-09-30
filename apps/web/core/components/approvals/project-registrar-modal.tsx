/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { RegistrationAgentModal } from "@/components/issues/registration-agent-modal";
import { useRegistrationHandoffConfig } from "@/hooks/use-registration-handoff-config";

type Props = {
  workspaceSlug: string;
  /** null: closed */
  projectId: string | null;
  handleClose: () => void;
  onSubmit: (agentId: string) => Promise<void>;
};

/**
 * The workspace approvals page spans projects, so the registrar pool has to
 * be resolved for whichever project the server asked a registrar for (a
 * move that would skip the registration state - see
 * plane.utils.registration_handoff).
 */
export const ProjectRegistrarModal = observer(function ProjectRegistrarModal(props: Props) {
  const { workspaceSlug, projectId, handleClose, onSubmit } = props;
  const { eligibleAgentIds } = useRegistrationHandoffConfig(workspaceSlug, projectId ?? undefined);

  return (
    <RegistrationAgentModal
      isOpen={!!projectId}
      handleClose={handleClose}
      workspaceSlug={workspaceSlug}
      projectId={projectId ?? ""}
      eligibleAgentIds={eligibleAgentIds}
      onSubmit={onSubmit}
    />
  );
});
