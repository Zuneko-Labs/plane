/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { redirect } from "react-router";
import type { Route } from "./+types/page";

// Approvals moved to one workspace-wide page covering every project (see
// app/(all)/[workspaceSlug]/(projects)/approvals) - keep old links working.
export function clientLoader({ params }: Route.ClientLoaderArgs) {
  throw redirect(`/${params.workspaceSlug}/approvals`);
}

export default function ProjectApprovalsRedirect() {
  return null;
}
