/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
import { Button } from "@plane/propel/button";
import { setToast, TOAST_TYPE } from "@plane/propel/toast";
import { EModalPosition, EModalWidth, ModalCore } from "@plane/ui";
import { MemberDropdown } from "@/components/dropdowns/member/dropdown";
import { useMember } from "@/hooks/store/use-member";

type Props = {
  isOpen: boolean;
  handleClose: () => void;
  workspaceSlug: string;
  projectId: string;
  eligibleAgentIds: string[];
  onSubmit: (agentId: string) => Promise<void>;
};

/**
 * Moving a work item into the registration state means a physical person
 * has to go to the sub-registrar's office — usually not whoever changed the
 * state. This modal is purely UX: the server (see
 * plane.utils.registration_handoff) rejects the transition regardless of
 * whether it was ever shown, so Cancel here just closes with no side effect.
 */
export const RegistrationAgentModal = (props: Props) => {
  const { isOpen, handleClose, workspaceSlug, projectId, eligibleAgentIds, onSubmit } = props;
  const [agentId, setAgentId] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const {
    project: { fetchProjectMembers },
  } = useMember();

  // MemberDropdown skips its own member-roster fetch whenever it's given an
  // explicit `memberIds` allow-list (see dropdown.tsx) — without this, the
  // eligible agents' names/avatars are never loaded and nothing renders as
  // selectable.
  useEffect(() => {
    if (isOpen && workspaceSlug && projectId) fetchProjectMembers(workspaceSlug, projectId);
  }, [isOpen, workspaceSlug, projectId, fetchProjectMembers]);

  const onClose = () => {
    setAgentId(null);
    setIsSubmitting(false);
    handleClose();
  };

  const handleConfirm = async () => {
    if (!agentId) return;
    setIsSubmitting(true);
    try {
      await onSubmit(agentId);
      onClose();
    } catch {
      setToast({
        type: TOAST_TYPE.ERROR,
        title: "Error",
        message: "Could not name the registration agent. Please try again.",
      });
      setIsSubmitting(false);
    }
  };

  return (
    <ModalCore isOpen={isOpen} handleClose={onClose} position={EModalPosition.CENTER} width={EModalWidth.XL}>
      <div className="p-5">
        <h5 className="text-base font-medium text-primary">Name a registration agent</h5>
        <p className="mt-2 text-13 text-tertiary">
          A physical person will need to go to the sub-registrar's office for this. Pick who's handling it — they'll
          be added as an assignee and notified.
        </p>
        <div className="mt-4">
          <MemberDropdown
            value={agentId}
            onChange={setAgentId}
            // an empty eligible-agents list means "not configured yet", not
            // "nobody is eligible" — fall back to every project member
            memberIds={eligibleAgentIds.length > 0 ? eligibleAgentIds : undefined}
            projectId={projectId}
            multiple={false}
            placeholder="Select registration agent"
            buttonVariant="border-with-text"
          />
        </div>
      </div>
      <div className="flex items-center justify-end gap-2 border-t border-subtle-1 p-4">
        <Button variant="secondary" size="sm" onClick={onClose}>
          Cancel
        </Button>
        <Button variant="primary" size="sm" onClick={handleConfirm} disabled={!agentId} loading={isSubmitting}>
          Confirm
        </Button>
      </div>
    </ModalCore>
  );
};
