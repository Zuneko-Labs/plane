/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useMemo, useState } from "react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
import useSWR from "swr";
import { Search } from "lucide-react";
// plane imports
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import type { TComplianceCadence, TComplianceTemplate } from "@plane/types";
import { cn } from "@plane/utils";
// hooks
import { useCompliance } from "@/hooks/store/use-compliance";
import { useProject } from "@/hooks/store/use-project";
// local
import { COMPLIANCE_CADENCE_LABELS } from "./constants";

// Columns are grouped by how often the work recurs — the one property every
// template has in a consistent form — so related deadlines sit together.
const CADENCE_ORDER: TComplianceCadence[] = ["monthly", "quarterly", "advance_tax", "annual"];
const SHORT_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const ordinal = (day: number) => {
  const mod100 = day % 100;
  if (mod100 >= 11 && mod100 <= 13) return `${day}th`;
  return `${day}${{ 1: "st", 2: "nd", 3: "rd" }[day % 10] ?? "th"}`;
};

const dueLabel = (template: TComplianceTemplate) => {
  if (template.cadence === "annual" && template.due_month) {
    return `Due ${template.due_day} ${SHORT_MONTHS[template.due_month - 1]}`;
  }
  if (template.cadence === "monthly" && template.due_day >= 28) return "Due month-end";
  return `Due ${ordinal(template.due_day)}`;
};

const byName = (a: string, b: string) => a.localeCompare(b, undefined, { sensitivity: "base" });

export const ApplicabilityGrid = observer(function ApplicabilityGrid() {
  const { workspaceSlug } = useParams();
  const { templates, fetchCategoriesAndTemplates, toggleApplicability } = useCompliance();
  const { workspaceProjectIds, getProjectById } = useProject();
  const [search, setSearch] = useState("");

  useSWR(
    workspaceSlug ? `COMPLIANCE_APPLICABILITY_${workspaceSlug}` : null,
    workspaceSlug ? () => fetchCategoriesAndTemplates(workspaceSlug.toString()) : null
  );

  const projects = useMemo(() => {
    const list = (workspaceProjectIds ?? [])
      .map((id) => getProjectById(id))
      .filter((project): project is NonNullable<typeof project> => Boolean(project));
    // eslint-disable-next-line unicorn/no-array-sort -- `.filter()` above always returns a fresh array, so sorting it in place is safe; `toSorted()` isn't available in this project's configured TS lib target
    return list.sort((a, b) => byName(a.name, b.name));
  }, [workspaceProjectIds, getProjectById]);

  const filteredProjects = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return projects;
    return projects.filter(
      (project) => project.name.toLowerCase().includes(query) || project.identifier.toLowerCase().includes(query)
    );
  }, [projects, search]);

  const cadenceGroups = useMemo(() => {
    const active = templates.filter((template) => template.is_active);
    return CADENCE_ORDER.map((cadence) => {
      const groupTemplates = active.filter((template) => template.cadence === cadence);
      // eslint-disable-next-line unicorn/no-array-sort -- `.filter()` above always returns a fresh array, so sorting it in place is safe; `toSorted()` isn't available in this project's configured TS lib target
      return { cadence, templates: groupTemplates.sort((a, b) => byName(a.title, b.title)) };
    }).filter((group) => group.templates.length > 0);
  }, [templates]);

  const columns = useMemo(
    () =>
      cadenceGroups.flatMap((group) =>
        group.templates.map((template, index) => ({ template, isGroupStart: index === 0 }))
      ),
    [cadenceGroups]
  );

  const handleToggle = async (templateId: string, projectId: string, applicable: boolean) => {
    if (!workspaceSlug) return;
    try {
      await toggleApplicability(workspaceSlug.toString(), templateId, projectId, applicable);
    } catch (error) {
      const err = error as { error?: string };
      setToast({
        type: TOAST_TYPE.ERROR,
        title: "Error!",
        message: err?.error ?? "Something went wrong. Please try again.",
      });
    }
  };

  if (columns.length === 0) {
    return <p className="text-13 text-secondary">Create a template first to set up applicability.</p>;
  }

  return (
    <div className="flex w-full flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h4 className="text-16 font-medium text-primary">Applicability</h4>
          <p className="text-13 text-secondary">
            Tick the recurring compliances that apply to each project. Changes save instantly.
          </p>
        </div>
        <label className="flex w-full items-center gap-2 rounded-md border border-subtle bg-layer-1 px-2.5 py-1.5 sm:w-64">
          <Search className="size-3.5 shrink-0 text-tertiary" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search projects"
            aria-label="Search projects"
            className="w-full bg-transparent text-13 text-primary outline-none placeholder:text-placeholder"
          />
        </label>
      </div>

      <div className="max-h-[70vh] overflow-auto rounded-md border border-subtle">
        <table className="w-full border-separate border-spacing-0 text-13">
          <thead>
            {/* Row 1: frequency groups */}
            <tr>
              <th
                rowSpan={2}
                className="sticky top-0 left-0 z-30 min-w-60 border-r border-b border-subtle bg-layer-1 px-3 text-left align-bottom text-12 font-medium text-secondary"
              >
                <div className="pb-2">Project</div>
              </th>
              {cadenceGroups.map((group) => (
                <th
                  key={group.cadence}
                  colSpan={group.templates.length}
                  className="sticky top-0 z-20 h-8 border-b border-l border-subtle bg-layer-1 px-3 text-left text-11 font-semibold tracking-wide text-tertiary uppercase"
                >
                  {COMPLIANCE_CADENCE_LABELS[group.cadence]}
                </th>
              ))}
            </tr>
            {/* Row 2: compliance titles with their due date */}
            <tr>
              {columns.map(({ template, isGroupStart }) => (
                <th
                  key={template.id}
                  title={template.category_detail?.name ? `Category: ${template.category_detail.name}` : undefined}
                  className={cn(
                    "font-normal sticky top-8 z-20 min-w-24 border-b border-subtle bg-layer-1 px-2 py-2 text-center align-bottom",
                    isGroupStart && "border-l"
                  )}
                >
                  <div className="text-13 font-medium whitespace-nowrap text-primary">{template.title}</div>
                  <div className="text-11 whitespace-nowrap text-tertiary">{dueLabel(template)}</div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filteredProjects.map((project) => {
              const appliedCount = columns.filter(({ template }) =>
                template.applicable_project_ids.includes(project.id)
              ).length;
              return (
                <tr key={project.id} className="group">
                  <td className="sticky left-0 z-10 border-r border-b border-subtle bg-canvas px-3 py-2 group-hover:bg-layer-1">
                    <div className="flex items-center justify-between gap-3">
                      <div className="flex min-w-0 items-center gap-2">
                        <span className="truncate font-medium text-primary" title={project.name}>
                          {project.name}
                        </span>
                        <span className="shrink-0 rounded-sm bg-layer-2 px-1.5 py-0.5 text-11 text-tertiary">
                          {project.identifier}
                        </span>
                      </div>
                      <span
                        className={cn("shrink-0 text-11", appliedCount > 0 ? "text-secondary" : "text-placeholder")}
                        title={`${appliedCount} of ${columns.length} compliances apply`}
                      >
                        {appliedCount}/{columns.length}
                      </span>
                    </div>
                  </td>
                  {columns.map(({ template, isGroupStart }) => {
                    const isApplicable = template.applicable_project_ids.includes(project.id);
                    return (
                      <td
                        key={template.id}
                        className={cn(
                          "border-b border-subtle p-0 text-center group-hover:bg-layer-1",
                          isGroupStart && "border-l"
                        )}
                      >
                        <label className="flex h-10 w-full cursor-pointer items-center justify-center">
                          <input
                            type="checkbox"
                            checked={isApplicable}
                            onChange={(e) => handleToggle(template.id, project.id, e.target.checked)}
                            aria-label={`${template.title} for ${project.name}`}
                            className="accent-brand-solid size-4 cursor-pointer"
                          />
                        </label>
                      </td>
                    );
                  })}
                </tr>
              );
            })}
            {filteredProjects.length === 0 && (
              <tr>
                <td colSpan={columns.length + 1} className="px-3 py-6 text-center text-13 text-secondary">
                  No projects match &ldquo;{search}&rdquo;.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
});
