/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { ReactNode } from "react";
import Link from "next/link";
import { Tooltip } from "@plane/propel/tooltip";
import type { TApprovalModuleRef } from "@/services/approval-gate.service";

export const TH_CLASS =
  "h-11 min-w-36 border border-t-0 border-b-0 border-subtle bg-layer-1 px-4 text-left text-13 font-medium";
export const TD_CLASS = "h-11 min-w-36 border-r-[0.5px] border-b-[0.5px] border-subtle px-4 text-13";

export const formatApprovalDate = (dateString: string) =>
  new Date(dateString).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });

export const workItemLink = (workspaceSlug: string, projectId: string, issueId: string) =>
  `/${workspaceSlug}/projects/${projectId}/issues/${issueId}`;

/** Sticky first column: identifier + name, linking to the work item. */
export const WorkItemHeaderCell = () => (
  <th className="left-0 z-[15] h-11 min-w-60 border-r-[0.5px] border-subtle bg-layer-1 text-13 font-medium md:sticky">
    <div className="flex h-full w-full items-center px-page-x">Work items</div>
  </th>
);

export const WorkItemCell = (props: {
  href: string;
  projectIdentifier: string | null;
  sequenceId: number;
  name: string;
}) => {
  const { href, projectIdentifier, sequenceId, name } = props;
  return (
    <td className="left-0 z-[15] h-11 min-w-60 border-r-[0.5px] border-b-[0.5px] border-subtle bg-surface-1 md:sticky">
      <Link href={href} className="flex h-full w-full items-center gap-2 px-page-x hover:underline">
        <span className="flex-shrink-0 text-13 text-tertiary">
          {projectIdentifier ? `${projectIdentifier}-${sequenceId}` : `#${sequenceId}`}
        </span>
        <span className="truncate text-13 text-primary">{name}</span>
      </Link>
    </td>
  );
};

export const ProjectCell = ({ name }: { name: string | null }) => (
  <td className={TD_CLASS}>
    {name ? <span className="block truncate text-secondary">{name}</span> : <span className="text-tertiary">-</span>}
  </td>
);

export const ModulesCell = ({ modules }: { modules: TApprovalModuleRef[] }) => (
  <td className={TD_CLASS}>
    {modules.length > 0 ? (
      <Tooltip tooltipContent={modules.map((module) => module.name).join(", ")}>
        <span className="block truncate text-secondary">
          {modules.length === 1 ? modules[0].name : `${modules.length} modules`}
        </span>
      </Tooltip>
    ) : (
      <span className="text-tertiary">No module</span>
    )}
  </td>
);

export const ApprovalEmptyState = (props: { icon: ReactNode; title: string; description: string }) => (
  <div className="flex h-full flex-col items-center justify-center gap-3 py-16 text-center">
    <div className="flex h-14 w-14 items-center justify-center rounded-full bg-layer-1">{props.icon}</div>
    <div>
      <h3 className="text-base font-medium text-primary">{props.title}</h3>
      <p className="mt-1 text-13 text-tertiary">{props.description}</p>
    </div>
  </div>
);

export const ApprovalLoadingState = ({ label }: { label: string }) => (
  <div className="flex h-full items-center justify-center text-13 text-tertiary">{label}&hellip;</div>
);
