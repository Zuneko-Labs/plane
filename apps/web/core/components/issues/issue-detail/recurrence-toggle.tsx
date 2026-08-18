/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
import { Repeat } from "lucide-react";
// plane imports
import { useTranslation } from "@plane/i18n";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import type { TIssueRecurrenceDetail } from "@plane/types";
import { ToggleSwitch } from "@plane/ui";
// components
import { SidebarPropertyListItem } from "@/components/common/layout/sidebar/property-list-item";
// services
import { IssueService } from "@/services/issue/issue.service";

const issueService = new IssueService();

type Props = {
  workspaceSlug: string;
  projectId: string;
  issueId: string;
  disabled?: boolean;
};

export function IssueRecurrenceToggle(props: Props) {
  const { workspaceSlug, projectId, issueId, disabled } = props;
  const { t } = useTranslation();
  // state
  const [recurrence, setRecurrence] = useState<TIssueRecurrenceDetail | null>(null);
  const [isUpdating, setIsUpdating] = useState(false);

  useEffect(() => {
    let ignore = false;

    const fetchRecurrence = async () => {
      try {
        const res = await issueService.getIssueRecurrence(workspaceSlug, projectId, issueId);
        if (!ignore) setRecurrence(res?.recurrence ?? null);
      } catch {
        // No recurrence / not accessible — leave the row hidden.
      }
    };
    fetchRecurrence();

    return () => {
      ignore = true;
    };
  }, [workspaceSlug, projectId, issueId]);

  // Only recurring work items get this row.
  if (!recurrence) return null;

  const handleToggle = async (nextValue: boolean) => {
    const previous = recurrence;
    // optimistic update
    setRecurrence({ ...recurrence, is_active: nextValue });
    setIsUpdating(true);
    try {
      const res = await issueService.updateIssueRecurrence(workspaceSlug, projectId, issueId, {
        is_active: nextValue,
      });
      setRecurrence(res?.recurrence ?? { ...recurrence, is_active: nextValue });
    } catch {
      // revert on failure
      setRecurrence(previous);
      setToast({
        type: TOAST_TYPE.ERROR,
        title: t("error"),
        message: t("something_went_wrong"),
      });
    } finally {
      setIsUpdating(false);
    }
  };

  return (
    <SidebarPropertyListItem icon={Repeat} label={t("recurring")}>
      <div className="flex h-7.5 items-center gap-2" title={t("recurring_active_description")}>
        <ToggleSwitch
          value={recurrence.is_active}
          onChange={handleToggle}
          disabled={disabled || isUpdating}
          size="sm"
        />
      </div>
    </SidebarPropertyListItem>
  );
}
