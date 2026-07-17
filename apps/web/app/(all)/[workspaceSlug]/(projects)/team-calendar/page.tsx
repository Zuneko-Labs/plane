/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// components
import { PageHead } from "@/components/core/page-title";
import { TeamCalendarRoot } from "@/components/team-calendar/root";

export default function TeamCalendarPage() {
  return (
    <>
      <PageHead title="Team Calendar" />
      <div className="relative h-full w-full overflow-hidden">
        <TeamCalendarRoot />
      </div>
    </>
  );
}
