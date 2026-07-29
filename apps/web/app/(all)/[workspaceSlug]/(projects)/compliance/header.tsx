/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// plane imports
import { ClipboardList } from "lucide-react";
import { Breadcrumbs, Header } from "@plane/ui";
// components
import { BreadcrumbLink } from "@/components/common/breadcrumb-link";

export function ComplianceHeader() {
  return (
    <Header>
      <Header.LeftItem>
        <div className="flex items-center gap-2.5">
          <Breadcrumbs>
            <Breadcrumbs.Item
              component={
                <BreadcrumbLink label="Compliance" icon={<ClipboardList className="size-4 text-secondary" />} />
              }
            />
          </Breadcrumbs>
        </div>
      </Header.LeftItem>
    </Header>
  );
}
