/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { Dispatch, SetStateAction } from "react";
import { observer } from "mobx-react";
// plane imports
import { cn } from "@plane/utils";
// hooks
import { useNotification } from "@/hooks/store/notifications/use-notification";
// local imports
import { NotificationItemArchiveOption } from "./archive";
import { NotificationItemReadOption } from "./read";
import { NotificationItemSnoozeOption } from "./snooze";

type TNotificationOption = {
  workspaceSlug: string;
  notificationId: string;
  isSnoozeStateModalOpen: boolean;
  setIsSnoozeStateModalOpen: Dispatch<SetStateAction<boolean>>;
  customSnoozeModal: boolean;
  setCustomSnoozeModal: Dispatch<SetStateAction<boolean>>;
};

export const NotificationOption = observer(function NotificationOption(props: TNotificationOption) {
  const {
    workspaceSlug,
    notificationId,
    isSnoozeStateModalOpen,
    setIsSnoozeStateModalOpen,
    customSnoozeModal,
    setCustomSnoozeModal,
  } = props;
  // hooks
  const notification = useNotification(notificationId);

  return (
    <div
      className={cn(
        "invisible flex-shrink-0 text-body-xs-medium opacity-0 transition-opacity group-focus-within:visible group-focus-within:opacity-100 group-hover:visible group-hover:opacity-100",
        { "visible opacity-100": isSnoozeStateModalOpen || customSnoozeModal }
      )}
    >
      <div className="relative flex items-center justify-center gap-2">
        {/* read */}
        <NotificationItemReadOption workspaceSlug={workspaceSlug} notification={notification} />

        {/* archive */}
        <NotificationItemArchiveOption workspaceSlug={workspaceSlug} notification={notification} />

        {/* snooze notification */}
        <NotificationItemSnoozeOption
          workspaceSlug={workspaceSlug}
          notification={notification}
          setIsSnoozeStateModalOpen={setIsSnoozeStateModalOpen}
          customSnoozeModal={customSnoozeModal}
          setCustomSnoozeModal={setCustomSnoozeModal}
        />
      </div>
    </div>
  );
});
