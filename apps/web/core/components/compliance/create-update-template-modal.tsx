/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
import { Controller, useForm } from "react-hook-form";
// plane imports
import { ISSUE_PRIORITIES } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
import { Button } from "@plane/propel/button";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import type { TComplianceCadence, TComplianceTemplate } from "@plane/types";
import { CustomSelect, EModalPosition, EModalWidth, Input, ModalCore, ToggleSwitch } from "@plane/ui";
// hooks
import { useCompliance } from "@/hooks/store/use-compliance";
// components
import { COMPLIANCE_CADENCE_LABELS } from "./constants";

const CADENCE_OPTIONS: TComplianceCadence[] = ["monthly", "quarterly", "annual", "advance_tax"];
// Sentinel value for the "+ Create new category" option in the category
// dropdown — resolved into a real category id at submit time.
const NEW_CATEGORY_VALUE = "__new__";

type Props = {
  isOpen: boolean;
  onClose: () => void;
  templateToUpdate?: TComplianceTemplate;
};

type TFormValues = {
  key: string;
  title: string;
  category: string;
  cadence: TComplianceCadence;
  due_day: number | null;
  due_month: number | null;
  name_template: string;
  priority: TComplianceTemplate["priority"];
  is_active: boolean;
};

const defaultValues: TFormValues = {
  key: "",
  title: "",
  category: "",
  cadence: "monthly",
  due_day: 20,
  due_month: null,
  name_template: "{title} - {period}",
  priority: "medium",
  is_active: true,
};

// Small label above every field — without this, a bare input/dropdown gives
// no clue what it controls (this was the actual UX bug reported: fields
// like the key input or due-day number were unlabeled).
function FieldLabel(props: { children: string }) {
  return <label className="text-13 font-medium text-secondary">{props.children}</label>;
}

export const CreateUpdateTemplateModal = observer(function CreateUpdateTemplateModal(props: Props) {
  const { isOpen, onClose, templateToUpdate } = props;
  const { workspaceSlug } = useParams();
  const { t } = useTranslation();
  const { categories, createCategory, createTemplate, updateTemplate } = useCompliance();
  const [newCategoryName, setNewCategoryName] = useState("");

  const {
    control,
    handleSubmit,
    reset,
    watch,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<TFormValues>({ defaultValues });

  const cadence = watch("cadence");
  const category = watch("category");
  const isUpdating = Boolean(templateToUpdate);
  const isCreatingNewCategory = category === NEW_CATEGORY_VALUE;

  useEffect(() => {
    if (!isOpen) return;
    setNewCategoryName("");
    if (templateToUpdate) {
      reset({
        key: templateToUpdate.key,
        title: templateToUpdate.title,
        category: templateToUpdate.category,
        cadence: templateToUpdate.cadence,
        due_day: templateToUpdate.due_day,
        due_month: templateToUpdate.due_month,
        name_template: templateToUpdate.name_template,
        priority: templateToUpdate.priority,
        is_active: templateToUpdate.is_active,
      });
    } else {
      reset(defaultValues);
    }
  }, [isOpen, templateToUpdate, reset]);

  const handleClose = () => {
    onClose();
    reset(defaultValues);
    setNewCategoryName("");
  };

  const handleFormSubmit = async (data: TFormValues) => {
    if (!workspaceSlug) return;
    // The "required" rule already blocks this in practice — guarding here
    // too since the field is nullable (so it can be fully cleared while
    // typing, rather than snapping to 0).
    if (data.due_day === null) {
      setError("due_day", { type: "manual", message: "Due day is required." });
      return;
    }

    let categoryId = data.category;
    if (isCreatingNewCategory) {
      if (!newCategoryName.trim()) {
        setError("category", { type: "manual", message: "Enter a name for the new category." });
        return;
      }
      try {
        const newCategory = await createCategory(workspaceSlug.toString(), newCategoryName.trim());
        categoryId = newCategory.id;
      } catch (error) {
        const err = error as { name?: string[]; error?: string };
        setToast({
          type: TOAST_TYPE.ERROR,
          title: "Error!",
          message: err?.name?.[0] ?? err?.error ?? "Could not create category.",
        });
        return;
      }
    }

    const payload: Partial<TComplianceTemplate> = {
      ...data,
      category: categoryId,
      due_day: data.due_day,
      due_month: data.cadence === "annual" ? data.due_month : null,
    };

    try {
      if (isUpdating && templateToUpdate) {
        await updateTemplate(workspaceSlug.toString(), templateToUpdate.id, payload);
      } else {
        await createTemplate(workspaceSlug.toString(), payload);
      }
      handleClose();
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
    <ModalCore isOpen={isOpen} position={EModalPosition.TOP} width={EModalWidth.XL} handleClose={handleClose}>
      <form onSubmit={handleSubmit(handleFormSubmit)}>
        <div className="space-y-4 p-5">
          <h3 className="text-18 font-medium text-primary">{isUpdating ? t("update") : "New template"}</h3>

          <div className="space-y-1">
            <FieldLabel>Title</FieldLabel>
            <Controller
              control={control}
              name="title"
              rules={{ required: "Title is required." }}
              render={({ field: { value, onChange } }) => (
                <Input
                  value={value}
                  onChange={onChange}
                  hasError={Boolean(errors.title)}
                  placeholder="e.g. GSTR-1"
                  className="w-full"
                />
              )}
            />
            {errors.title && <p className="text-11 text-danger-primary">{errors.title.message}</p>}
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <FieldLabel>Key (unique, used internally)</FieldLabel>
              <Controller
                control={control}
                name="key"
                rules={{ required: "Key is required." }}
                render={({ field: { value, onChange } }) => (
                  <Input
                    value={value}
                    onChange={onChange}
                    disabled={isUpdating}
                    hasError={Boolean(errors.key)}
                    placeholder="e.g. gstr-1"
                    className="w-full"
                  />
                )}
              />
              {errors.key && <p className="text-11 text-danger-primary">{errors.key.message}</p>}
            </div>

            <div className="space-y-1">
              <FieldLabel>Category</FieldLabel>
              <Controller
                control={control}
                name="category"
                rules={{ required: "Select or create a category." }}
                render={({ field: { value, onChange } }) =>
                  isCreatingNewCategory ? (
                    <div className="flex items-center gap-2">
                      <Input
                        value={newCategoryName}
                        onChange={(e) => setNewCategoryName(e.target.value)}
                        placeholder="New category name, e.g. GST"
                        className="w-full"
                      />
                      <button
                        type="button"
                        onClick={() => {
                          setNewCategoryName("");
                          onChange("");
                        }}
                        className="text-13 whitespace-nowrap text-tertiary hover:text-primary"
                      >
                        Cancel
                      </button>
                    </div>
                  ) : (
                    <CustomSelect
                      value={value}
                      onChange={onChange}
                      label={categories.find((c) => c.id === value)?.name ?? "Select category"}
                      buttonClassName="w-full border-[0.5px] border-strong"
                    >
                      {categories.map((cat) => (
                        <CustomSelect.Option key={cat.id} value={cat.id}>
                          {cat.name}
                        </CustomSelect.Option>
                      ))}
                      <CustomSelect.Option value={NEW_CATEGORY_VALUE}>+ Create new category</CustomSelect.Option>
                    </CustomSelect>
                  )
                }
              />
              {errors.category && <p className="text-11 text-danger-primary">{errors.category.message}</p>}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <FieldLabel>Frequency</FieldLabel>
              <Controller
                control={control}
                name="cadence"
                render={({ field: { value, onChange } }) => (
                  <CustomSelect
                    value={value}
                    onChange={onChange}
                    label={COMPLIANCE_CADENCE_LABELS[value]}
                    buttonClassName="w-full border-[0.5px] border-strong"
                  >
                    {CADENCE_OPTIONS.map((option) => (
                      <CustomSelect.Option key={option} value={option}>
                        {COMPLIANCE_CADENCE_LABELS[option]}
                      </CustomSelect.Option>
                    ))}
                  </CustomSelect>
                )}
              />
            </div>

            <div className="space-y-1">
              <FieldLabel>Priority</FieldLabel>
              <Controller
                control={control}
                name="priority"
                render={({ field: { value, onChange } }) => (
                  <CustomSelect
                    value={value}
                    onChange={onChange}
                    label={ISSUE_PRIORITIES.find((p) => p.key === value)?.title ?? value}
                    buttonClassName="w-full border-[0.5px] border-strong"
                  >
                    {ISSUE_PRIORITIES.map((option) => (
                      <CustomSelect.Option key={option.key} value={option.key}>
                        {option.title}
                      </CustomSelect.Option>
                    ))}
                  </CustomSelect>
                )}
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <FieldLabel>Due day of month (1-31)</FieldLabel>
              <Controller
                control={control}
                name="due_day"
                rules={{ required: "Due day is required.", min: 1, max: 31 }}
                render={({ field: { value, onChange } }) => (
                  <Input
                    type="number"
                    value={value ?? ""}
                    onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}
                    hasError={Boolean(errors.due_day)}
                    placeholder="20"
                    className="w-full"
                  />
                )}
              />
              {errors.due_day && <p className="text-11 text-danger-primary">Enter a day between 1 and 31.</p>}
            </div>
            {cadence === "annual" && (
              <div className="space-y-1">
                <FieldLabel>Due month (1-12, annual only)</FieldLabel>
                <Controller
                  control={control}
                  name="due_month"
                  rules={{ required: cadence === "annual", min: 1, max: 12 }}
                  render={({ field: { value, onChange } }) => (
                    <Input
                      type="number"
                      value={value ?? ""}
                      onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}
                      hasError={Boolean(errors.due_month)}
                      placeholder="10"
                      className="w-full"
                    />
                  )}
                />
                {errors.due_month && <p className="text-11 text-danger-primary">Enter a month between 1 and 12.</p>}
              </div>
            )}
          </div>

          <div className="space-y-1">
            <FieldLabel>Task name pattern</FieldLabel>
            <Controller
              control={control}
              name="name_template"
              rules={{ required: "Name pattern is required." }}
              render={({ field: { value, onChange } }) => (
                <Input
                  value={value}
                  onChange={onChange}
                  hasError={Boolean(errors.name_template)}
                  placeholder="{title} - {period}"
                  className="w-full"
                />
              )}
            />
            <p className="text-11 text-tertiary">
              Placeholders: {"{title}"} {"{period}"} {"{month}"} {"{year}"} — e.g. {"{title} - {period}"} → GSTR-1 -
              July 2026
            </p>
            {errors.name_template && <p className="text-11 text-danger-primary">{errors.name_template.message}</p>}
          </div>

          <div className="flex items-center gap-2">
            <Controller
              control={control}
              name="is_active"
              render={({ field: { value, onChange } }) => <ToggleSwitch value={value} onChange={onChange} size="sm" />}
            />
            <span className="text-13 text-secondary">Active</span>
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 border-t-[0.5px] border-subtle px-5 py-4">
          <Button variant="secondary" onClick={handleClose}>
            {t("cancel")}
          </Button>
          <Button variant="primary" type="submit" loading={isSubmitting}>
            {isUpdating ? t("update") : t("add")}
          </Button>
        </div>
      </form>
    </ModalCore>
  );
});
