/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useMemo, useState } from "react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
// plane imports
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
import { Button } from "@plane/propel/button";
import { setToast, TOAST_TYPE } from "@plane/propel/toast";
import { EModalPosition, EModalWidth, ModalCore } from "@plane/ui";
// hooks
import { useProject } from "@/hooks/store/use-project";
import { useUserPermissions } from "@/hooks/store/user";

/** Header action: join every project of the workspace the user is not a member of yet. */
export const JoinAllProjects = observer(function JoinAllProjects() {
  // states
  const [isOpen, setIsOpen] = useState(false);
  const [isJoining, setIsJoining] = useState(false);
  // router
  const { workspaceSlug } = useParams();
  // store hooks
  const { workspaceProjectIds, getProjectById, fetchProjects } = useProject();
  const { allowPermissions, joinProjects } = useUserPermissions();
  // derived values
  const isWorkspaceAdmin = allowPermissions([EUserPermissions.ADMIN], EUserPermissionsLevel.WORKSPACE);
  const canJoin = allowPermissions([EUserPermissions.ADMIN, EUserPermissions.MEMBER], EUserPermissionsLevel.WORKSPACE);

  const joinableProjectIds = useMemo(
    () =>
      (workspaceProjectIds ?? []).filter((id) => {
        const project = getProjectById(id);
        if (!project || project.member_role) return false;
        // backend rejects the whole request when a secret project is included for a non-admin
        return isWorkspaceAdmin || project.network !== 0;
      }),
    [workspaceProjectIds, getProjectById, isWorkspaceAdmin]
  );

  if (!workspaceSlug || !canJoin || joinableProjectIds.length === 0) return null;

  const handleJoin = async () => {
    setIsJoining(true);
    try {
      await joinProjects(workspaceSlug.toString(), joinableProjectIds);
      await fetchProjects(workspaceSlug.toString());
      setToast({
        type: TOAST_TYPE.SUCCESS,
        title: "Success!",
        message: `Joined ${joinableProjectIds.length} project${joinableProjectIds.length === 1 ? "" : "s"}.`,
      });
      setIsOpen(false);
    } catch {
      setToast({
        type: TOAST_TYPE.ERROR,
        title: "Error!",
        message: "Could not join all projects. Please try again.",
      });
    } finally {
      setIsJoining(false);
    }
  };

  return (
    <>
      <Button variant="secondary" size="lg" onClick={() => setIsOpen(true)} className="items-center gap-1">
        Join all projects
      </Button>
      <ModalCore
        isOpen={isOpen}
        handleClose={() => !isJoining && setIsOpen(false)}
        position={EModalPosition.CENTER}
        width={EModalWidth.XL}
      >
        <div className="space-y-5 px-5 py-8 sm:p-6">
          <h3 className="text-16 leading-6 font-medium text-primary">Join all projects?</h3>
          <p>
            You will be added to <span className="font-semibold">{joinableProjectIds.length}</span> project
            {joinableProjectIds.length === 1 ? "" : "s"} you are not a member of yet.
          </p>
        </div>
        <div className="mt-5 flex justify-end gap-2 px-5 pb-8 sm:px-6 sm:pb-6">
          <Button variant="secondary" size="lg" onClick={() => setIsOpen(false)} disabled={isJoining}>
            Cancel
          </Button>
          <Button variant="primary" size="lg" onClick={handleJoin} loading={isJoining}>
            {isJoining ? "Joining..." : "Join all"}
          </Button>
        </div>
      </ModalCore>
    </>
  );
});
