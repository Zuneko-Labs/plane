/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useMemo } from "react";
import type { ColumnDef, Row, RowData } from "@tanstack/react-table";
import { observer } from "mobx-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import useSWR from "swr";
import { UserRound } from "lucide-react";
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
// plane package imports
import type { AnalyticsTableDataMap, WorkItemInsightColumns } from "@plane/types";
// plane web components
import { Avatar } from "@plane/ui";
import { getFileURL } from "@plane/utils";
// hooks
import { useAnalytics } from "@/hooks/store/use-analytics";
import { useUserPermissions } from "@/hooks/store/user";
import { AnalyticsService } from "@/services/analytics.service";
// plane web components
import { exportCSV } from "../export";
import { InsightTable } from "../insight-table";

const analyticsService = new AnalyticsService();

declare module "@tanstack/react-table" {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  interface ColumnMeta<TData extends RowData, TValue> {
    export: {
      key: string;
      value: (row: Row<TData>) => string | number;
      label?: string;
    };
  }
}

const WorkItemsInsightTable = observer(function WorkItemsInsightTable() {
  // router
  const params = useParams();
  const workspaceSlug = params.workspaceSlug.toString();
  const { t } = useTranslation();
  // store hooks
  const { allowPermissions } = useUserPermissions();
  const isAdmin = allowPermissions([EUserPermissions.ADMIN], EUserPermissionsLevel.WORKSPACE, workspaceSlug);
  const { selectedDuration, selectedProjects, selectedCycle, selectedModule, isPeekView, isEpic } = useAnalytics();
  const { data: workItemsData, isLoading } = useSWR(
    `insights-table-work-items-${workspaceSlug}-${selectedDuration}-${selectedProjects}-${selectedCycle}-${selectedModule}-${isPeekView}-${isEpic}`,
    () =>
      analyticsService.getAdvanceAnalyticsStats<WorkItemInsightColumns[]>(
        workspaceSlug,
        "work-items",
        {
          // date_filter: selectedDuration,
          ...(selectedProjects?.length > 0 ? { project_ids: selectedProjects.join(",") } : {}),
          ...(selectedCycle ? { cycle_id: selectedCycle } : {}),
          ...(selectedModule ? { module_id: selectedModule } : {}),
          ...(isEpic ? { epic: true } : {}),
        },
        isPeekView
      )
  );
  // derived values
  const columnsLabels: Record<keyof Omit<WorkItemInsightColumns, "project_id" | "avatar_url" | "assignee_id">, string> =
    useMemo(
      () => ({
        backlog_work_items: t("workspace_projects.state.backlog"),
        started_work_items: t("workspace_projects.state.started"),
        un_started_work_items: t("workspace_projects.state.unstarted"),
        completed_work_items: t("workspace_projects.state.completed"),
        cancelled_work_items: t("workspace_projects.state.cancelled"),
        project__name: t("common.project"),
        display_name: t("common.assignee"),
      }),
      [t]
    );
  const columns: ColumnDef<AnalyticsTableDataMap["work-items"]>[] = useMemo(
    () => [
      {
        accessorKey: "display_name",
        header: () => <div className="text-left">{columnsLabels["display_name"]}</div>,
        cell: ({ row }: { row: Row<WorkItemInsightColumns> }) => {
          const { assignee_id, avatar_url, display_name } = row.original;
          // member rows of the workspace-level table open the team calendar (admin only) filtered to that member
          const isClickable = !isPeekView && isAdmin && !!assignee_id;
          const content = (
            <div className="flex items-center gap-2">
              {avatar_url && avatar_url !== "" ? (
                <Avatar name={display_name} src={getFileURL(avatar_url)} size={24} shape="circle" />
              ) : (
                <div className="flex h-4 w-4 flex-shrink-0 items-center justify-center overflow-hidden rounded-full bg-layer-1 capitalize">
                  {display_name ? display_name?.[0] : <UserRound className="text-secondary" size={12} />}
                </div>
              )}
              <span className="break-words text-secondary">{display_name ?? t(`Unassigned`)}</span>
            </div>
          );
          return (
            <div className="text-left">
              {isClickable ? (
                <Link
                  href={`/${workspaceSlug}/team-calendar?member=${assignee_id}`}
                  className="inline-block hover:underline"
                >
                  {content}
                </Link>
              ) : (
                content
              )}
            </div>
          );
        },
        meta: {
          export: {
            key: columnsLabels["display_name"],
            value: (row) => row.original.display_name?.toString() ?? "",
          },
        },
      },
      {
        accessorKey: "backlog_work_items",
        header: () => <div className="text-right">{columnsLabels["backlog_work_items"]}</div>,
        cell: ({ row }) => <div className="text-right">{row.original.backlog_work_items}</div>,
        meta: {
          export: {
            key: columnsLabels["backlog_work_items"],
            value: (row) => row.original.backlog_work_items.toString(),
          },
        },
      },
      {
        accessorKey: "started_work_items",
        header: () => <div className="text-right">{columnsLabels["started_work_items"]}</div>,
        cell: ({ row }) => <div className="text-right">{row.original.started_work_items}</div>,
        meta: {
          export: {
            key: columnsLabels["started_work_items"],
            value: (row) => row.original.started_work_items.toString(),
          },
        },
      },
      {
        accessorKey: "un_started_work_items",
        header: () => <div className="text-right">{columnsLabels["un_started_work_items"]}</div>,
        cell: ({ row }) => <div className="text-right">{row.original.un_started_work_items}</div>,
        meta: {
          export: {
            key: columnsLabels["un_started_work_items"],
            value: (row) => row.original.un_started_work_items.toString(),
          },
        },
      },
      {
        accessorKey: "completed_work_items",
        header: () => <div className="text-right">{columnsLabels["completed_work_items"]}</div>,
        cell: ({ row }) => <div className="text-right">{row.original.completed_work_items}</div>,
        meta: {
          export: {
            key: columnsLabels["completed_work_items"],
            value: (row) => row.original.completed_work_items.toString(),
          },
        },
      },
      {
        accessorKey: "cancelled_work_items",
        header: () => <div className="text-right">{columnsLabels["cancelled_work_items"]}</div>,
        cell: ({ row }) => <div className="text-right">{row.original.cancelled_work_items}</div>,
        meta: {
          export: {
            key: columnsLabels["cancelled_work_items"],
            value: (row) => row.original.cancelled_work_items.toString(),
          },
        },
      },
    ],
    [columnsLabels, isAdmin, isPeekView, t, workspaceSlug]
  );
  return (
    <InsightTable<"work-items">
      analyticsType="work-items"
      data={workItemsData}
      isLoading={isLoading}
      columns={columns}
      columnsLabels={columnsLabels}
      headerText={isPeekView ? t("common.assignee") : t("common.members")}
      onExport={(rows) => workItemsData && exportCSV(rows, columns, workspaceSlug)}
    />
  );
});

export default WorkItemsInsightTable;
