/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import useSWR from "swr";
// plane imports
import { ENotificationLoader, ENotificationQueryParamType } from "@plane/constants";
import { getNumberCount } from "@plane/utils";
// components
import { CountChip } from "@/components/common/count-chip";
// hooks
import { useWorkspaceNotifications } from "@/hooks/store/notifications";
import { useWorkspace } from "@/hooks/store/use-workspace";

type TNotificationAppSidebarOption = {
  workspaceSlug: string;
};

export const NotificationAppSidebarOption = observer(function NotificationAppSidebarOption(
  props: TNotificationAppSidebarOption
) {
  const { workspaceSlug } = props;
  // hooks
  const { unreadNotificationsCount, getUnreadNotificationsCount, notificationIdsByWorkspaceId, getNotifications } =
    useWorkspaceNotifications();
  const { getWorkspaceBySlug } = useWorkspace();

  useSWR(
    workspaceSlug ? "WORKSPACE_UNREAD_NOTIFICATION_COUNT" : null,
    workspaceSlug ? () => getUnreadNotificationsCount(workspaceSlug) : null
  );

  // Prefetch the notification list in the background (shares the SWR cache key with
  // NotificationsRoot) so the inbox has data ready the moment it's opened, instead of
  // only starting the fetch once the user navigates to the notifications page.
  const workspaceId = workspaceSlug ? getWorkspaceBySlug(workspaceSlug)?.id : undefined;
  const hasExistingNotifications = Boolean(workspaceId && notificationIdsByWorkspaceId(workspaceId));
  const notificationMutation = hasExistingNotifications
    ? ENotificationLoader.MUTATION_LOADER
    : ENotificationLoader.INIT_LOADER;
  const notificationLoader = hasExistingNotifications
    ? ENotificationQueryParamType.CURRENT
    : ENotificationQueryParamType.INIT;
  useSWR(
    workspaceSlug ? `WORKSPACE_NOTIFICATION_${workspaceSlug}` : null,
    workspaceSlug ? () => getNotifications(workspaceSlug, notificationMutation, notificationLoader) : null
  );

  // derived values
  const isMentionsEnabled = unreadNotificationsCount.mention_unread_notifications_count > 0;
  const totalNotifications = isMentionsEnabled
    ? unreadNotificationsCount.mention_unread_notifications_count
    : unreadNotificationsCount.total_unread_notifications_count;

  if (totalNotifications <= 0) return <></>;

  return (
    <div className="ml-auto">
      <CountChip count={`${isMentionsEnabled ? `@ ` : ``}${getNumberCount(totalNotifications)}`} />
    </div>
  );
});
