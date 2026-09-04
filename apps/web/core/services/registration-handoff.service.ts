/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

/* eslint-disable no-useless-catch */

import { API_BASE_URL } from "@plane/constants";
import { APIService } from "@/services/api.service";

export type TRegistrationHandoffConfig = {
  id: string;
  project: string;
  trigger_state_id: string;
  eligible_agent_ids: string[];
};

export class RegistrationHandoffService extends APIService {
  constructor() {
    super(API_BASE_URL);
  }

  async fetchConfig(workspaceSlug: string, projectId: string): Promise<TRegistrationHandoffConfig[] | undefined> {
    try {
      const { data } = await this.get(
        `/api/workspaces/${workspaceSlug}/projects/${projectId}/registration-handoff-config/`
      );
      return data || undefined;
    } catch (error) {
      throw error;
    }
  }
}

const registrationHandoffService = new RegistrationHandoffService();

export default registrationHandoffService;
