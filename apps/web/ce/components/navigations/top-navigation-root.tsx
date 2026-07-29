/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// components
import { useState } from "react";
import { observer } from "mobx-react";
import { useParams, usePathname } from "next/navigation";
import { cn, calculateTimeAgo } from "@plane/utils";
import { TopNavPowerK } from "@/components/navigation";
import { HelpMenuRoot } from "@/components/workspace/sidebar/help-section/root";
import { UserMenuRoot } from "@/components/workspace/sidebar/user-menu-root";
import { WorkspaceMenuRoot } from "@/components/workspace/sidebar/workspace-menu-root";
import { useAppRailPreferences } from "@/hooks/use-navigation-preferences";
import { AppSidebarItem } from "@/components/sidebar/sidebar-item";
import { InboxIcon } from "@plane/propel/icons";
import useSWR from "swr";
import { useWorkspaceNotifications } from "@/hooks/store/notifications";
import { useWorkspace } from "@/hooks/store/use-workspace";
import { NotificationContent } from "@/components/workspace-notifications/sidebar/notification-card/content";

export const TopNavigationRoot = observer(function TopNavigationRoot() {
  // router
  const { workspaceSlug } = useParams();
  const pathname = usePathname();

  // store hooks
  const {
    unreadNotificationsCount,
    getUnreadNotificationsCount,
    getAllAndMentionedNotifications,
    notifications,
    isInboxPreviewOpen,
    setIsInboxPreviewOpen,
  } = useWorkspaceNotifications();
  const { preferences } = useAppRailPreferences();
  const { currentWorkspace } = useWorkspace();
  // states
  const [isHoveringPreview, setIsHoveringPreview] = useState(false);

  const showLabel = preferences.displayMode === "icon_with_label";

  // Fetch notification count
  useSWR(
    workspaceSlug ? "WORKSPACE_UNREAD_NOTIFICATION_COUNT" : null,
    workspaceSlug ? () => getUnreadNotificationsCount(workspaceSlug.toString()) : null
  );

  // Fetch the notification list itself (not just the unread count) so the hover preview has
  // data ready on every page, not only after the home page or dedicated notifications page
  // happens to have populated the store first.
  useSWR(
    workspaceSlug ? `TOP_NAV_NOTIFICATIONS_PREVIEW_${workspaceSlug}` : null,
    workspaceSlug ? () => getAllAndMentionedNotifications(workspaceSlug.toString()) : null,
    {
      revalidateIfStale: true,
      revalidateOnFocus: false,
      revalidateOnReconnect: true,
    }
  );

  // The backend's "total_unread_notifications_count" is actually just the non-mention bucket —
  // it's a separate, non-overlapping count from "mention_unread_notifications_count", not an
  // aggregate that already includes mentions. Sum both to get the true combined unread count.
  const totalNotifications =
    unreadNotificationsCount.total_unread_notifications_count +
    unreadNotificationsCount.mention_unread_notifications_count;
  const totalNotificationsLabel = totalNotifications > 99 ? "99+" : totalNotifications;

  // Auto-popup (on home page landing) only shows a compact "new messages" nudge when there
  // are unread notifications; hovering the icon always shows the full 5-item queue.
  const showAutoBanner = isInboxPreviewOpen && !isHoveringPreview && totalNotifications > 0;
  const showFullPreview = isHoveringPreview;

  // First 5 most recent UNREAD notifications for the hover preview — both regular activity
  // and mentions are combined here (unlike the dedicated Notifications page, which splits
  // them into separate "All"/"Mentions" tabs). Once a notification is opened or marked as
  // read (individually or via "mark all as read"), it drops out of the queue.
  const previewNotificationIds = currentWorkspace
    ? Object.values(notifications)
        .filter(
          (notification) =>
            notification.workspace === currentWorkspace.id && !notification.read_at && !notification.archived_at
        )
        // eslint-disable-next-line unicorn/no-array-sort -- `.filter()` above always returns a fresh array, so sorting it in place is safe (no shared/mutated state); `toSorted()` isn't available in this project's configured TS lib target
        .sort((a, b) => new Date(b.created_at ?? 0).getTime() - new Date(a.created_at ?? 0).getTime())
        .slice(0, 5)
        .map((notification) => notification.id)
    : [];

  return (
    <div
      className={cn("z-[27] flex min-h-10 w-full items-center bg-canvas px-3.5 transition-all duration-300", {
        "px-2": !showLabel,
      })}
    >
      {/* Workspace Menu */}
      <div className="flex-1 shrink-0">
        <WorkspaceMenuRoot variant="top-navigation" />
      </div>
      {/* Power K Search */}
      <div className="shrink-0">
        <TopNavPowerK />
      </div>
      {/* Additional Actions */}
      <div className="flex flex-1 shrink-0 items-center justify-end gap-1">
        <div
          className="relative"
          onMouseEnter={() => setIsHoveringPreview(true)}
          onMouseLeave={() => {
            setIsHoveringPreview(false);
            if (isInboxPreviewOpen) setIsInboxPreviewOpen(false);
          }}
        >
          <AppSidebarItem
            variant="link"
            item={{
              href: `/${workspaceSlug?.toString()}/notifications/`,
              icon: (
                <div className="relative">
                  <InboxIcon className="size-5" />
                  {totalNotifications > 0 && (
                    <span className="absolute -top-1.5 -right-1.5 flex h-3.5 min-w-3.5 items-center justify-center rounded-full bg-danger-primary px-0.5 text-[9px] leading-none font-medium text-white">
                      {totalNotificationsLabel}
                    </span>
                  )}
                </div>
              ),
              isActive: pathname?.includes("/notifications/"),
            }}
          />
          {showAutoBanner && (
            <div className="absolute top-full right-0 z-50 mt-2 w-max rounded-lg border border-subtle-1 bg-layer-2 px-3 py-2 shadow-overlay-200">
              <p className="text-caption-sm-regular text-primary">You have new messages</p>
            </div>
          )}
          {showFullPreview && (
            <div className="absolute top-full right-0 z-50 mt-2 w-80 rounded-lg border border-subtle-1 bg-layer-2 p-2 shadow-overlay-200">
              <p className="px-2 py-1 text-caption-md-medium text-primary">Inbox</p>
              {previewNotificationIds.length === 0 ? (
                <p className="px-2 py-2 text-caption-sm-regular text-secondary">No new notifications</p>
              ) : (
                <div className="flex flex-col gap-0.5">
                  {previewNotificationIds.map((notificationId) => {
                    const notification = notifications[notificationId];
                    if (!notification) return null;
                    return (
                      <div key={notificationId} className="rounded-md px-2 py-1.5 hover:bg-layer-1">
                        <p className="line-clamp-1 text-13 text-primary">
                          <NotificationContent
                            notification={notification.asJson}
                            workspaceId={currentWorkspace?.id ?? ""}
                            workspaceSlug={workspaceSlug.toString()}
                            projectId={notification.project ?? ""}
                          />
                        </p>
                        <p className="text-11 text-tertiary">{calculateTimeAgo(notification.created_at ?? null)}</p>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}
        </div>
        <HelpMenuRoot />
        <div className="flex size-8 items-center justify-center rounded-md hover:bg-layer-1-hover">
          <UserMenuRoot />
        </div>
      </div>
    </div>
  );
});
