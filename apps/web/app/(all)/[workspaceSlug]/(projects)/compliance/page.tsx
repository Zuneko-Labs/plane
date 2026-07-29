/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
// components
import { ApplicabilityGrid, TemplatesList } from "@/components/compliance";
import { PageHead } from "@/components/core/page-title";

type TComplianceView = "templates" | "applicability";

export default function CompliancePage() {
  const [view, setView] = useState<TComplianceView>("templates");

  return (
    <>
      <PageHead title="Compliance" />
      <div className="flex h-full w-full flex-col overflow-y-auto px-page-x py-page-y">
        <div className="mb-4 flex items-center gap-1 border-b border-subtle">
          <button
            type="button"
            onClick={() => setView("templates")}
            className={`border-b-2 px-3 py-2 text-14 font-medium ${
              view === "templates"
                ? "border-accent-strong text-primary"
                : "border-transparent text-secondary hover:text-primary"
            }`}
          >
            Recurring Templates
          </button>
          <button
            type="button"
            onClick={() => setView("applicability")}
            className={`border-b-2 px-3 py-2 text-14 font-medium ${
              view === "applicability"
                ? "border-accent-strong text-primary"
                : "border-transparent text-secondary hover:text-primary"
            }`}
          >
            Applicability
          </button>
        </div>

        {view === "templates" ? <TemplatesList /> : <ApplicabilityGrid />}
      </div>
    </>
  );
}
