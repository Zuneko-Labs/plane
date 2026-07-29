/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
import useSWR from "swr";
import { Pencil, Trash2 } from "lucide-react";
// plane imports
import { Button } from "@plane/propel/button";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import type { TComplianceTemplate } from "@plane/types";
import { Table, ToggleSwitch } from "@plane/ui";
// hooks
import { useCompliance } from "@/hooks/store/use-compliance";
// components
import { COMPLIANCE_CADENCE_LABELS } from "./constants";
import { CreateUpdateTemplateModal } from "./create-update-template-modal";
import { DeleteTemplateModal } from "./delete-template-modal";
import { EngineControls } from "./engine-controls";

export const TemplatesList = observer(function TemplatesList() {
  const { workspaceSlug } = useParams();
  const { templates, fetchCategoriesAndTemplates, updateTemplate } = useCompliance();
  const [templateToUpdate, setTemplateToUpdate] = useState<TComplianceTemplate | undefined>(undefined);
  const [templateToDelete, setTemplateToDelete] = useState<TComplianceTemplate | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);

  useSWR(
    workspaceSlug ? `COMPLIANCE_TEMPLATES_${workspaceSlug}` : null,
    workspaceSlug ? () => fetchCategoriesAndTemplates(workspaceSlug.toString()) : null
  );

  const handleToggleActive = async (template: TComplianceTemplate) => {
    if (!workspaceSlug) return;
    try {
      await updateTemplate(workspaceSlug.toString(), template.id, { is_active: !template.is_active });
    } catch (error) {
      const err = error as { error?: string };
      setToast({
        type: TOAST_TYPE.ERROR,
        title: "Error!",
        message: err?.error ?? "Something went wrong. Please try again.",
      });
    }
  };

  return (
    <div className="flex w-full flex-col gap-4">
      <CreateUpdateTemplateModal
        isOpen={isModalOpen}
        templateToUpdate={templateToUpdate}
        onClose={() => {
          setIsModalOpen(false);
          setTemplateToUpdate(undefined);
        }}
      />
      <DeleteTemplateModal
        isOpen={Boolean(templateToDelete)}
        data={templateToDelete}
        onClose={() => setTemplateToDelete(null)}
      />

      <EngineControls />

      <div className="flex items-center justify-between">
        <div>
          <h4 className="text-16 font-medium text-primary">Recurring Templates</h4>
          <p className="text-13 text-secondary">
            Click a template to edit its due date, naming pattern, frequency — or add your own.
          </p>
        </div>
        <Button
          variant="primary"
          onClick={() => {
            setTemplateToUpdate(undefined);
            setIsModalOpen(true);
          }}
        >
          + New template
        </Button>
      </div>

      <Table<TComplianceTemplate>
        data={templates}
        keyExtractor={(template) => template.id}
        tdClassName="text-center"
        columns={[
          { key: "title", content: "Template", tdRender: (row) => row.title },
          {
            key: "category",
            content: "Category",
            tdRender: (row) => row.category_detail?.name,
          },
          {
            key: "cadence",
            content: "Frequency",
            tdRender: (row) => COMPLIANCE_CADENCE_LABELS[row.cadence],
          },
          {
            key: "due",
            content: "Due",
            tdRender: (row) => (row.cadence === "annual" ? `${row.due_day} / month ${row.due_month}` : row.due_day),
          },
          {
            key: "name_template",
            content: "Task name pattern",
            tdRender: (row) => row.name_template,
          },
          {
            key: "is_active",
            content: "Active",
            tdRender: (row) => (
              <ToggleSwitch value={row.is_active} onChange={() => handleToggleActive(row)} size="sm" />
            ),
          },
          {
            key: "actions",
            content: "",
            tdRender: (row) => (
              <div className="flex items-center justify-center gap-2">
                <button
                  type="button"
                  onClick={() => {
                    setTemplateToUpdate(row);
                    setIsModalOpen(true);
                  }}
                  className="text-secondary hover:text-primary"
                >
                  <Pencil className="size-3.5" />
                </button>
                <button
                  type="button"
                  onClick={() => setTemplateToDelete(row)}
                  className="text-secondary hover:text-danger-primary"
                >
                  <Trash2 className="size-3.5" />
                </button>
              </div>
            ),
          },
        ]}
      />
    </div>
  );
});
