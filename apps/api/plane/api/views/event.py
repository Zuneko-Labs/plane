# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Incremental sync — the pull-API half of the outbox architecture. Consumers
poll this endpoint with a ``dispatch_seq`` checkpoint instead of registering
a webhook, and pick up exactly where they left off after downtime.
"""

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.db.models import EventLog
from plane.utils.permissions import WorkSpaceAdminPermission
from .base import BaseAPIView

# Postgres bigint upper bound — dispatch_seq's column type.
_MAX_BIGINT = 9223372036854775807


def _serialize_event(event: EventLog) -> dict:
    return {
        "id": str(event.id),
        "dispatch_seq": event.dispatch_seq,
        "event_type": event.event_type,
        "schema_version": event.schema_version,
        "workspace_id": str(event.workspace_id),
        "project_id": str(event.project_id) if event.project_id else None,
        "entity_type": event.entity_type,
        "entity_id": str(event.entity_id),
        "actor_id": str(event.actor_id) if event.actor_id else None,
        "occurred_at": event.occurred_at.isoformat(),
        "data": event.data,
        "changes": event.changes,
    }


class WorkspaceEventsAPIEndpoint(BaseAPIView):
    """
    GET /api/v1/workspaces/{slug}/events/?after={dispatch_seq}&per_page={M}

    ``dispatch_seq`` is a gap-free, commit-ordered cursor (see
    bgtasks/event_outbox.py) — a consumer that has seen up to N is guaranteed
    to see every event that will ever carry a dispatch_seq <= N. Rows with
    dispatch_seq IS NULL are still outbox-pending and are never returned;
    they will appear once the relay or the on_commit fast path claims them.
    """

    permission_classes = [WorkSpaceAdminPermission]
    use_read_replica = True

    def get(self, request, slug):
        try:
            after = int(request.GET.get("after", 0))
        except (TypeError, ValueError):
            return Response({"error": "after must be an integer"}, status=status.HTTP_400_BAD_REQUEST)
        if after < 0 or after > _MAX_BIGINT:
            return Response({"error": "after must be a valid bigint"}, status=status.HTTP_400_BAD_REQUEST)

        per_page = self.get_per_page(request, default_per_page=200, max_per_page=1000)

        # Workspace scoping is enforced here, in the query itself — not in the
        # serializer — so `after` can never be used to probe another
        # tenant's row count or content.
        base_qs = EventLog.objects.filter(workspace__slug=slug, dispatch_seq__isnull=False)

        oldest_dispatch_seq = base_qs.order_by("dispatch_seq").values_list("dispatch_seq", flat=True).first()
        # A gap between `after` and the oldest row still retained means
        # events in between were deleted by retention — silently returning
        # an empty page here would be indistinguishable from "caught up".
        if oldest_dispatch_seq is not None and after < oldest_dispatch_seq - 1:
            return Response(
                {"error": "Requested checkpoint is past the retention window; a full resync is required."},
                status=status.HTTP_410_GONE,
            )

        events = list(base_qs.filter(dispatch_seq__gt=after).order_by("dispatch_seq")[: per_page + 1])
        has_more = len(events) > per_page
        events = events[:per_page]

        return Response(
            {
                "results": [_serialize_event(event) for event in events],
                "next_after": events[-1].dispatch_seq if events else after,
                "has_more": has_more,
            },
            status=status.HTTP_200_OK,
        )
