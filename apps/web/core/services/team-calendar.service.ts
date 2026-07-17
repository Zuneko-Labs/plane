/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
// services
import { APIService } from "@/services/api.service";

export type TTeamCalendarIssue = {
  id: string;
  name: string;
  sequence_id: number;
  priority: string;
  project_id: string;
  project_identifier: string;
  start_date: string | null;
  target_date: string | null;
  state_group: string | null;
  state_id: string | null;
  state_name: string | null;
  state_color: string | null;
  effective_start_date: string | null;
};

export type TTeamCalendarMember = {
  id: string;
  display_name: string;
  first_name: string;
  last_name: string;
  avatar_url: string | null;
  issues: TTeamCalendarIssue[];
};

export type TTeamCalendarResponse = {
  members: TTeamCalendarMember[];
};

export class TeamCalendarService extends APIService {
  constructor() {
    super(API_BASE_URL);
  }

  async getTeamCalendar(
    workspaceSlug: string,
    params: { start_date: string; end_date: string; project?: string }
  ): Promise<TTeamCalendarResponse> {
    return this.get(`/api/workspaces/${workspaceSlug}/team-calendar/`, { params })
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }
}

export const teamCalendarService = new TeamCalendarService();
