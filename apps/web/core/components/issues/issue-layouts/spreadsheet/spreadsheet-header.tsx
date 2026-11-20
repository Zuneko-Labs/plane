/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { MouseEvent } from "react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
// constants
import { SPREADSHEET_SELECT_GROUP } from "@plane/constants";
// ui
import type { IIssueDisplayFilterOptions, IIssueDisplayProperties } from "@plane/types";
// components
import { cn } from "@plane/utils";
import { MultipleSelectGroupAction } from "@/components/core/multiple-select";
// hooks
import { getColumnStyle } from "@/hooks/use-column-widths";
import type { TSelectionHelper } from "@/hooks/use-multiple-select";
import { ColumnResizeHandle } from "./column-resize-handle";
import { SpreadsheetHeaderColumn } from "./spreadsheet-header-column";

interface Props {
  displayProperties: IIssueDisplayProperties;
  displayFilters: IIssueDisplayFilterOptions;
  handleDisplayFilterUpdate: (data: Partial<IIssueDisplayFilterOptions>) => void;
  canEditProperties: (projectId: string | undefined) => boolean;
  isEstimateEnabled: boolean;
  spreadsheetColumnsList: (keyof IIssueDisplayProperties)[];
  selectionHelpers: TSelectionHelper;
  isEpic?: boolean;
  isWorkspaceLevel?: boolean;
  startResize: (key: string, event: MouseEvent<HTMLElement>) => void;
  resetWidth: (key: string) => void;
}

export const SpreadsheetHeader = observer(function SpreadsheetHeader(props: Props) {
  const {
    startResize,
    resetWidth,
    displayProperties,
    displayFilters,
    handleDisplayFilterUpdate,
    canEditProperties,
    isEstimateEnabled,
    spreadsheetColumnsList,
    selectionHelpers,
    isEpic = false,
    isWorkspaceLevel = false,
  } = props;
  // router
  const { projectId } = useParams();
  // derived values
  const isGroupSelectionEmpty = selectionHelpers.isGroupSelected(SPREADSHEET_SELECT_GROUP) === "empty";
  // auth
  const canSelectIssues = canEditProperties(projectId?.toString()) && !selectionHelpers.isSelectionDisabled;

  return (
    <thead className="sticky top-0 left-0 z-[12] border-b-[0.5px] border-subtle">
      <tr>
        {isWorkspaceLevel && (
          <th
            className="left-0 z-[15] h-11 items-center border border-t-0 border-b-0 border-subtle bg-layer-1 py-1 text-13 font-medium md:sticky"
            style={getColumnStyle("project", 144)}
            tabIndex={-1}
          >
            <div className="flex h-full w-full items-center truncate px-2">Project</div>
            <ColumnResizeHandle
              onResizeStart={(e) => startResize("project", e)}
              onReset={() => resetWidth("project")}
            />
          </th>
        )}

        {/* Single header column containing both identifier and workitem */}
        <th
          className={cn(
            "group/list-header relative z-[15] h-11 border-r-[0.5px] border-subtle bg-layer-1 text-13 font-medium md:sticky",
            { "left-0": !isWorkspaceLevel }
          )}
          style={{
            ...getColumnStyle("name", isWorkspaceLevel ? 360 : 320),
            ...(isWorkspaceLevel ? { left: getColumnStyle("project", 144).width } : {}),
          }}
          tabIndex={-1}
        >
          <div className="flex h-full w-full items-center gap-2 px-page-x">
            {/* Workitem header section */}
            <div className="flex h-full min-w-0 flex-grow items-center gap-1 py-2.5">
              {canSelectIssues && (
                <div className="mr-1 flex w-3.5 flex-shrink-0 items-center">
                  <MultipleSelectGroupAction
                    className={cn(
                      "pointer-events-none size-3.5 opacity-0 !outline-none group-hover/list-header:pointer-events-auto group-hover/list-header:opacity-100",
                      {
                        "pointer-events-auto opacity-100": !isGroupSelectionEmpty,
                      }
                    )}
                    groupID={SPREADSHEET_SELECT_GROUP}
                    selectionHelpers={selectionHelpers}
                  />
                </div>
              )}
              <span className="text-13 font-medium">{`${isEpic ? "Epics" : "Work items"}`}</span>
            </div>
          </div>
          <ColumnResizeHandle onResizeStart={(e) => startResize("name", e)} onReset={() => resetWidth("name")} />
        </th>

        {spreadsheetColumnsList.map((property) => (
          <SpreadsheetHeaderColumn
            key={property}
            onResizeStart={(e) => startResize(property, e)}
            onResetWidth={() => resetWidth(property)}
            property={property}
            displayProperties={displayProperties}
            displayFilters={displayFilters}
            handleDisplayFilterUpdate={handleDisplayFilterUpdate}
            isEstimateEnabled={isEstimateEnabled}
            isEpic={isEpic}
          />
        ))}
      </tr>
    </thead>
  );
});
