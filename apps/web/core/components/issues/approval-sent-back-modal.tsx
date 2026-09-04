/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { Button } from "@plane/propel/button";
import { setToast, TOAST_TYPE } from "@plane/propel/toast";
import { EModalPosition, EModalWidth, ModalCore } from "@plane/ui";

type Props = {
  isOpen: boolean;
  handleClose: () => void;
  onSubmit: (commentHtml: string) => Promise<void>;
};

/**
 * Sending a work item back is a rejection — the approver must always leave
 * a reason. This modal is purely UX: the server (see plane.utils.approval)
 * rejects the transition regardless of whether it was ever shown, so
 * Cancel here just closes with no side effect.
 */
export const ApprovalSentBackModal = (props: Props) => {
  const { isOpen, handleClose, onSubmit } = props;
  const [comment, setComment] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const onClose = () => {
    setComment("");
    setIsSubmitting(false);
    handleClose();
  };

  const handleConfirm = async () => {
    if (!comment.trim()) return;
    setIsSubmitting(true);
    try {
      await onSubmit(`<p>${comment.trim()}</p>`);
      onClose();
    } catch (err: any) {
      setToast({
        type: TOAST_TYPE.ERROR,
        title: "Error",
        message: err?.error ?? err?.detail ?? "Could not send this work item back. Please try again.",
      });
      setIsSubmitting(false);
    }
  };

  return (
    <ModalCore isOpen={isOpen} handleClose={onClose} position={EModalPosition.CENTER} width={EModalWidth.XL}>
      <div className="p-5">
        <h5 className="text-base font-medium text-primary">Send back for changes</h5>
        <p className="mt-2 text-13 text-tertiary">
          A comment is required — the assignee needs to know what to fix before resubmitting.
        </p>
        <div className="mt-4">
          <textarea
            autoFocus
            rows={4}
            className="w-full rounded-sm border border-subtle-1 bg-surface-1 p-2 text-13 text-primary placeholder:text-placeholder focus:outline-none"
            placeholder="Explain why this is being sent back"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
          />
        </div>
      </div>
      <div className="flex items-center justify-end gap-2 border-t border-subtle-1 p-4">
        <Button variant="secondary" size="sm" onClick={onClose}>
          Cancel
        </Button>
        <Button variant="primary" size="sm" onClick={handleConfirm} disabled={!comment.trim()} loading={isSubmitting}>
          Send back
        </Button>
      </div>
    </ModalCore>
  );
};
