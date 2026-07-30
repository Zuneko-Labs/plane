/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
import type { TComplianceCategory, TComplianceRunSummary, TComplianceTemplate } from "@plane/types";
// services
import { APIService } from "@/services/api.service";

export class ComplianceService extends APIService {
  constructor() {
    super(API_BASE_URL);
  }

  async getCategories(workspaceSlug: string): Promise<TComplianceCategory[]> {
    return this.get(`/api/workspaces/${workspaceSlug}/compliance-categories/`)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async createCategory(workspaceSlug: string, data: Partial<TComplianceCategory>): Promise<TComplianceCategory> {
    return this.post(`/api/workspaces/${workspaceSlug}/compliance-categories/`, data)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async getTemplates(workspaceSlug: string): Promise<TComplianceTemplate[]> {
    return this.get(`/api/workspaces/${workspaceSlug}/compliance-templates/`)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async createTemplate(workspaceSlug: string, data: Partial<TComplianceTemplate>): Promise<TComplianceTemplate> {
    return this.post(`/api/workspaces/${workspaceSlug}/compliance-templates/`, data)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async updateTemplate(
    workspaceSlug: string,
    templateId: string,
    data: Partial<TComplianceTemplate>
  ): Promise<TComplianceTemplate> {
    return this.patch(`/api/workspaces/${workspaceSlug}/compliance-templates/${templateId}/`, data)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async deleteTemplate(workspaceSlug: string, templateId: string): Promise<void> {
    return this.delete(`/api/workspaces/${workspaceSlug}/compliance-templates/${templateId}/`)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async toggleApplicability(
    workspaceSlug: string,
    templateId: string,
    projectId: string,
    applicable: boolean
  ): Promise<void> {
    return this.patch(`/api/workspaces/${workspaceSlug}/compliance-templates/${templateId}/applicability/`, {
      project_id: projectId,
      applicable,
    })
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async triggerGenerate(workspaceSlug: string, asOf?: string): Promise<TComplianceRunSummary> {
    return this.post(`/api/workspaces/${workspaceSlug}/compliance-templates/generate/`, asOf ? { as_of: asOf } : {})
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }
}
