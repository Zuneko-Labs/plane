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
  pending_approval_state_id: string;
  approved_state_id: string;
  // null on projects whose workflow has no rejection step — none of the
  // client's real department workflows model one (see
  // apply_department_workflows.py) — so Sent Back gating simply doesn't
  // apply there until a matching state is added.
  sent_back_state_id: string | null;
};

export type TApprovalGateConfigPayload = {
  pending_approval_state_id: string;
  approved_state_id: string;
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
