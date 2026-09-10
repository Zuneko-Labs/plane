/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

/* eslint-disable no-useless-catch */

import { API_BASE_URL } from "@plane/constants";
import { APIService } from "@/services/api.service";

export type TApprovalGateConfig = {
  id: string | null;
  project: string;
  // On by default for every project — see DEFAULT_APPROVAL_GATE_STATES on
  // the backend. Turning it off switches the gate off entirely, not just
  // the states below.
  is_enabled: boolean;
  // null until a role resolves — either nothing is configured/matched yet,
  // or (for sent_back) the project's workflow has no rejection step at all
  // (see apply_department_workflows.py), so that gating simply doesn't
  // apply there until a matching state is added.
  pending_approval_state_id: string | null;
  approved_state_id: string | null;
  sent_back_state_id: string | null;
};

export type TApprovalGateConfigPayload = {
  is_enabled?: boolean;
  pending_approval_state_id?: string | null;
  approved_state_id?: string | null;
  sent_back_state_id?: string | null;
};

export type TApprovalRecord = {
  id: string;
  project: string;
  issue: string;
  issue_name: string;
  issue_sequence_id: number;
  actor: string;
  actor_email: string;
  decision: "approved" | "sent_back";
  comment: string | null;
  created_at: string;
};

// Shared SWR key: both the settings editor and every read-only consumer
// (state dropdown, sent-back modal, kanban drop) must key off the same
// cache entry, or saving in settings never revalidates the consumers.
export const approvalGateConfigSWRKey = (workspaceSlug: string, projectId: string) =>
  `APPROVAL_GATE_CONFIG_${workspaceSlug}_${projectId}`;

export class ApprovalGateService extends APIService {
  constructor() {
    super(API_BASE_URL);
  }

  async fetchConfig(workspaceSlug: string, projectId: string): Promise<TApprovalGateConfig[] | undefined> {
    try {
      const { data } = await this.get(`/api/workspaces/${workspaceSlug}/projects/${projectId}/approval-gate-config/`);
      return data || undefined;
    } catch (error) {
      throw error;
    }
  }

  async createConfig(
    workspaceSlug: string,
    projectId: string,
    payload: TApprovalGateConfigPayload
  ): Promise<TApprovalGateConfig> {
    try {
      const { data } = await this.post(
        `/api/workspaces/${workspaceSlug}/projects/${projectId}/approval-gate-config/`,
        payload
      );
      return data;
    } catch (error) {
      throw error;
    }
  }

  async updateConfig(
    workspaceSlug: string,
    projectId: string,
    configId: string,
    payload: TApprovalGateConfigPayload
  ): Promise<TApprovalGateConfig> {
    try {
      const { data } = await this.patch(
        `/api/workspaces/${workspaceSlug}/projects/${projectId}/approval-gate-config/${configId}/`,
        payload
      );
      return data;
    } catch (error) {
      throw error;
    }
  }

  async deleteConfig(workspaceSlug: string, projectId: string, configId: string): Promise<void> {
    try {
      await this.delete(`/api/workspaces/${workspaceSlug}/projects/${projectId}/approval-gate-config/${configId}/`);
    } catch (error) {
      throw error;
    }
  }

  async fetchRecords(workspaceSlug: string, projectId: string): Promise<TApprovalRecord[]> {
    try {
      const { data } = await this.get(`/api/workspaces/${workspaceSlug}/projects/${projectId}/approval-records/`);
      return data || [];
    } catch (error) {
      throw error;
    }
  }
}

const approvalGateService = new ApprovalGateService();

export default approvalGateService;
