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
import { CustomSearchSelect, Loader } from "@plane/ui";
// components
import { SettingsControlItem } from "@/components/settings/control-item";
// hooks
import { useProject } from "@/hooks/store/use-project";
import { useProjectState } from "@/hooks/store/use-project-state";
import { useUserPermissions } from "@/hooks/store/user";
// services
import approvalGateService from "@/services/approval-gate.service";

/**
 * Project-level config for the handover approval gate: which States are
 * Pending Approval / Approved / Sent Back. This is the "configurable
 * without a deploy" surface for plane.utils.approval — an explicit
 * override on top of the zero-config default (states already named for one
 * of these roles, or a client department-workflow alias, are gated
 * automatically with no setup; see plane/utils/approval.py).
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
    slug && projectId ? `APPROVAL_GATE_CONFIG_SETTINGS_${slug}_${projectId}` : null,
    slug && projectId ? () => approvalGateService.fetchConfig(slug, projectId) : null
  );
  const currentConfig = configs?.[0];

  const [pendingId, setPendingId] = useState<string | null>(null);
  const [approvedId, setApprovedId] = useState<string | null>(null);
  const [sentBackId, setSentBackId] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
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

  const isExplicitOverride = !!currentConfig?.id;
  const isDirty =
    pendingId !== (currentConfig?.pending_approval_state_id ?? null) ||
    approvedId !== (currentConfig?.approved_state_id ?? null) ||
    sentBackId !== (currentConfig?.sent_back_state_id ?? null);

  const handleSave = async () => {
    if (!slug || !projectId || !pendingId || !approvedId) return;
    setIsSaving(true);
    try {
      const payload = {
        pending_approval_state_id: pendingId,
        approved_state_id: approvedId,
        sent_back_state_id: sentBackId,
      };
      if (isExplicitOverride && currentConfig?.id) {
        await approvalGateService.updateConfig(slug, projectId, currentConfig.id, payload);
      } else {
        await approvalGateService.createConfig(slug, projectId, payload);
      }
      await mutate();
      setToast({ type: TOAST_TYPE.SUCCESS, title: "Saved", message: "Approval gate configuration updated." });
    } catch {
      setToast({ type: TOAST_TYPE.ERROR, title: "Error!", message: "Could not save the approval gate configuration." });
    } finally {
      setIsSaving(false);
    }
  };

  const handleClearOverride = async () => {
    if (!slug || !projectId || !currentConfig?.id) return;
    setIsSaving(true);
    try {
      await approvalGateService.deleteConfig(slug, projectId, currentConfig.id);
      await mutate();
      setToast({
        type: TOAST_TYPE.SUCCESS,
        title: "Cleared",
        message: "Reverted to the automatic default (matched by state name).",
      });
    } catch {
      setToast({ type: TOAST_TYPE.ERROR, title: "Error!", message: "Could not clear the override." });
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="flex flex-col gap-4 py-2">
      <div className="flex items-center gap-3">
        <div className="grid size-10 shrink-0 place-items-center rounded-sm bg-layer-2">
          <ShieldCheck className="size-4 shrink-0 text-primary" />
        </div>
        <SettingsControlItem
          title="Handover approval gate"
          description="Only a project Admin may move a work item into the Approved or Sent Back state below. A project whose states already match one of these roles by name is gated automatically — this is only needed to override that, or to name states explicitly."
          control={null}
        />
      </div>

      {!currentProjectDetails || !projectStates ? (
        <Loader className="ml-13">
          <Loader.Item height="50px" />
        </Loader>
      ) : (
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
            <div className="flex items-center justify-between gap-2 border-t border-subtle px-5 py-4">
              <Button
                variant="error-outline"
                size="sm"
                onClick={handleClearOverride}
                disabled={!isExplicitOverride || isSaving}
              >
                Clear override
              </Button>
              <Button
                variant="primary"
                size="sm"
                onClick={handleSave}
                disabled={!isDirty || !pendingId || !approvedId || isSaving}
                loading={isSaving}
              >
                Save
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  );
});
