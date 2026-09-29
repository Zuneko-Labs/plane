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
import { getApprovalTransitionError, SENT_FOR_APPROVAL_TOAST } from "./use-approval-gate-config";
import { REGISTRATION_AGENT_REQUIRED } from "./use-registration-handoff-config";
import { useMember } from "./store/use-member";
import { useProjectState } from "./store/use-project-state";
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
  const { getProjectStates } = useProjectState();
  const {
    project: { getProjectMemberIds },
  } = useMember();

  // active Members/Admins (guests can't be assigned), narrowed to the
  // configured pool when there is one - mirrors plane.utils.registration_handoff
  const getEligibleAgentIds = (projectId: string, configuredIds: string[] = []) => {
    const memberIds = getProjectMemberIds(projectId, false) ?? [];
    return configuredIds.length > 0 ? memberIds.filter((memberId) => configuredIds.includes(memberId)) : memberIds;
  };
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
    let sendsForApproval = false;
    if (stateId && workspaceSlug) {
      const [registrationConfigs, approvalConfigs] = await Promise.all([
        registrationHandoffService.fetchConfig(workspaceSlug.toString(), projectId).catch(() => undefined),
        approvalGateService.fetchConfig(workspaceSlug.toString(), projectId).catch(() => undefined),
      ]);
      const registrationConfig = registrationConfigs?.[0];
      const approvalConfig = approvalConfigs?.[0];
      const isGateOn = !!approvalConfig && (approvalConfig.is_enabled ?? true);
      const fromStateId = getIssueById(issueId)?.state_id;
      const isApprover = allowPermissions(
        [EUserPermissions.ADMIN],
        EUserPermissionsLevel.PROJECT,
        workspaceSlug.toString(),
        projectId
      );

      // Pending Approval is a hard stop for everyone - refuse a drop the
      // server would refuse (see plane.utils.approval), no redirect.
      const transitionError = getApprovalTransitionError({
        config: approvalConfig,
        states: getProjectStates(projectId),
        isApprover,
        fromStateId,
        toStateId: stateId,
      });
      if (transitionError) {
        setToast({ type: TOAST_TYPE.ERROR, title: "Can't move work item", message: transitionError });
        return;
      }

      // Only the first entry into the registration state needs a registrar —
      // an item already handed off keeps the one it was given.
      const alreadyHandedOff = !!getIssueById(issueId)?.has_registration_handoff;
      if (registrationConfig && registrationConfig.trigger_state_id === stateId && !alreadyHandedOff) {
        setPendingRegistrationDrop({
          projectId,
          issueId,
          data,
          eligibleAgentIds: getEligibleAgentIds(projectId, registrationConfig.eligible_agent_ids),
        });
        return;
      }

      // Ask for a reason only for an actual rejection — an approver
      // dragging a work item back out of Pending Approval into Sent Back.
      if (
        isGateOn &&
        isApprover &&
        !!approvalConfig.sent_back_state_id &&
        !!approvalConfig.pending_approval_state_id &&
        stateId === approvalConfig.sent_back_state_id &&
        fromStateId === approvalConfig.pending_approval_state_id
      ) {
        setPendingSentBackDrop({ projectId, issueId, data });
        return;
      }

      sendsForApproval =
        isGateOn &&
        !!approvalConfig.pending_approval_state_id &&
        stateId === approvalConfig.pending_approval_state_id &&
        fromStateId !== approvalConfig.pending_approval_state_id;
    }

    if (updateIssue) {
      updateIssue(projectId, issueId, data)
        .then(() => {
          if (sendsForApproval) setToast(SENT_FOR_APPROVAL_TOAST);
        })
        .catch((err) => {
          // the registrar on record is no longer eligible - ask for a new one
          if (err?.error_code === REGISTRATION_AGENT_REQUIRED) {
            setPendingRegistrationDrop({ projectId, issueId, data, eligibleAgentIds: getEligibleAgentIds(projectId) });
            return;
          }
          setToast({ ...errorToastProps, message: err?.error ?? err?.detail ?? errorToastProps.message });
        });
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
        const currentAssigneeIds = getIssueById(issueId)?.assignee_ids ?? [];
        await updateIssue(projectId, issueId, {
          ...data,
          registration_agent_id: agentId,
          // the server adds the registrar on top of the assignees sent, so
          // sending them also shows the registrar on the card right away
          assignee_ids: Array.from(new Set([...currentAssigneeIds, agentId])),
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
