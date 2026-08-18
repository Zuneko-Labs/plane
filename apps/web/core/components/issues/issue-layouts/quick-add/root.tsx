/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { FC } from "react";
import { useEffect, useState } from "react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
import { Repeat } from "lucide-react";
import type { UseFormRegister } from "react-hook-form";
import { useForm } from "react-hook-form";
// plane imports
import { useTranslation } from "@plane/i18n";
import { PlusIcon } from "@plane/propel/icons";
import { setPromiseToast } from "@plane/propel/toast";
import type { IProject, TIssue, TIssueRecurrenceFrequency, EIssueLayoutTypes } from "@plane/types";
import { cn, createIssuePayload } from "@plane/utils";
// plane web imports
import { QuickAddIssueFormRoot } from "@/plane-web/components/issues/quick-add";
// local imports
import { CreateIssueToastActionItems } from "../../create-issue-toast-action-items";

export type TQuickAddIssueForm = {
  ref: React.RefObject<HTMLFormElement>;
  isOpen: boolean;
  projectDetail: IProject;
  hasError: boolean;
  register: UseFormRegister<TIssue>;
  onSubmit: () => void;
  isEpic: boolean;
};

export type TQuickAddIssueButton = {
  isEpic?: boolean;
  onClick: () => void;
};

type TQuickAddIssueRoot = {
  isQuickAddOpen?: boolean;
  layout: EIssueLayoutTypes;
  prePopulatedData?: Partial<TIssue>;
  QuickAddButton?: FC<TQuickAddIssueButton>;
  customQuickAddButton?: React.ReactNode;
  containerClassName?: string;
  setIsQuickAddOpen?: (isOpen: boolean) => void;
  quickAddCallback?: (projectId: string | null | undefined, data: TIssue) => Promise<TIssue | undefined>;
  isEpic?: boolean;
};

const defaultValues: Partial<TIssue> = {
  name: "",
};

export const QuickAddIssueRoot = observer(function QuickAddIssueRoot(props: TQuickAddIssueRoot) {
  const {
    isQuickAddOpen,
    layout,
    prePopulatedData,
    QuickAddButton,
    customQuickAddButton,
    containerClassName = "",
    setIsQuickAddOpen,
    quickAddCallback,
    isEpic = false,
  } = props;
  // i18n
  const { t } = useTranslation();
  // router
  const { workspaceSlug, projectId } = useParams();
  // states
  const [isOpen, setIsOpen] = useState(isQuickAddOpen ?? false);
  // "" = one-time (not recurring); otherwise the chosen frequency
  const [recurringFrequency, setRecurringFrequency] = useState<TIssueRecurrenceFrequency | "">("");
  // "N times per month" for monthly recurrences (semi-monthly)
  const [recurringTimesPerMonth, setRecurringTimesPerMonth] = useState<number>(1);
  // form info
  const {
    reset,
    handleSubmit,
    setFocus,
    register,
    formState: { errors, isSubmitting },
  } = useForm<TIssue>({ defaultValues });

  useEffect(() => {
    if (isQuickAddOpen !== undefined) {
      setIsOpen(isQuickAddOpen);
    }
  }, [isQuickAddOpen]);

  useEffect(() => {
    if (!isOpen) {
      reset({ ...defaultValues });
      setRecurringFrequency("");
      setRecurringTimesPerMonth(1);
    }
  }, [isOpen, reset]);

  const handleIsOpen = (nextIsOpen: boolean) => {
    if (isQuickAddOpen !== undefined && setIsQuickAddOpen) {
      setIsQuickAddOpen(nextIsOpen);
    } else {
      setIsOpen(nextIsOpen);
    }
  };

  const onSubmitHandler = async (formData: TIssue) => {
    if (isSubmitting || !workspaceSlug || !projectId) return;

    reset({ ...defaultValues });

    const payload = createIssuePayload(projectId.toString(), {
      ...prePopulatedData,
      ...formData,
      // attach a recurrence rule when a frequency was picked in the quick-add.
      ...(recurringFrequency
        ? {
            recurrence: {
              frequency: recurringFrequency,
              start_date: null,
              ...(recurringFrequency === "monthly" ? { times_per_month: recurringTimesPerMonth } : {}),
            },
          }
        : {}),
    });

    setRecurringFrequency("");
    setRecurringTimesPerMonth(1);

    if (quickAddCallback) {
      const quickAddPromise = quickAddCallback(projectId.toString(), { ...payload });
      setPromiseToast<any>(quickAddPromise, {
        loading: isEpic ? t("epic.adding") : t("issue.adding"),
        success: {
          title: t("common.success"),
          message: () => `${isEpic ? t("epic.create.success") : t("issue.create.success")}`,
          actionItems: (data) => (
            // TODO: Translate here
            <CreateIssueToastActionItems
              workspaceSlug={workspaceSlug.toString()}
              projectId={projectId.toString()}
              issueId={data.id}
              isEpic={isEpic}
            />
          ),
        },
        error: {
          title: t("common.error.label"),
          message: (err) => err?.message || t("common.error.message"),
        },
      });

      await quickAddPromise;
    }
  };

  if (!projectId) return null;

  return (
    <div
      className={cn(
        containerClassName,
        errors && errors?.name && errors?.name?.message ? `border-danger-strong bg-danger-subtle` : ``
      )}
    >
      {isOpen ? (
        <>
          <QuickAddIssueFormRoot
            isOpen={isOpen}
            layout={layout}
            prePopulatedData={prePopulatedData}
            projectId={projectId?.toString()}
            hasError={!!(errors && errors?.name && errors?.name?.message)}
            setFocus={setFocus}
            register={register}
            onSubmit={handleSubmit(onSubmitHandler)}
            onClose={() => handleIsOpen(false)}
            isEpic={isEpic}
          />
          {!isEpic && (
            <div className="flex items-center gap-1.5 px-3 py-1.5 text-tertiary">
              <Repeat className="size-3.5 shrink-0" />
              <select
                value={recurringFrequency}
                onChange={(e) => setRecurringFrequency(e.target.value as TIssueRecurrenceFrequency | "")}
                className="focus:ring-primary-100 rounded border-[0.5px] border-subtle bg-surface-1 px-1.5 py-0.5 text-caption-sm-regular focus:ring-1 focus:outline-none"
                aria-label={t("recurring")}
              >
                <option value="">{t("recurrence_one_time")}</option>
                <option value="daily">{t("frequency_daily")}</option>
                <option value="weekly">{t("frequency_weekly")}</option>
                <option value="monthly">{t("frequency_monthly")}</option>
              </select>
              {recurringFrequency === "monthly" && (
                <>
                  <input
                    type="number"
                    min={1}
                    max={28}
                    value={recurringTimesPerMonth}
                    onChange={(e) => setRecurringTimesPerMonth(Math.min(28, Math.max(1, Number(e.target.value) || 1)))}
                    className="focus:ring-primary-100 w-12 rounded border-[0.5px] border-subtle bg-surface-1 px-1.5 py-0.5 text-caption-sm-regular focus:ring-1 focus:outline-none"
                    aria-label={t("times_per_month")}
                  />
                  <span className="text-caption-sm-regular">{t("times_per_month")}</span>
                </>
              )}
            </div>
          )}
        </>
      ) : (
        <>
          {QuickAddButton && <QuickAddButton isEpic={isEpic} onClick={() => handleIsOpen(true)} />}
          {customQuickAddButton && <>{customQuickAddButton}</>}
          {!QuickAddButton && !customQuickAddButton && (
            <button
              className="flex w-full cursor-pointer items-center gap-2 bg-layer-transparent px-2 py-3 hover:bg-layer-transparent-hover"
              onClick={() => handleIsOpen(true)}
            >
              <PlusIcon className="h-3.5 w-3.5 stroke-2" />
              <span className="text-13 font-medium">{t(`${isEpic ? "epic.new" : "issue.new"}`)}</span>
            </button>
          )}
        </>
      )}
    </div>
  );
});
