/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { TComplianceCadence } from "@plane/types";

// Hardcoded rather than routed through useTranslation()/t() — the i18n
// package's per-namespace locale files (e.g. workspace-settings.json) are
// currently missing from packages/i18n/src/locales (mid-migration state),
// so any dotted key outside the "common" namespace renders as the raw key
// instead of resolved text. These are plain English strings until that's
// fixed; add them back to common.json's i18n_label lookups once it is.
export const COMPLIANCE_CADENCE_LABELS: Record<TComplianceCadence, string> = {
  monthly: "Monthly",
  quarterly: "Quarterly",
  annual: "Annual",
  advance_tax: "Advance Tax",
};
