/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
import useSWR from "swr";
import { ShieldCheck } from "lucide-react";
// plane imports
import { EIconSize, EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
import { Button } from "@plane/propel/button";
import { StateGroupIcon, StatePropertyIcon } from "@plane/propel/icons";
import { setToast, TOAST_TYPE } from "@plane/propel/toast";
import { CustomSearchSelect, Loader, ToggleSwitch } from "@plane/ui";
// components
import { SettingsControlItem } from "@/components/settings/control-item";
// hooks
import { useProject } from "@/hooks/store/use-project";
import { useProjectState } from "@/hooks/store/use-project-state";
import { useUserPermissions } from "@/hooks/store/user";
// services
import approvalGateService, { approvalGateConfigSWRKey } from "@/services/approval-gate.service";
import type { TApprovalGateConfigPayload } from "@/services/approval-gate.service";

/**
 * Project-level config for the handover approval gate: which States are
 * Pending Approval / Approved / Sent Back. On by default for every project
 * (see DEFAULT_APPROVAL_GATE_STATES on the backend) — this is the
 * "configurable without a deploy" surface for plane.utils.approval, letting
 * an Admin turn the gate off entirely or repoint any of the three states.
 */
export const ApprovalGateAutomation = observer(function ApprovalGateAutomation() {
  const { workspaceSlug } = useParams();
  const { currentProjectDetails } = useProject();
  const { projectStates } = useProjectState();
  const { allowPermissions } = useUserPermissions();
  const { t } = useTranslation();

  const slug = workspaceSlug?.toString();
  const projectId = currentProjectDetails?.id;

  const { data: configs, mutate } = useSWR(
    slug && projectId ? approvalGateConfigSWRKey(slug, projectId) : null,
    slug && projectId ? () => approvalGateService.fetchConfig(slug, projectId) : null
  );
  const currentConfig = configs?.[0];

  const [isEnabled, setIsEnabled] = useState(true);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [approvedId, setApprovedId] = useState<string | null>(null);
  const [sentBackId, setSentBackId] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    setIsEnabled(currentConfig?.is_enabled ?? true);
    setPendingId(currentConfig?.pending_approval_state_id ?? null);
    setApprovedId(currentConfig?.approved_state_id ?? null);
    setSentBackId(currentConfig?.sent_back_state_id ?? null);
  }, [currentConfig]);

  const isAdmin = allowPermissions([EUserPermissions.ADMIN], EUserPermissionsLevel.PROJECT, slug, projectId);

  const stateOptions = (excludeIds: (string | null)[]) =>
    (projectStates ?? [])
      .filter((state) => !excludeIds.includes(state.id))
      .map((state) => ({
        value: state.id,
        query: state.name,
        content: (
          <div className="flex items-center gap-2">
            <StateGroupIcon stateGroup={state.group} color={state.color} size={EIconSize.LG} />
            {state.name}
          </div>
        ),
      }));

  const renderSelectedState = (stateId: string | null) => {
    const state = projectStates?.find((s) => s.id === stateId);
    return (
      <div className="flex items-center gap-2">
        {state ? (
          <StateGroupIcon stateGroup={state.group} color={state.color} size={EIconSize.LG} />
        ) : (
          <StatePropertyIcon className="h-3.5 w-3.5 text-secondary" />
        )}
        {state?.name ?? <span className="text-secondary">{t("state")}</span>}
      </div>
    );
  };

  const isDirty =
    isEnabled !== (currentConfig?.is_enabled ?? true) ||
    pendingId !== (currentConfig?.pending_approval_state_id ?? null) ||
    approvedId !== (currentConfig?.approved_state_id ?? null) ||
    sentBackId !== (currentConfig?.sent_back_state_id ?? null);

  // The create endpoint upserts (see ApprovalGateConfigViewSet.create), so
  // every save — the Save button and the toggle alike — goes through the
  // same POST regardless of whether a row already exists.
  const persist = async (overrides: TApprovalGateConfigPayload = {}) => {
    if (!slug || !projectId) return;
    setIsSaving(true);
    try {
      const payload: TApprovalGateConfigPayload = {
        is_enabled: isEnabled,
        pending_approval_state_id: pendingId,
        approved_state_id: approvedId,
        sent_back_state_id: sentBackId,
        ...overrides,
      };
      await approvalGateService.createConfig(slug, projectId, payload);
      await mutate();
      setToast({ type: TOAST_TYPE.SUCCESS, title: "Saved", message: "Approval gate configuration updated." });
    } catch {
      setToast({ type: TOAST_TYPE.ERROR, title: "Error!", message: "Could not save the approval gate configuration." });
    } finally {
      setIsSaving(false);
    }
  };

  const handleSave = () => persist();

  const handleToggle = async () => {
    const nextValue = !isEnabled;
    setIsEnabled(nextValue);
    await persist({ is_enabled: nextValue });
  };

  return (
    <div className="flex flex-col gap-4 py-2">
      <div className="flex items-center gap-3">
        <div className="grid size-10 shrink-0 place-items-center rounded-sm bg-layer-2">
          <ShieldCheck className="size-4 shrink-0 text-primary" />
        </div>
        <SettingsControlItem
          title="Handover approval gate"
          description="Only a project Admin may move a work item into the Approved or Sent Back state below. On by default for every project, mapped to Closed / Excel entry and Handover / Xerox and Binding — change the states below or turn it off entirely."
          control={<ToggleSwitch value={isEnabled} onChange={handleToggle} size="sm" disabled={!isAdmin || isSaving} />}
        />
      </div>

      {!currentProjectDetails || !projectStates ? (
        <Loader className="ml-13">
          <Loader.Item height="50px" />
        </Loader>
      ) : (
        isEnabled && (
          <div className="ml-13 flex flex-col rounded-sm border border-subtle bg-surface-2">
            <div className="flex w-full items-center justify-between gap-2 px-5 py-4">
              <div className="w-1/2 text-13 font-medium">Pending Approval state</div>
              <div className="w-1/2">
                <CustomSearchSelect
                  value={pendingId}
                  label={renderSelectedState(pendingId)}
                  onChange={(val: string) => setPendingId(val)}
                  options={stateOptions([approvedId, sentBackId])}
                  disabled={!isAdmin}
                  input
                />
              </div>
            </div>

            <div className="flex w-full items-center justify-between gap-2 border-t border-subtle px-5 py-4">
              <div className="w-1/2 text-13 font-medium">Approved state</div>
              <div className="w-1/2">
                <CustomSearchSelect
                  value={approvedId}
                  label={renderSelectedState(approvedId)}
                  onChange={(val: string) => setApprovedId(val)}
                  options={stateOptions([pendingId, sentBackId])}
                  disabled={!isAdmin}
                  input
                />
              </div>
            </div>

            <div className="flex w-full items-center justify-between gap-2 border-t border-subtle px-5 py-4">
              <div className="w-1/2 text-13 font-medium">Sent Back state (optional)</div>
              <div className="w-1/2">
                <CustomSearchSelect
                  value={sentBackId}
                  label={renderSelectedState(sentBackId)}
                  onChange={(val: string) => setSentBackId(val)}
                  options={stateOptions([pendingId, approvedId])}
                  disabled={!isAdmin}
                  input
                />
              </div>
            </div>

            {isAdmin && (
              <div className="flex items-center justify-end gap-2 border-t border-subtle px-5 py-4">
                <Button
                  variant="primary"
                  size="sm"
                  onClick={handleSave}
                  disabled={!isDirty || !pendingId || (!approvedId && !sentBackId) || isSaving}
                  loading={isSaving}
                >
                  Save
                </Button>
              </div>
            )}
          </div>
        )
      )}
    </div>
  );
});
