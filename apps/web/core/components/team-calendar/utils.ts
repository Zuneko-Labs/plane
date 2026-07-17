/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { addDays, format, startOfWeek } from "date-fns";
// services
import type { TTeamCalendarIssue } from "@/services/team-calendar.service";

export const DATE_FORMAT = "yyyy-MM-dd";

export const getWeekDays = (anchor: Date): string[] => {
  const weekStart = startOfWeek(anchor, { weekStartsOn: 1 });
  return Array.from({ length: 7 }, (_, index) => format(addDays(weekStart, index), DATE_FORMAT));
};

export type TIssueBarPlacement = {
  issue: TTeamCalendarIssue;
  /** 0-based day column the bar starts in */
  startIndex: number;
  /** 0-based day column the bar ends in (inclusive) */
  endIndex: number;
  /** vertical lane within the member row */
  lane: number;
  /** the item extends before the visible week */
  clippedStart: boolean;
  /** the item extends after the visible week */
  clippedEnd: boolean;
};

/**
 * Lays out a member's issues as bars in the visible week: clamps each issue's
 * date range to the week and assigns non-overlapping vertical lanes.
 * Dates are compared as ISO yyyy-MM-dd strings, which sort lexicographically.
 */
export const computeBarPlacements = (issues: TTeamCalendarIssue[], weekDays: string[]): TIssueBarPlacement[] => {
  const weekStart = weekDays[0];
  const weekEnd = weekDays[weekDays.length - 1];

  const bars = issues
    .map((issue) => {
      // Use effective_start_date (which falls back to created_at on the backend),
      // then fall back to start_date, then target_date.
      const effectiveStart = issue.effective_start_date ?? issue.start_date ?? issue.target_date;
      // If only start exists (no due date), bar extends to end of week.
      const effectiveEnd = issue.target_date ?? (issue.start_date ? weekEnd : null);
      if (!effectiveStart || !effectiveEnd) return null;
      if (effectiveEnd < weekStart || effectiveStart > weekEnd) return null;

      const clippedStart = effectiveStart < weekStart;
      const clippedEnd = effectiveEnd > weekEnd;
      const startIndex = clippedStart ? 0 : weekDays.indexOf(effectiveStart);
      const endIndex = clippedEnd ? weekDays.length - 1 : weekDays.indexOf(effectiveEnd);
      if (startIndex === -1 || endIndex === -1) return null;

      return { issue, startIndex, endIndex, lane: 0, clippedStart, clippedEnd };
    })
    .filter((bar): bar is TIssueBarPlacement => bar !== null);

  // Greedy lane assignment: earliest-starting bars first, each takes the
  // first lane that is free at its start column.
  bars.sort((a, b) => a.startIndex - b.startIndex || a.endIndex - b.endIndex);
  const laneEnds: number[] = [];
  for (const bar of bars) {
    let lane = laneEnds.findIndex((end) => end < bar.startIndex);
    if (lane === -1) {
      lane = laneEnds.length;
      laneEnds.push(bar.endIndex);
    } else {
      laneEnds[lane] = bar.endIndex;
    }
    bar.lane = lane;
  }

  return bars;
};
