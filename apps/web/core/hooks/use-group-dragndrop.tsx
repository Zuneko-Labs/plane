/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { useParams } from "next/navigation";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import type { EIssuesStoreType, TIssue, TIssueGroupByOptions, TIssueOrderByOptions } from "@plane/types";
import { ApprovalSentBackModal } from "@/components/issues/approval-sent-back-modal";
import type { GroupDropLocation } from "@/components/issues/issue-layouts/utils";
import { handleGroupDragDrop } from "@/components/issues/issue-layouts/utils";
import { RegistrationAgentModal } from "@/components/issues/registration-agent-modal";
import approvalGateService from "@/services/approval-gate.service";
import registrationHandoffService from "@/services/registration-handoff.service";
import { ISSUE_FILTER_DEFAULT_DATA } from "@/store/issue/helpers/base-issues.store";
import { useIssueDetail } from "./store/use-issue-detail";
import { useIssues } from "./store/use-issues";
import { useIssuesActions } from "./use-issues-actions";
import { useUserPermissions } from "./store/user";
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";

type DNDStoreType =
  | EIssuesStoreType.PROJECT
  | EIssuesStoreType.MODULE
  | EIssuesStoreType.CYCLE
  | EIssuesStoreType.PROJECT_VIEW
  | EIssuesStoreType.PROFILE
  | EIssuesStoreType.ARCHIVED
  | EIssuesStoreType.WORKSPACE_DRAFT
  | EIssuesStoreType.TEAM
  | EIssuesStoreType.TEAM_VIEW
  | EIssuesStoreType.EPIC
  | EIssuesStoreType.TEAM_PROJECT_WORK_ITEMS;

type TPendingRegistrationDrop = {
  projectId: string;
  issueId: string;
  data: Partial<TIssue>;
  eligibleAgentIds: string[];
};

type TPendingSentBackDrop = {
  projectId: string;
  issueId: string;
  data: Partial<TIssue>;
};

export const useGroupIssuesDragNDrop = (
  storeType: DNDStoreType,
  orderBy: TIssueOrderByOptions | undefined,
  groupBy: TIssueGroupByOptions | undefined,
  subGroupBy?: TIssueGroupByOptions
) => {
  const { workspaceSlug } = useParams();

  const { allowPermissions } = useUserPermissions();
  const {
    issue: { getIssueById },
  } = useIssueDetail();
  const { updateIssue } = useIssuesActions(storeType);
  const {
    issues: { getIssueIds, addCycleToIssue, removeCycleFromIssue, changeModulesInIssue },
  } = useIssues(storeType);

  // Dropping a card onto the registration state's column needs an eligible
  // agent, same as the detail view's StateDropdown — the drop is held here
  // (never optimistically applied) until the modal confirms or is cancelled.
  const [pendingRegistrationDrop, setPendingRegistrationDrop] = useState<TPendingRegistrationDrop | null>(null);

  // Dropping a card onto the Sent Back column always requires a comment —
  // held here (never optimistically applied) until the modal confirms or is
  // cancelled. The server still enforces this and the approver-only rule
  // regardless of whether this modal was ever shown.
  const [pendingSentBackDrop, setPendingSentBackDrop] = useState<TPendingSentBackDrop | null>(null);

  /**
   * update Issue on Drop, checks if modules or cycles are changed and then calls appropriate functions
   * @param projectId
   * @param issueId
   * @param data
   * @param issueUpdates
   */
  const updateIssueOnDrop = async (
    projectId: string,
    issueId: string,
    data: Partial<TIssue>,
    issueUpdates: {
      [groupKey: string]: {
        ADD: string[];
        REMOVE: string[];
      };
    }
  ) => {
    const errorToastProps = {
      type: TOAST_TYPE.ERROR,
      title: "Error!",
      message: "Error while updating work item",
    };
    const moduleKey = ISSUE_FILTER_DEFAULT_DATA["module"];
    const cycleKey = ISSUE_FILTER_DEFAULT_DATA["cycle"];

    const isModuleChanged = Object.keys(data).includes(moduleKey);
    const isCycleChanged = Object.keys(data).includes(cycleKey);

    if (isCycleChanged && workspaceSlug) {
      if (data[cycleKey]) {
        addCycleToIssue(workspaceSlug.toString(), projectId, data[cycleKey]?.toString() ?? "", issueId).catch(() =>
          setToast(errorToastProps)
        );
      } else {
        removeCycleFromIssue(workspaceSlug.toString(), projectId, issueId).catch(() => setToast(errorToastProps));
      }
      delete data[cycleKey];
    }

    if (isModuleChanged && workspaceSlug && issueUpdates[moduleKey]) {
      changeModulesInIssue(
        workspaceSlug.toString(),
        projectId,
        issueId,
        issueUpdates[moduleKey].ADD,
        issueUpdates[moduleKey].REMOVE
      ).catch(() => setToast(errorToastProps));
      delete data[moduleKey];
    }

    const stateId = data.state_id as string | undefined;
    if (stateId && workspaceSlug) {
      const configs = await registrationHandoffService
        .fetchConfig(workspaceSlug.toString(), projectId)
        .catch(() => undefined);
      const config = configs?.[0];
      // Only the first entry into the registration state needs an agent —
      // an item already handed off keeps the agent it was given.
      const alreadyHandedOff = !!getIssueById(issueId)?.has_registration_handoff;
      if (config && config.trigger_state_id === stateId && !alreadyHandedOff) {
        setPendingRegistrationDrop({ projectId, issueId, data, eligibleAgentIds: config.eligible_agent_ids });
        return;
      }

      const approvalConfigs = await approvalGateService
        .fetchConfig(workspaceSlug.toString(), projectId)
        .catch(() => undefined);
      const approvalConfig = approvalConfigs?.[0];
      const isGatedTarget =
        !!approvalConfig &&
        (stateId === approvalConfig.approved_state_id || stateId === approvalConfig.sent_back_state_id);

      if (isGatedTarget) {
        const isApprover = allowPermissions(
          [EUserPermissions.ADMIN],
          EUserPermissionsLevel.PROJECT,
          workspaceSlug.toString(),
          projectId
        );
        if (!isApprover) {
          // A member can't decide Approved/Sent Back themselves — their
          // drop still succeeds, it just lands in Pending Approval and
          // notifies the project's approvers instead (the server applies
          // this same redirect regardless, see plane.utils.approval; doing
          // it here too means the card lands in the right column
          // immediately instead of flashing into a state it'll get
          // corrected out of).
          if (approvalConfig?.pending_approval_state_id) {
            data.state_id = approvalConfig.pending_approval_state_id;
            setToast({
              type: TOAST_TYPE.INFO,
              title: "Sent for approval",
              message: "A project approver will review this work item.",
            });
          } else {
            setToast({
              type: TOAST_TYPE.ERROR,
              title: "Not allowed",
              message: 'Only a project approver can move a work item to "Approved" or "Sent Back".',
            });
            return;
          }
        }
      }

      if (approvalConfig && approvalConfig.sent_back_state_id === data.state_id) {
        setPendingSentBackDrop({ projectId, issueId, data });
        return;
      }
    }

    if (updateIssue) {
      updateIssue(projectId, issueId, data).catch((err) =>
        setToast({ ...errorToastProps, message: err?.error ?? err?.detail ?? errorToastProps.message })
      );
    }
  };

  const handleOnDrop = async (source: GroupDropLocation, destination: GroupDropLocation) => {
    if (
      source.columnId &&
      destination.columnId &&
      destination.columnId === source.columnId &&
      destination.id === source.id
    )
      return;

    await handleGroupDragDrop(
      source,
      destination,
      getIssueById,
      getIssueIds,
      updateIssueOnDrop,
      groupBy,
      subGroupBy,
      orderBy !== "sort_order"
    ).catch((err) => {
      setToast({
        title: "Error!",
        type: TOAST_TYPE.ERROR,
        message: err?.error ?? err?.detail ?? "Failed to perform this action",
      });
    });
  };

  const registrationAgentModal = (
    <RegistrationAgentModal
      isOpen={!!pendingRegistrationDrop}
      handleClose={() => setPendingRegistrationDrop(null)}
      workspaceSlug={workspaceSlug?.toString() ?? ""}
      projectId={pendingRegistrationDrop?.projectId ?? ""}
      eligibleAgentIds={pendingRegistrationDrop?.eligibleAgentIds ?? []}
      onSubmit={async (agentId) => {
        if (!pendingRegistrationDrop || !updateIssue) return;
        const { projectId, issueId, data } = pendingRegistrationDrop;
        await updateIssue(projectId, issueId, {
          ...data,
          registration_agent_id: agentId,
          // The PATCH returns 204 with no body, and the store only applies
          // the keys we send — so mirror the record the server just wrote,
          // otherwise the next state change re-prompts for an agent.
          has_registration_handoff: true,
        } as Partial<TIssue>);
        setPendingRegistrationDrop(null);
      }}
    />
  );

  const sentBackModal = (
    <ApprovalSentBackModal
      isOpen={!!pendingSentBackDrop}
      handleClose={() => setPendingSentBackDrop(null)}
      onSubmit={async (commentHtml) => {
        if (!pendingSentBackDrop || !updateIssue) return;
        const { projectId, issueId, data } = pendingSentBackDrop;
        await updateIssue(projectId, issueId, { ...data, approval_comment_html: commentHtml } as Partial<TIssue>);
        setPendingSentBackDrop(null);
      }}
    />
  );

  return { handleOnDrop, registrationAgentModal, sentBackModal };
};
