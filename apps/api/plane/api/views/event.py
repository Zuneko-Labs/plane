# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Incremental sync — the pull-API half of the outbox architecture. Consumers
poll this endpoint with a ``dispatch_seq`` checkpoint instead of registering
a webhook, and pick up exactly where they left off after downtime.
"""

# Python imports
from uuid import UUID

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.db.models import EventLog, User
from plane.utils.permissions import WorkSpaceAdminPermission
from .base import BaseAPIView

# Postgres bigint upper bound — dispatch_seq's column type.
_MAX_BIGINT = 9223372036854775807


def _collect_user_id_candidates(data: dict) -> set:
    """
    Every entity's ``data`` snapshot is that entity's own DRF serializer
    output (see event_outbox._get_model_data) — field names for "who did
    this" vary per entity (project: created_by/updated_by/project_lead;
    module: lead/members; issue: assignees; ...) and are not worth
    hardcoding one by one. Instead: pull every UUID-shaped value out of the
    (shallow) dict — plus one level into list values, for M2M fields like
    ``members``/``assignees`` — and let the caller resolve whichever of
    them turn out to be real users in one batched query.
    """
    candidates = set()
    for value in data.values():
        if isinstance(value, str):
            try:
                candidates.add(UUID(value))
            except ValueError:
                pass
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    try:
                        candidates.add(UUID(item))
                    except ValueError:
                        pass
    return candidates


def _resolve_users_in_data(data: dict, users_by_id: dict) -> dict:
    """
    Replace every UUID string in ``data`` that is one of this page's known
    user ids (whatever key it's under — created_by, updated_by, lead,
    members, assignees, ... every entity names these differently) with an
    inline ``{"id", "name", "email"}`` object, so a consumer reads a name
    directly off the field instead of cross-referencing a lookup table.
    UUIDs that aren't users (workspace/project/state/parent/etc. ids) are
    left as-is — those are already surfaced via this event's top-level
    workspace_slug/project_name fields, or are structural foreign keys with
    no single "name" of their own.
    """
    resolved = {}
    for key, value in data.items():
        if isinstance(value, str) and value in users_by_id:
            resolved[key] = users_by_id[value]
        elif isinstance(value, list) and value and all(isinstance(item, str) for item in value):
            resolved[key] = [users_by_id.get(item, item) for item in value]
        else:
            resolved[key] = value
    return resolved


def _serialize_event(event: EventLog, users_by_id: dict) -> dict:
    # `data` carries the entity's full snapshot for created/updated events
    # (see db/models/event_log.py) — its "name" is the only place an entity's
    # display name is available; a `deleted` event's `data` is NULL, so there
    # is no name to surface for those (the row only ever stored entity_id).
    entity_name = event.data.get("name") if event.data else None
    data = _resolve_users_in_data(event.data, users_by_id) if event.data else event.data

    return {
        "id": str(event.id),
        "dispatch_seq": event.dispatch_seq,
        "event_type": event.event_type,
        "schema_version": event.schema_version,
        "workspace_id": str(event.workspace_id),
        "workspace_slug": event.workspace.slug,
        "project_id": str(event.project_id) if event.project_id else None,
        "project_name": event.project.name if event.project_id else None,
        "entity_type": event.entity_type,
        "entity_id": str(event.entity_id),
        "entity_name": entity_name,
        "actor_id": str(event.actor_id) if event.actor_id else None,
        "actor_name": event.actor.display_name if event.actor_id else None,
        "actor_email": event.actor.email if event.actor_id else None,
        "occurred_at": event.occurred_at.isoformat(),
        "data": data,
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
        base_qs = EventLog.objects.filter(workspace__slug=slug, dispatch_seq__isnull=False).select_related(
            "workspace", "project", "actor"
        )

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

        candidate_ids = set()
        for event in events:
            if event.data:
                candidate_ids |= _collect_user_id_candidates(event.data)
        users_by_id = {
            str(user_id): {"id": str(user_id), "name": display_name, "email": email}
            for user_id, display_name, email in User.objects.filter(id__in=candidate_ids).values_list(
                "id", "display_name", "email"
            )
        }

        return Response(
            {
                "results": [_serialize_event(event, users_by_id) for event in events],
                "next_after": events[-1].dispatch_seq if events else after,
                "has_more": has_more,
            },
            status=status.HTTP_200_OK,
        )


class WorkspaceEventsCheckpointAPIEndpoint(BaseAPIView):
    """
    GET /api/v1/workspaces/{slug}/events/checkpoint/

    Bootstrap endpoint for a consumer that has no checkpoint yet (new
    integration, or one whose stored checkpoint was rejected with 410
    GONE because it fell outside the retention window — see
    WorkspaceEventsAPIEndpoint). Retention deletes events unconditionally
    on `occurred_at`, so `after=0` is not a durable starting point once
    any purge has run.

    Returns the current max dispatch_seq. The consumer's bootstrap
    sequence is: 1) call this endpoint, 2) fetch full current state via
    the regular list APIs (issues/cycles/etc), 3) start polling
    /events/?after=<latest_dispatch_seq> going forward. Events dispatched
    between steps 1 and 2 are naturally re-observed as no-op updates by
    the consumer's own upsert logic, so ordering between the two steps
    is not load-bearing.
    """

    permission_classes = [WorkSpaceAdminPermission]
    use_read_replica = True

    def get(self, request, slug):
        latest_dispatch_seq = (
            EventLog.objects.filter(workspace__slug=slug, dispatch_seq__isnull=False)
            .order_by("-dispatch_seq")
            .values_list("dispatch_seq", flat=True)
            .first()
        ) or 0

        return Response({"latest_dispatch_seq": latest_dispatch_seq}, status=status.HTTP_200_OK)
