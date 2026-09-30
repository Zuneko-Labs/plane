/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

/* eslint-disable no-useless-catch */

import { API_BASE_URL } from "@plane/constants";
import type { TIssuePriorities } from "@plane/types";
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
  decision: TApprovalDecision;
  comment: string | null;
  created_at: string;
};

export type TApprovalDecision = "approved" | "sent_back" | "reopened";

export type TApprovalModuleRef = { id: string; name: string };

/** A work item waiting in Pending Approval, from any project the user approves for. */
export type TWorkspacePendingApproval = {
  id: string;
  name: string;
  sequence_id: number;
  priority: TIssuePriorities | null;
  target_date: string | null;
  state_id: string;
  state_name: string | null;
  project_id: string;
  project_name: string | null;
  project_identifier: string | null;
  modules: TApprovalModuleRef[];
  labels: { id: string; name: string; color: string | null }[];
  assignee_ids: string[];
  has_registration_handoff: boolean;
  approved_state_id: string;
  sent_back_state_id: string | null;
  updated_at: string;
};

export type TWorkspaceApprovalRecord = TApprovalRecord & {
  project_name: string | null;
  project_identifier: string | null;
  modules: TApprovalModuleRef[];
  actor_name: string | null;
};

export type TReopenRequestStatus = "pending" | "approved" | "rejected";

/** A request to take an approved work item back to an earlier stage. */
export type TReopenRequest = {
  id: string;
  project_id: string;
  project_name: string | null;
  project_identifier: string | null;
  issue_id: string;
  issue_name: string;
  issue_sequence_id: number;
  issue_state_id: string | null;
  modules: TApprovalModuleRef[];
  from_state_id: string | null;
  from_state_name: string | null;
  to_state_id: string | null;
  to_state_name: string | null;
  reason: string;
  status: TReopenRequestStatus;
  requested_by: string;
  requested_by_name: string | null;
  decided_by: string | null;
  decided_by_name: string | null;
  decided_at: string | null;
  decision_comment: string | null;
  created_at: string;
};

export type TReopenRequestDecisionPayload = {
  decision: "approve" | "reject";
  comment?: string;
  // only when moving back needs a registrar and the server asked for one
  registration_agent_id?: string;
};

// Shared SWR key: both the settings editor and every read-only consumer
// (state dropdown, sent-back modal, kanban drop) must key off the same
// cache entry, or saving in settings never revalidates the consumers.
export const approvalGateConfigSWRKey = (workspaceSlug: string, projectId: string) =>
  `APPROVAL_GATE_CONFIG_${workspaceSlug}_${projectId}`;

// workspace-wide approvals page
export const workspacePendingApprovalsSWRKey = (workspaceSlug: string) =>
  `WORKSPACE_PENDING_APPROVALS_${workspaceSlug}`;
export const workspaceReopenRequestsSWRKey = (workspaceSlug: string, status: TReopenRequestStatus | "all") =>
  `WORKSPACE_REOPEN_REQUESTS_${workspaceSlug}_${status}`;
export const workspaceApprovalRecordsSWRKey = (workspaceSlug: string) => `WORKSPACE_APPROVAL_RECORDS_${workspaceSlug}`;

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

  async fetchWorkspacePendingApprovals(workspaceSlug: string): Promise<TWorkspacePendingApproval[]> {
    try {
      const { data } = await this.get(`/api/workspaces/${workspaceSlug}/approvals/pending/`);
      return data || [];
    } catch (error) {
      throw error;
    }
  }

  async fetchWorkspaceApprovalRecords(workspaceSlug: string): Promise<TWorkspaceApprovalRecord[]> {
    try {
      const { data } = await this.get(`/api/workspaces/${workspaceSlug}/approvals/records/`);
      return data || [];
    } catch (error) {
      throw error;
    }
  }

  async fetchWorkspaceReopenRequests(
    workspaceSlug: string,
    status: TReopenRequestStatus | "all" = "pending"
  ): Promise<TReopenRequest[]> {
    try {
      const { data } = await this.get(`/api/workspaces/${workspaceSlug}/approvals/reopen-requests/`, {
        params: { status },
      });
      return data || [];
    } catch (error) {
      throw error;
    }
  }

  async decideReopenRequest(
    workspaceSlug: string,
    requestId: string,
    payload: TReopenRequestDecisionPayload
  ): Promise<TReopenRequest> {
    try {
      const { data } = await this.post(
        `/api/workspaces/${workspaceSlug}/approvals/reopen-requests/${requestId}/decision/`,
        payload
      );
      return data;
    } catch (error: any) {
      throw error?.response?.data ?? error;
    }
  }

  async createReopenRequest(
    workspaceSlug: string,
    projectId: string,
    issueId: string,
    payload: { state_id: string; reason: string }
  ): Promise<TReopenRequest> {
    try {
      const { data } = await this.post(
        `/api/workspaces/${workspaceSlug}/projects/${projectId}/issues/${issueId}/reopen-requests/`,
        payload
      );
      return data;
    } catch (error: any) {
      throw error?.response?.data ?? error;
    }
  }
}

const approvalGateService = new ApprovalGateService();

export default approvalGateService;
