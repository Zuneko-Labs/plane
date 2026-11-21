/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useMemo } from "react";
import { format, parseISO } from "date-fns";
import Link from "next/link";
// plane imports
import { STATE_GROUPS } from "@plane/constants";
import { Popover } from "@plane/propel/popover";
import { Tooltip } from "@plane/propel/tooltip";
import { Avatar } from "@plane/ui";
import { cn, getFileURL } from "@plane/utils";
// services
import type { TTeamCalendarIssue, TTeamCalendarMember } from "@/services/team-calendar.service";
// local imports
import { IssueChip } from "./issue-chip";
import type { TIssueBarPlacement } from "./utils";
import { computeBarPlacements, DATE_FORMAT } from "./utils";

const MEMBER_COLUMN_WIDTH = 240;
const BAR_HEIGHT = 34;
const ROW_VERTICAL_PADDING = 8;
const MIN_ROW_HEIGHT = 44;
const MAX_LANES = 3;
const MORE_ROW_HEIGHT = 22;

const hexToRgb = (hex: string): [number, number, number] | null => {
  const match = hex.replace("#", "").match(/^([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i);
  return match ? [parseInt(match[1], 16), parseInt(match[2], 16), parseInt(match[3], 16)] : null;
};

const getBarColor = (issue: TTeamCalendarIssue): string =>
  issue.state_color ??
  STATE_GROUPS[issue.state_group as keyof typeof STATE_GROUPS]?.color ??
  STATE_GROUPS.backlog.color;

const getBarBg = (color: string): string => {
  const rgb = hexToRgb(color);
  return rgb ? `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, 0.12)` : "transparent";
};

type IssueBarProps = {
  workspaceSlug: string;
  placement: TIssueBarPlacement;
  dayCount: number;
};

function IssueBar({ workspaceSlug, placement, dayCount }: IssueBarProps) {
  const { issue, startIndex, endIndex, lane, clippedStart, clippedEnd } = placement;
  const left = (startIndex / dayCount) * 100;
  const width = ((endIndex - startIndex + 1) / dayCount) * 100;

  const barColor = getBarColor(issue);

  return (
    <Tooltip
      tooltipHeading={`${issue.project_identifier}-${issue.sequence_id}`}
      tooltipContent={`${issue.name} (${issue.start_date ?? "—"} → ${issue.target_date ?? "—"})`}
    >
      <Link
        href={`/${workspaceSlug}/projects/${issue.project_id}/issues/${issue.id}`}
        className={cn(
          "shadow-sm absolute flex flex-col justify-center overflow-hidden border border-subtle px-2 py-0.5 text-left",
          clippedStart ? "border-l-dashed rounded-l-none border-l-2" : "rounded-l-md",
          clippedEnd ? "border-r-dashed rounded-r-none border-r-2" : "rounded-r-md"
        )}
        style={{
          left: `calc(${left}% + 2px)`,
          width: `calc(${width}% - 4px)`,
          top: ROW_VERTICAL_PADDING / 2 + lane * (BAR_HEIGHT + 4),
          height: BAR_HEIGHT,
          borderLeftColor: barColor,
          borderLeftWidth: 3,
          backgroundColor: getBarBg(barColor),
        }}
      >
        <span className="truncate text-12 font-medium text-primary">{issue.name}</span>
        <span className="truncate text-10 text-tertiary">
          {issue.project_identifier}-{issue.sequence_id}
        </span>
      </Link>
    </Tooltip>
  );
}

type MemberRowProps = {
  workspaceSlug: string;
  member: TTeamCalendarMember;
  weekDays: string[];
  today: string;
};

function MemberRow({ workspaceSlug, member, weekDays, today }: MemberRowProps) {
  const placements = useMemo(() => computeBarPlacements(member.issues, weekDays), [member.issues, weekDays]);
  // cap visible lanes so busy members do not blow the row up; the rest go behind "+N more"
  const visiblePlacements = placements.filter((placement) => placement.lane < MAX_LANES);
  const hiddenPlacements = placements.filter((placement) => placement.lane >= MAX_LANES);
  const laneCount = visiblePlacements.reduce((max, placement) => Math.max(max, placement.lane + 1), 0);
  const rowHeight = Math.max(
    MIN_ROW_HEIGHT,
    laneCount * (BAR_HEIGHT + 4) + ROW_VERTICAL_PADDING + (hiddenPlacements.length > 0 ? MORE_ROW_HEIGHT : 0)
  );

  return (
    <div className="flex border-b border-subtle" style={{ minHeight: rowHeight }}>
      <div
        className="sticky left-0 z-[2] flex flex-shrink-0 items-start gap-2 border-r border-subtle bg-surface-1 px-3 py-2.5"
        style={{ width: MEMBER_COLUMN_WIDTH }}
      >
        <Avatar name={member.display_name} src={getFileURL(member.avatar_url ?? "")} />
        <span className="truncate text-13 font-medium text-primary">{member.display_name}</span>
      </div>
      <div className="relative flex-grow">
        <div className="absolute inset-0 flex">
          {weekDays.map((day) => (
            <div
              key={day}
              className={cn("h-full flex-1 border-r border-subtle last:border-r-0", {
                "bg-layer-transparent-hover": day === today,
              })}
            />
          ))}
        </div>
        <div className="relative" style={{ height: rowHeight }}>
          {visiblePlacements.map((placement) => (
            <IssueBar
              key={`${placement.issue.id}-${placement.lane}`}
              workspaceSlug={workspaceSlug}
              placement={placement}
              dayCount={weekDays.length}
            />
          ))}
          {hiddenPlacements.length > 0 && (
            <div className="absolute right-1 bottom-0.5">
              <Popover>
                <Popover.Button
                  className="rounded-sm bg-layer-1 px-1.5 text-11 font-medium text-secondary hover:bg-layer-1-hover"
                  render={<button type="button" />}
                >
                  +{hiddenPlacements.length} more
                </Popover.Button>
                <Popover.Panel
                  side="bottom"
                  align="end"
                  positionerClassName="z-30"
                  className="w-72 rounded-lg border border-subtle bg-surface-1 p-2 shadow-raised-200"
                >
                  <p className="px-1 pb-1.5 text-12 font-semibold text-primary">{member.display_name}</p>
                  <div className="flex max-h-72 flex-col gap-1 overflow-y-auto">
                    {placements.map((placement) => (
                      <IssueChip
                        key={placement.issue.id}
                        workspaceSlug={workspaceSlug}
                        issue={placement.issue}
                        member={member}
                        showAvatar={false}
                      />
                    ))}
                  </div>
                </Popover.Panel>
              </Popover>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

type TeamCalendarGridProps = {
  workspaceSlug: string;
  members: TTeamCalendarMember[];
  weekDays: string[];
};

export function TeamCalendarGrid({ workspaceSlug, members, weekDays }: TeamCalendarGridProps) {
  const today = format(new Date(), DATE_FORMAT);

  return (
    <div className="flex h-full flex-col overflow-auto">
      <div className="min-w-[900px]">
        {/* header row */}
        <div className="sticky top-0 z-[3] flex border-b border-subtle bg-surface-1">
          <div
            className="sticky left-0 z-[2] flex-shrink-0 border-r border-subtle bg-surface-1 px-3 py-2 text-11 font-semibold text-tertiary"
            style={{ width: MEMBER_COLUMN_WIDTH }}
          >
            Member
          </div>
          <div className="flex flex-grow">
            {weekDays.map((day) => (
              <div
                key={day}
                className={cn(
                  "flex-1 border-r border-subtle px-2 py-2 text-center text-11 font-semibold text-tertiary last:border-r-0",
                  { "text-accent-primary": day === today }
                )}
              >
                {format(parseISO(day), "d EEE")}
              </div>
            ))}
          </div>
        </div>
        {/* member rows */}
        {members.map((member) => (
          <MemberRow key={member.id} workspaceSlug={workspaceSlug} member={member} weekDays={weekDays} today={today} />
        ))}
        {members.length === 0 && (
          <div className="flex items-center justify-center py-16 text-13 text-tertiary">
            No members found for the selected filters.
          </div>
        )}
      </div>
    </div>
  );
}
