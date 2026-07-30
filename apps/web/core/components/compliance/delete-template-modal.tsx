/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
// plane imports
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import type { TComplianceTemplate } from "@plane/types";
import { AlertModalCore } from "@plane/ui";
// hooks
import { useCompliance } from "@/hooks/store/use-compliance";

type Props = {
  isOpen: boolean;
  onClose: () => void;
  data: TComplianceTemplate | null;
};

export const DeleteTemplateModal = observer(function DeleteTemplateModal(props: Props) {
  const { isOpen, onClose, data } = props;
  const { workspaceSlug } = useParams();
  const { deleteTemplate } = useCompliance();
  const [isDeleting, setIsDeleting] = useState(false);

  const handleClose = () => {
    onClose();
    setIsDeleting(false);
  };

  const handleDeletion = async () => {
    if (!workspaceSlug || !data) return;
    setIsDeleting(true);
    try {
      await deleteTemplate(workspaceSlug.toString(), data.id);
      handleClose();
    } catch (error) {
      setIsDeleting(false);
      const err = error as { error?: string };
      setToast({
        type: TOAST_TYPE.ERROR,
        title: "Error!",
        message: err?.error ?? "Something went wrong. Please try again.",
      });
    }
  };

  return (
    <AlertModalCore
      handleClose={handleClose}
      handleSubmit={handleDeletion}
      isSubmitting={isDeleting}
      isOpen={isOpen}
      title="Delete template"
      content={
        <>
          Are you sure you want to delete this template? This cannot be undone.{" "}
          <span className="font-medium text-primary">{data?.title}</span>
        </>
      }
    />
  );
});
