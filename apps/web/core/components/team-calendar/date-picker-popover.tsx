/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { ChevronDown, ChevronLeft, ChevronRight } from "lucide-react";
// plane imports
import { MONTHS_LIST } from "@plane/constants";
import { Calendar } from "@plane/propel/calendar";
import { Popover } from "@plane/propel/popover";
import { cn } from "@plane/utils";

type TDatePickerPopoverProps = {
  label: string;
  anchor: Date;
  onChange: (date: Date) => void;
};

/** Clickable calendar title: jump to any year/month, or pick an exact date. */
export function DatePickerPopover({ label, anchor, onChange }: TDatePickerPopoverProps) {
  const [open, setOpen] = useState(false);
  const [cursor, setCursor] = useState(() => new Date(anchor.getFullYear(), anchor.getMonth(), 1));
  const year = cursor.getFullYear();

  const handleOpenChange = (next: boolean) => {
    if (next) setCursor(new Date(anchor.getFullYear(), anchor.getMonth(), 1));
    setOpen(next);
  };

  const pick = (date: Date) => {
    onChange(date);
    setOpen(false);
  };

  return (
    <Popover open={open} onOpenChange={handleOpenChange}>
      <Popover.Button
        className="flex h-7 items-center gap-1 rounded-sm px-2 text-14 font-semibold text-primary hover:bg-layer-transparent-hover"
        render={<button type="button" aria-label="Pick date" />}
      >
        {label}
        <ChevronDown className="size-3.5 text-tertiary" />
      </Popover.Button>
      <Popover.Panel
        side="bottom"
        align="start"
        positionerClassName="z-30"
        className="rounded-lg border border-subtle bg-surface-1 shadow-raised-200"
      >
        <div className="flex items-center justify-between px-3 pt-3">
          <button
            type="button"
            className="grid size-6 place-items-center rounded-sm hover:bg-layer-transparent-hover"
            onClick={() => setCursor((c) => new Date(c.getFullYear() - 1, c.getMonth(), 1))}
            aria-label="Previous year"
          >
            <ChevronLeft className="size-4" />
          </button>
          <span className="text-13 font-semibold text-primary">{year}</span>
          <button
            type="button"
            className="grid size-6 place-items-center rounded-sm hover:bg-layer-transparent-hover"
            onClick={() => setCursor((c) => new Date(c.getFullYear() + 1, c.getMonth(), 1))}
            aria-label="Next year"
          >
            <ChevronRight className="size-4" />
          </button>
        </div>
        <div className="grid grid-cols-4 gap-1 px-3 py-2">
          {Object.entries(MONTHS_LIST).map(([monthNumber, month]) => {
            const monthIndex = Number(monthNumber) - 1;
            const isActive = anchor.getFullYear() === year && anchor.getMonth() === monthIndex;
            return (
              <button
                key={monthNumber}
                type="button"
                className={cn(
                  "rounded-sm px-2 py-1.5 text-12 font-medium hover:bg-layer-transparent-hover",
                  isActive ? "bg-accent-primary text-on-color hover:bg-accent-primary" : "text-secondary"
                )}
                onClick={() => pick(new Date(year, monthIndex, 1))}
              >
                {month.shortTitle}
              </button>
            );
          })}
        </div>
        <div className="border-t border-subtle">
          <Calendar
            mode="single"
            weekStartsOn={1}
            selected={anchor}
            month={cursor}
            onMonthChange={setCursor}
            onSelect={(date) => date && pick(date)}
          />
        </div>
      </Popover.Panel>
    </Popover>
  );
}
