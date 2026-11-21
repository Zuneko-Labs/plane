/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useMemo } from "react";
import { format, isSameMonth, parseISO } from "date-fns";
// plane imports
import { Popover } from "@plane/propel/popover";
import { cn } from "@plane/utils";
// services
import type { TTeamCalendarIssue, TTeamCalendarMember } from "@/services/team-calendar.service";
// local imports
import { IssueChip } from "./issue-chip";
import { DATE_FORMAT, getIssueSpan } from "./utils";

const MAX_CHIPS_PER_DAY = 3;
const WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

type TDayItem = { issue: TTeamCalendarIssue; member: TTeamCalendarMember };

type TMonthGridProps = {
  workspaceSlug: string;
  members: TTeamCalendarMember[];
  /** all visible days, full weeks, Monday first */
  days: string[];
  /** any date inside the month being shown */
  anchor: Date;
};

export function MonthGrid({ workspaceSlug, members, days, anchor }: TMonthGridProps) {
  const today = format(new Date(), DATE_FORMAT);
  const windowEnd = days[days.length - 1];

  // day -> items covering that day
  const itemsByDay = useMemo(() => {
    const map = new Map<string, TDayItem[]>();
    for (const day of days) map.set(day, []);
    for (const member of members) {
      for (const issue of member.issues) {
        const span = getIssueSpan(issue, windowEnd);
        if (!span) continue;
        for (const day of days) {
          if (day >= span.start && day <= span.end) map.get(day)?.push({ issue, member });
        }
      }
    }
    return map;
  }, [members, days, windowEnd]);

  const weeks = useMemo(() => {
    const result: string[][] = [];
    for (let i = 0; i < days.length; i += 7) result.push(days.slice(i, i + 7));
    return result;
  }, [days]);

  return (
    <div className="flex h-full min-w-[720px] flex-col overflow-auto">
      <div className="sticky top-0 z-[3] grid flex-shrink-0 grid-cols-7 border-b border-subtle bg-surface-1">
        {WEEKDAY_LABELS.map((label) => (
          <div
            key={label}
            className="border-r border-subtle py-2 text-center text-11 font-semibold text-tertiary uppercase last:border-r-0"
          >
            {label}
          </div>
        ))}
      </div>
      <div className="grid flex-grow" style={{ gridTemplateRows: `repeat(${weeks.length}, minmax(112px, 1fr))` }}>
        {weeks.map((week) => (
          <div key={week[0]} className="grid grid-cols-7 border-b border-subtle last:border-b-0">
            {week.map((day) => {
              const date = parseISO(day);
              const items = itemsByDay.get(day) ?? [];
              const visible = items.slice(0, MAX_CHIPS_PER_DAY);
              const hiddenCount = items.length - visible.length;
              const isToday = day === today;
              const inMonth = isSameMonth(date, anchor);
              const isFirstOfMonth = date.getDate() === 1;
              return (
                <div
                  key={day}
                  className={cn("flex min-w-0 flex-col gap-0.5 border-r border-subtle p-1 last:border-r-0", {
                    "bg-layer-1/40": !inMonth,
                  })}
                >
                  <div className="flex justify-center py-0.5">
                    <span
                      className={cn(
                        "grid h-6 min-w-6 place-items-center rounded-full px-1 text-12 font-medium",
                        isToday ? "bg-accent-primary text-on-color" : inMonth ? "text-primary" : "text-placeholder"
                      )}
                    >
                      {isFirstOfMonth ? format(date, "MMM d") : format(date, "d")}
                    </span>
                  </div>
                  {visible.map(({ issue, member }) => (
                    <IssueChip
                      key={`${member.id}-${issue.id}`}
                      workspaceSlug={workspaceSlug}
                      issue={issue}
                      member={member}
                    />
                  ))}
                  {hiddenCount > 0 && (
                    <Popover>
                      <Popover.Button
                        className="h-5 w-full rounded-[4px] px-1 text-left text-11 font-medium text-secondary hover:bg-layer-1-hover"
                        render={<button type="button" />}
                      >
                        +{hiddenCount} more
                      </Popover.Button>
                      <Popover.Panel
                        side="bottom"
                        align="start"
                        positionerClassName="z-30"
                        className="w-64 rounded-lg border border-subtle bg-surface-1 p-2 shadow-raised-200"
                      >
                        <p className="px-1 pb-1.5 text-12 font-semibold text-primary">{format(date, "EEEE, MMM d")}</p>
                        <div className="flex max-h-72 flex-col gap-1 overflow-y-auto">
                          {items.map(({ issue, member }) => (
                            <IssueChip
                              key={`${member.id}-${issue.id}`}
                              workspaceSlug={workspaceSlug}
                              issue={issue}
                              member={member}
                            />
                          ))}
                        </div>
                      </Popover.Panel>
                    </Popover>
                  )}
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}
