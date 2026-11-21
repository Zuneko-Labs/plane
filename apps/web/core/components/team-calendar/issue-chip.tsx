/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import Link from "next/link";
// plane imports
import { STATE_GROUPS } from "@plane/constants";
import { Tooltip } from "@plane/propel/tooltip";
import { Avatar } from "@plane/ui";
import { getFileURL } from "@plane/utils";
// services
import type { TTeamCalendarIssue, TTeamCalendarMember } from "@/services/team-calendar.service";

export const getIssueColor = (issue: TTeamCalendarIssue): string =>
  issue.state_color ??
  STATE_GROUPS[issue.state_group as keyof typeof STATE_GROUPS]?.color ??
  STATE_GROUPS.backlog.color;

type TIssueChipProps = {
  workspaceSlug: string;
  issue: TTeamCalendarIssue;
  member: Pick<TTeamCalendarMember, "display_name" | "avatar_url">;
  showAvatar?: boolean;
};

/** Compact one-line pill used in month cells and "+N more" lists. */
export function IssueChip({ workspaceSlug, issue, member, showAvatar = true }: TIssueChipProps) {
  const color = getIssueColor(issue);
  return (
    <Tooltip
      tooltipHeading={`${issue.project_identifier}-${issue.sequence_id}`}
      tooltipContent={`${issue.name} · ${member.display_name} (${issue.start_date ?? "—"} → ${issue.target_date ?? "—"})`}
    >
      <Link
        href={`/${workspaceSlug}/projects/${issue.project_id}/issues/${issue.id}`}
        className="flex h-5 w-full min-w-0 items-center gap-1 overflow-hidden rounded-[4px] px-1 text-11 leading-none text-primary hover:brightness-95"
        style={{ backgroundColor: `${color}26`, borderLeft: `3px solid ${color}` }}
      >
        {showAvatar && (
          <span className="shrink-0">
            <Avatar name={member.display_name} src={getFileURL(member.avatar_url ?? "")} size={14} />
          </span>
        )}
        <span className="truncate font-medium">{issue.name}</span>
      </Link>
    </Tooltip>
  );
}
