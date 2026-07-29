/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { TIssuePriorities } from "./issues";

export type TComplianceCadence = "monthly" | "quarterly" | "annual" | "advance_tax";

export interface TComplianceCategory {
  id: string;
  name: string;
  workspace_id: string;
}

export interface TComplianceTemplate {
  id: string;
  key: string;
  title: string;
  category: string;
  category_detail: TComplianceCategory;
  cadence: TComplianceCadence;
  due_day: number;
  due_month: number | null;
  name_template: string;
  priority: TIssuePriorities;
  is_active: boolean;
  applicable_project_ids: string[];
  workspace_id: string;
}

export interface TComplianceRunSummaryItem {
  project: string;
  title: string;
  issue_id?: string;
  reason?: string;
}

export interface TComplianceRunSummary {
  as_of: string;
  created: number;
  skipped: number;
  failed: number;
  created_items: TComplianceRunSummaryItem[];
  failed_items: TComplianceRunSummaryItem[];
}
