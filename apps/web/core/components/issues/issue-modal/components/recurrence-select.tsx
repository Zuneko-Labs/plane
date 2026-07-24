/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import React from "react";
import { observer } from "mobx-react";
// plane imports
import { useTranslation } from "@plane/i18n";
import type { TIssueRecurrence, TIssueRecurrenceFrequency } from "@plane/types";
import { cn, renderFormattedPayloadDate } from "@plane/utils";
// components
import { DateDropdown } from "@/components/dropdowns/date";

type Props = {
  value: TIssueRecurrence;
  onChange: (value: TIssueRecurrence) => void;
  className?: string;
};

const FREQUENCY_OPTIONS: { value: TIssueRecurrenceFrequency; labelKey: string }[] = [
  { value: "daily", labelKey: "frequency_daily" },
  { value: "weekly", labelKey: "frequency_weekly" },
  { value: "monthly", labelKey: "frequency_monthly" },
];

export const RecurrenceSelect = observer(function RecurrenceSelect(props: Props) {
  const { value, onChange, className } = props;
  const { t } = useTranslation();

  const selectClassName =
    "rounded border-[0.5px] border-subtle bg-surface-1 px-2 py-1 text-caption-sm-regular focus:outline-none focus:ring-1 focus:ring-primary-100";

  return (
    <div className={cn("flex flex-wrap items-center gap-2 pt-2", className)}>
      <span className="text-caption-sm-regular text-secondary">{t("repeats")}</span>
      <select
        value={value.frequency}
        onChange={(e) => onChange({ ...value, frequency: e.target.value as TIssueRecurrenceFrequency })}
        className={selectClassName}
        aria-label={t("recurring")}
      >
        {FREQUENCY_OPTIONS.map((option) => (
          <option key={option.value} value={option.value}>
            {t(option.labelKey)}
          </option>
        ))}
      </select>

      {/* "N times per month" — only meaningful for monthly recurrences */}
      {value.frequency === "monthly" && (
        <>
          <input
            type="number"
            min={1}
            max={28}
            value={value.times_per_month ?? 1}
            onChange={(e) =>
              onChange({ ...value, times_per_month: Math.min(28, Math.max(1, Number(e.target.value) || 1)) })
            }
            className={cn(selectClassName, "w-14")}
            aria-label={t("times_per_month")}
          />
          <span className="text-caption-sm-regular text-secondary">{t("times_per_month")}</span>
        </>
      )}

      <span className="text-caption-sm-regular text-secondary">{t("recurrence_starts_on")}</span>
      <DateDropdown
        value={value.start_date}
        onChange={(date) => onChange({ ...value, start_date: date ? renderFormattedPayloadDate(date) : null })}
        buttonVariant="border-with-text"
        placeholder={t("recurrence_starts_on")}
      />
    </div>
  );
});
