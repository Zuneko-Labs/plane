/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useParams } from "next/navigation";
import { EUserPermissions } from "@plane/constants";
import { useUserPermissions } from "@/hooks/store/user";

/**
 * Whether the current user approves work items in at least one project of
 * the workspace — a project Admin (mirrors plane.utils.approval
 * .is_project_approver). Drives the workspace Approvals page and its
 * sidebar entry. Call from an observer component.
 */
export const useIsApproverInAnyProject = (workspaceSlug?: string) => {
  const params = useParams();
  const slug = workspaceSlug ?? params.workspaceSlug?.toString();
  const { workspaceProjectsPermissions } = useUserPermissions();
  if (!slug) return false;
  const projectRoles = workspaceProjectsPermissions?.[slug] ?? {};
  return Object.values(projectRoles).some((role) => role === EUserPermissions.ADMIN);
};
