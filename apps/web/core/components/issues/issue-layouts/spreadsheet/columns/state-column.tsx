/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import React from "react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
// types
import type { TIssue } from "@plane/types";
// components
import { StateDropdown } from "@/components/dropdowns/state/dropdown";
// hooks
import { useWorkItemStateTransition } from "@/hooks/use-work-item-state-transition";

type Props = {
  issue: TIssue;
  onClose: () => void;
  onChange: (issue: TIssue, data: Partial<TIssue>, updates: any) => void;
  disabled: boolean;
};

export const SpreadsheetStateColumn = observer(function SpreadsheetStateColumn(props: Props) {
  const { issue, onChange, disabled, onClose } = props;
  const { workspaceSlug } = useParams();
  // approval gate + registrar prompt + sent-back comment, shared by every
  // state-change surface
  const { changeState, stateTransitionModals } = useWorkItemStateTransition({
    workspaceSlug: workspaceSlug?.toString(),
    projectId: issue.project_id,
    workItem: issue,
    // onChange is the (async) spreadsheet update handler - awaited so a
    // refused change surfaces here
    onUpdate: async (data) => await onChange(issue, data, { changed_property: "state", change_details: data.state_id }),
  });

  return (
    <div className="h-11 border-b-[0.5px] border-subtle">
      <StateDropdown
        projectId={issue.project_id ?? undefined}
        value={issue.state_id}
        onChange={(data) => changeState(data)}
        disabled={disabled}
        buttonVariant="transparent-with-text"
        buttonClassName="text-left rounded-none group-[.selected-issue-row]:bg-accent-primary/5 group-[.selected-issue-row]:hover:bg-accent-primary/10 px-page-x"
        buttonContainerClassName="w-full"
        onClose={onClose}
        showTooltip
      />
      {stateTransitionModals}
    </div>
  );
});
