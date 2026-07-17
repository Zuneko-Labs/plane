/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useMemo, useState, useRef, useEffect, useCallback } from "react";
import { addDays, format, parseISO } from "date-fns";
import { ChevronDown, ChevronLeft, ChevronRight, X } from "lucide-react";
import { CheckIcon } from "@plane/propel/icons";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
import useSWR from "swr";
// plane imports
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
import { Button } from "@plane/propel/button";
import { Spinner } from "@plane/ui";
// components
import { MemberDropdown } from "@/components/dropdowns/member/dropdown";
import { ProjectDropdown } from "@/components/dropdowns/project/dropdown";
// hooks
import { useUserPermissions } from "@/hooks/store/user";
// services
import { teamCalendarService } from "@/services/team-calendar.service";
// local imports
import { TeamCalendarGrid } from "./grid";
import { getWeekDays } from "./utils";

type StatusFilterProps = {
  states: { name: string; color: string }[];
  selected: string[];
  onChange: (names: string[]) => void;
};

function StatusFilter({ states, selected, onChange }: StatusFilterProps) {
  const [isOpen, setIsOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const handleClickOutside = useCallback((e: MouseEvent) => {
    if (ref.current && !ref.current.contains(e.target as Node)) setIsOpen(false);
  }, []);

  useEffect(() => {
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [handleClickOutside]);

  const toggle = (name: string) => {
    onChange(selected.includes(name) ? selected.filter((s) => s !== name) : [...selected, name]);
  };

  const label =
    selected.length === 0 ? "All statuses" : `${selected.length} status${selected.length !== 1 ? "es" : ""}`;

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        className="flex h-[28px] items-center gap-1.5 rounded-md border border-subtle bg-surface-1 px-2.5 text-11 text-secondary hover:bg-layer-2"
        onClick={() => setIsOpen(!isOpen)}
      >
        {selected.length === 0 && <span className="text-tertiary">●</span>}
        {selected.length > 0 && (
          <span
            className="size-2 rounded-full"
            style={{
              backgroundColor: selected.length === 1 ? states.find((s) => s.name === selected[0])?.color : undefined,
            }}
          />
        )}
        <span className="truncate">{label}</span>
        <ChevronDown className="size-3 flex-shrink-0 text-tertiary" />
      </button>
      {isOpen && (
        <div className="absolute top-full left-0 z-20 mt-1 w-48 rounded-md border border-subtle bg-surface-1 py-1 shadow-raised-200">
          <button
            type="button"
            className={`flex w-full items-center justify-between gap-2 px-2.5 py-1.5 text-11 hover:bg-layer-2 ${
              selected.length === 0 ? "text-primary" : "text-secondary"
            }`}
            onClick={() => {
              onChange([]);
              setIsOpen(false);
            }}
          >
            <span className="flex items-center gap-2">
              <span className="bg-tertiary size-2 rounded-full" />
              All statuses
            </span>
            {selected.length === 0 && <CheckIcon className="h-3.5 w-3.5 flex-shrink-0" />}
          </button>
          {states.map((state) => (
            <button
              key={state.name}
              type="button"
              className={`flex w-full items-center justify-between gap-2 px-2.5 py-1.5 text-11 hover:bg-layer-2 ${
                selected.includes(state.name) ? "text-primary" : "text-secondary"
              }`}
              onClick={() => toggle(state.name)}
            >
              <span className="flex items-center gap-2">
                <span className="size-2 flex-shrink-0 rounded-full" style={{ backgroundColor: state.color }} />
                <span className="truncate">{state.name}</span>
              </span>
              {selected.includes(state.name) && <CheckIcon className="h-3.5 w-3.5 flex-shrink-0" />}
            </button>
          ))}
          {states.length === 0 && <p className="px-2.5 py-1.5 text-11 text-placeholder italic">No statuses found</p>}
        </div>
      )}
    </div>
  );
}

export const TeamCalendarRoot = observer(function TeamCalendarRoot() {
  const { workspaceSlug } = useParams();
  const slug = workspaceSlug?.toString() ?? "";
  const { allowPermissions } = useUserPermissions();
  const [weekAnchor, setWeekAnchor] = useState(() => new Date());
  const [selectedProjects, setSelectedProjects] = useState<string[]>([]);
  const [selectedMembers, setSelectedMembers] = useState<string[]>([]);
  const [selectedStates, setSelectedStates] = useState<string[]>([]);

  const isAdmin = allowPermissions([EUserPermissions.ADMIN], EUserPermissionsLevel.WORKSPACE, slug);

  const weekDays = useMemo(() => getWeekDays(weekAnchor), [weekAnchor]);
  const weekStart = weekDays[0];
  const weekEnd = weekDays[weekDays.length - 1];

  const { data, isLoading, error } = useSWR(
    slug && isAdmin ? ["team-calendar", slug, weekStart, selectedProjects.join(","), selectedStates.join(",")] : null,
    () =>
      teamCalendarService.getTeamCalendar(slug, {
        start_date: weekStart,
        end_date: weekEnd,
        ...(selectedProjects.length > 0 ? { project: selectedProjects.join(",") } : {}),
      })
  );

  const availableStates = useMemo(() => {
    const stateMap = new Map<string, { name: string; color: string }>();
    for (const member of data?.members ?? []) {
      for (const issue of member.issues) {
        if (issue.state_name && issue.state_color) {
          const key = issue.state_name;
          if (!stateMap.has(key)) {
            stateMap.set(key, { name: issue.state_name, color: issue.state_color });
          }
        }
      }
    }
    return Array.from(stateMap.values()).toSorted((a, b) => a.name.localeCompare(b.name));
  }, [data]);

  const visibleMembers = useMemo(() => {
    const members = data?.members ?? [];
    const filtered = selectedMembers.length === 0 ? members : members.filter((m) => selectedMembers.includes(m.id));
    if (selectedStates.length === 0) return filtered;
    return filtered.map((member) => {
      const memberIssues = member.issues.filter(
        (issue) => issue.state_name && selectedStates.includes(issue.state_name)
      );
      return Object.assign({}, member, { issues: memberIssues }) as typeof member;
    });
  }, [data, selectedMembers, selectedStates]);

  if (!isAdmin)
    return (
      <div className="flex h-full items-center justify-center text-13 text-tertiary">
        You need to be a workspace admin to access the team calendar.
      </div>
    );

  return (
    <div className="flex h-full flex-col">
      {/* controls */}
      <div className="flex flex-shrink-0 flex-wrap items-center justify-between gap-2 border-b border-subtle px-4 py-3">
        <div className="flex items-center gap-2">
          <button
            type="button"
            className="grid size-7 place-items-center rounded-sm hover:bg-layer-transparent-hover"
            onClick={() => setWeekAnchor((anchor) => addDays(anchor, -7))}
            aria-label="Previous week"
          >
            <ChevronLeft className="size-4" />
          </button>
          <span className="min-w-40 text-center text-13 font-semibold text-primary">
            {format(parseISO(weekStart), "MMM d")} – {format(parseISO(weekEnd), "MMM d, yyyy")}
          </span>
          <button
            type="button"
            className="grid size-7 place-items-center rounded-sm hover:bg-layer-transparent-hover"
            onClick={() => setWeekAnchor((anchor) => addDays(anchor, 7))}
            aria-label="Next week"
          >
            <ChevronRight className="size-4" />
          </button>
          <Button variant="secondary" size="sm" onClick={() => setWeekAnchor(new Date())}>
            Today
          </Button>
        </div>
        <div className="flex items-center gap-2">
          <StatusFilter states={availableStates} selected={selectedStates} onChange={setSelectedStates} />
          <div className="flex items-center gap-1">
            <ProjectDropdown
              multiple
              value={selectedProjects}
              onChange={(val) => setSelectedProjects(val)}
              buttonVariant="border-with-text"
              placeholder="All projects"
              hideIcon
            />
            {selectedProjects.length > 0 && (
              <button
                type="button"
                className="grid size-5 place-items-center rounded-sm text-tertiary hover:bg-layer-transparent-hover hover:text-secondary"
                onClick={() => setSelectedProjects([])}
                aria-label="Clear project filter"
              >
                <X className="size-3" />
              </button>
            )}
          </div>
          <div className="flex items-center gap-1">
            <MemberDropdown
              multiple
              value={selectedMembers}
              onChange={(val) => setSelectedMembers(val)}
              buttonVariant="border-with-text"
              placeholder="All members"
            />
            {selectedMembers.length > 0 && (
              <button
                type="button"
                className="grid size-5 place-items-center rounded-sm text-tertiary hover:bg-layer-transparent-hover hover:text-secondary"
                onClick={() => setSelectedMembers([])}
                aria-label="Clear member filter"
              >
                <X className="size-3" />
              </button>
            )}
          </div>
        </div>
      </div>
      {/* grid */}
      <div className="relative flex-grow overflow-hidden">
        {isLoading && !data ? (
          <div className="grid h-full place-items-center">
            <Spinner />
          </div>
        ) : error ? (
          <div className="flex h-full items-center justify-center text-13 text-tertiary">
            Failed to load the team calendar. Please try again.
          </div>
        ) : (
          <TeamCalendarGrid workspaceSlug={slug} members={visibleMembers} weekDays={weekDays} />
        )}
      </div>
      <div className="flex-shrink-0 border-t border-subtle px-4 py-2 text-11 text-tertiary">
        Bars span from a work item&apos;s start date to its due date.
      </div>
    </div>
  );
});
