/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
// plane imports
import { Button } from "@plane/propel/button";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
// hooks
import { useCompliance } from "@/hooks/store/use-compliance";

// Matches the Celery Beat schedule wired in apps/api/plane/celery.py
// ("check-every-day-to-generate-compliance-issues").
const ENGINE_SCHEDULE_LABEL = "04:15 UTC";

export const EngineControls = observer(function EngineControls() {
  const { workspaceSlug } = useParams();
  const { triggerGenerate } = useCompliance();
  const [isGenerating, setIsGenerating] = useState(false);

  const handleGenerateNow = async () => {
    if (!workspaceSlug) return;
    setIsGenerating(true);
    try {
      const summary = await triggerGenerate(workspaceSlug.toString());
      setToast({
        type: TOAST_TYPE.SUCCESS,
        title: "Done",
        message: `Created ${summary.created}, skipped ${summary.skipped}, failed ${summary.failed}.`,
      });
    } catch (error) {
      const err = error as { error?: string };
      setToast({
        type: TOAST_TYPE.ERROR,
        title: "Error!",
        message: err?.error ?? "Something went wrong. Please try again.",
      });
    } finally {
      setIsGenerating(false);
    }
  };

  return (
    <div className="flex items-center justify-between rounded-md border-[0.5px] border-subtle px-4 py-3">
      <span className="text-13 text-secondary">Engine auto-runs · {ENGINE_SCHEDULE_LABEL}</span>
      <Button variant="primary" onClick={handleGenerateNow} loading={isGenerating}>
        {isGenerating ? "Generating..." : "Generate now"}
      </Button>
    </div>
  );
});
