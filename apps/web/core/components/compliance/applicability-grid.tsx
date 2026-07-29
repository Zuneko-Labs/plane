/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useMemo } from "react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
import useSWR from "swr";
// plane imports
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@plane/propel/table";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
// hooks
import { useCompliance } from "@/hooks/store/use-compliance";
import { useProject } from "@/hooks/store/use-project";

export const ApplicabilityGrid = observer(function ApplicabilityGrid() {
  const { workspaceSlug } = useParams();
  const { templates, fetchCategoriesAndTemplates, toggleApplicability } = useCompliance();
  const { workspaceProjectIds, getProjectById } = useProject();

  useSWR(
    workspaceSlug ? `COMPLIANCE_APPLICABILITY_${workspaceSlug}` : null,
    workspaceSlug ? () => fetchCategoriesAndTemplates(workspaceSlug.toString()) : null
  );

  const projects = useMemo(
    () => (workspaceProjectIds ?? []).map((id) => getProjectById(id)).filter(Boolean),
    [workspaceProjectIds, getProjectById]
  );

  const activeTemplates = useMemo(() => templates.filter((template) => template.is_active), [templates]);

  const categoryGroups = useMemo(() => {
    const groups = new Map<string, typeof activeTemplates>();
    activeTemplates.forEach((template) => {
      const categoryName = template.category_detail?.name ?? "";
      const existing = groups.get(categoryName) ?? [];
      existing.push(template);
      groups.set(categoryName, existing);
    });
    return Array.from(groups.entries());
  }, [activeTemplates]);

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

  if (activeTemplates.length === 0) {
    return <p className="text-13 text-secondary">Create a template first to set up applicability.</p>;
  }

  return (
    <div className="flex w-full flex-col gap-4">
      <div>
        <h4 className="text-16 font-medium text-primary">Applicability</h4>
        <p className="text-13 text-secondary">
          Which recurring compliances apply to each project. Changes save instantly.
        </p>
      </div>
      <Table className="border-[0.5px] border-subtle">
        <TableHeader>
          <TableRow>
            <TableHead rowSpan={2} className="sticky left-0 bg-layer-1">
              Project
            </TableHead>
            {categoryGroups.map(([categoryName, groupTemplates]) => (
              <TableHead key={categoryName} colSpan={groupTemplates.length} className="text-center">
                {categoryName}
              </TableHead>
            ))}
          </TableRow>
          <TableRow>
            {categoryGroups.flatMap(([categoryName, groupTemplates]) =>
              groupTemplates.map((template) => (
                <TableHead key={`${categoryName}-${template.id}`} className="text-center whitespace-nowrap">
                  {template.title}
                </TableHead>
              ))
            )}
          </TableRow>
        </TableHeader>
        <TableBody>
          {projects.map((project) => (
            <TableRow key={project!.id}>
              <TableCell className="sticky left-0 bg-canvas font-medium text-primary">
                {project!.name} <span className="text-tertiary">{project!.identifier}</span>
              </TableCell>
              {categoryGroups.flatMap(([categoryName, groupTemplates]) =>
                groupTemplates.map((template) => {
                  const isApplicable = template.applicable_project_ids.includes(project!.id);
                  return (
                    <TableCell key={`${categoryName}-${template.id}-${project!.id}`} className="text-center">
                      <input
                        type="checkbox"
                        checked={isApplicable}
                        onChange={(e) => handleToggle(template.id, project!.id, e.target.checked)}
                        className="accent-brand-solid size-4 cursor-pointer"
                      />
                    </TableCell>
                  );
                })
              )}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
});
