# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Transactional outbox for the incremental sync architecture.

``write_event`` is called from view code, in the same transaction as the
mutation it records. From there, two independent paths pick the row up:

  * ``transaction.on_commit(dispatch_event.delay)`` — a fast path, giving
    sub-second webhook latency in the common case.
  * ``relay_events`` — a Celery-beat sweeper that claims anything the fast
    path missed (e.g. the broker was unreachable when ``.delay()`` ran). The
    ``event_log`` row is already committed by the time either path looks at
    it, so nothing is lost even if the fast path never fires.

Both paths claim a row via the same atomic, NULL-guarded UPDATE, so whichever
one gets there first wins and the other is a no-op — an event is never
double-dispatched by both paths racing each other.
"""

import json
import logging
from typing import Any, Dict, Optional, Union
from uuid import UUID

from celery import shared_task

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.core.serializers.json import DjangoJSONEncoder
from django.db import connection, transaction
from django.utils import timezone

from plane.api.serializers import (
    EstimateSerializer,
    EstimatePointSerializer,
    IssueAttachmentSerializer,
    IssueLinkSerializer,
    IssueRelationSerializer,
    LabelSerializer,
    ProjectMemberSerializer,
    StateSerializer,
)
from plane.app.serializers import WorkSpaceMemberSerializer
from plane.bgtasks.webhook_task import get_model_data, webhook_send_task
from plane.db.models import (
    Estimate,
    EstimatePoint,
    EventLog,
    FileAsset,
    IssueLink,
    IssueRelation,
    Label,
    ProjectMember,
    State,
    Webhook,
    WorkspaceMember,
)
from plane.utils.exception_logger import log_exception

logger = logging.getLogger("plane.worker")

# Arbitrary, fixed key for the relay's single-writer lock — the value itself
# carries no meaning, it just needs to be the same constant everywhere this
# runs. Held only for the duration of the claiming transaction (advisory
# *xact* lock releases automatically at commit/rollback).
_RELAY_ADVISORY_LOCK_KEY = 890321001

# Maps event_log.entity_type to the boolean flag on Webhook that gates
# whether an active webhook receives that entity's events. Entity types
# absent from this map (e.g. the Phase 9 reference entities) have no webhook
# flag yet and are skipped here — they still flow to the event_log pull API.
_WEBHOOK_FILTER_FIELD = {
    "project": "project",
    "issue": "issue",
    "module": "module",
    "module_issue": "module",
    "cycle": "cycle",
    "cycle_issue": "cycle",
    "issue_comment": "issue_comment",
}

# Phase 9 reference entities. Kept local rather than added to
# webhook_task.SERIALIZER_MAPPER/MODEL_MAPPER so that module — which drives
# today's webhook fan-out — stays untouched and merge-clean. These entity
# types are absent from _WEBHOOK_FILTER_FIELD above, so they flow only to
# event_log, never to webhooks.
_LOCAL_SERIALIZER_MAPPER = {
    "state": StateSerializer,
    "label": LabelSerializer,
    "workspace_member": WorkSpaceMemberSerializer,
    "project_member": ProjectMemberSerializer,
    "issue_link": IssueLinkSerializer,
    "issue_attachment": IssueAttachmentSerializer,
    "issue_relation": IssueRelationSerializer,
    "estimate": EstimateSerializer,
    "estimate_point": EstimatePointSerializer,
}

_LOCAL_MODEL_MAPPER = {
    "state": State,
    "label": Label,
    "workspace_member": WorkspaceMember,
    "project_member": ProjectMember,
    "issue_link": IssueLink,
    "issue_attachment": FileAsset,
    "issue_relation": IssueRelation,
    "estimate": Estimate,
    "estimate_point": EstimatePoint,
}


def _get_model_data(model_name: str, model_id: Union[str, UUID]) -> Dict[str, Any]:
    """
    Serialize a model instance for an event_log snapshot. Checks the Phase 9
    local mapping first; falls back to webhook_task's mapper for the entity
    types wired there since Phase 4-6.
    """
    serializer_class = _LOCAL_SERIALIZER_MAPPER.get(model_name)
    model = _LOCAL_MODEL_MAPPER.get(model_name)
    if serializer_class is None or model is None:
        return get_model_data(event=model_name, event_id=model_id)
    instance = model.objects.get(pk=model_id)
    return serializer_class(instance).data


def write_event(
    *,
    workspace_id: UUID,
    entity_type: str,
    entity_id: UUID,
    event_type: str,
    project_id: Optional[UUID] = None,
    actor_id: Optional[UUID] = None,
    data: Optional[Dict[str, Any]] = None,
    changes: Optional[Dict[str, Any]] = None,
) -> EventLog:
    """
    Record one outbox event. Must be called inside the caller's own
    transaction so the row commits atomically with the mutation it
    describes — this function does not open its own transaction.

    Returns the created row; the caller is responsible for scheduling
    delivery, typically:

        event = write_event(...)
        transaction.on_commit(lambda: dispatch_event.delay(event_log_id=str(event.id)))
    """
    return EventLog.objects.create(
        workspace_id=workspace_id,
        project_id=project_id,
        entity_type=entity_type,
        entity_id=entity_id,
        event_type=event_type,
        actor_id=actor_id,
        occurred_at=timezone.now(),
        data=data,
        changes=changes,
    )


def write_model_event(
    *,
    model_name: str,
    model_id: Union[str, UUID],
    requested_data: Optional[Dict[str, Any]],
    current_instance: Optional[Union[str, Dict[str, Any]]],
    actor_id: Optional[UUID],
    workspace_id: UUID,
    project_id: Optional[UUID] = None,
) -> EventLog:
    """
    A near drop-in parallel to the existing ``model_activity.delay(...)``
    call at each of the 24 dispatch sites — same created/updated detection
    (``current_instance is None`` means created), same requested-data diff —
    but written as one row instead of one row per changed key, and with a
    snapshot captured now rather than re-derived when a webhook eventually
    sends. Called alongside the existing ``model_activity.delay(...)``, not
    instead of it; that call still drives today's per-field webhook path
    unchanged.
    """
    event_type = f"{model_name}.{'created' if current_instance is None else 'updated'}"

    changes = None
    if current_instance is not None and requested_data is not None:
        current = json.loads(current_instance) if isinstance(current_instance, str) else current_instance
        diff = {
            key: {"old": current.get(key), "new": requested_data.get(key)}
            for key in requested_data
            if key in current and current.get(key) != requested_data.get(key)
        }
        changes = diff or None

    try:
        data = _get_model_data(model_name, model_id)
        # DRF serializer output can contain UUID/datetime objects a plain
        # JSONField write can't encode on its own — normalize the same way
        # webhook_task.py already does before it ever leaves Python.
        data = json.loads(json.dumps(data, cls=DjangoJSONEncoder))
    except ObjectDoesNotExist:
        data = None

    return write_event(
        workspace_id=workspace_id,
        project_id=project_id,
        entity_type=model_name,
        entity_id=model_id,
        event_type=event_type,
        actor_id=actor_id,
        data=data,
        changes=changes,
    )


def write_delete_event(
    *,
    model_name: str,
    entity_id: Union[str, UUID],
    actor_id: Optional[UUID],
    workspace_id: UUID,
    project_id: Optional[UUID] = None,
) -> EventLog:
    """A drop-in parallel to the existing ``webhook_activity.delay(verb="deleted", ...)`` calls."""
    return write_event(
        workspace_id=workspace_id,
        project_id=project_id,
        entity_type=model_name,
        entity_id=entity_id,
        event_type=f"{model_name}.deleted",
        actor_id=actor_id,
        data=None,
        changes=None,
    )


def write_archive_event(
    *,
    model_name: str,
    model_id: Union[str, UUID],
    archived: bool,
    actor_id: Optional[UUID],
    workspace_id: UUID,
    project_id: Optional[UUID] = None,
) -> EventLog:
    """
    Archive/unarchive events, for the 8 archive/unarchive endpoints. These
    take no meaningful request body, so ``model_activity``'s diff (which
    only looks at keys present in the request) produces nothing for them —
    unlike ``write_model_event``, this always writes a direct snapshot.
    """
    try:
        data = _get_model_data(model_name, model_id)
        data = json.loads(json.dumps(data, cls=DjangoJSONEncoder))
    except ObjectDoesNotExist:
        data = None

    return write_event(
        workspace_id=workspace_id,
        project_id=project_id,
        entity_type=model_name,
        entity_id=model_id,
        event_type=f"{model_name}.{'archived' if archived else 'unarchived'}",
        actor_id=actor_id,
        data=data,
        changes=None,
    )


def _claim_event(event_id) -> bool:
    """Atomically mark one row dispatched, only if still pending. Returns
    whether this call was the one that claimed it."""
    with connection.cursor() as cur:
        cur.execute(
            """
            UPDATE event_log
            SET dispatch_seq = nextval('event_log_dispatch_seq_seq'), dispatched_at = NOW()
            WHERE id = %s AND dispatched_at IS NULL
            """,
            [str(event_id)],
        )
        return cur.rowcount > 0


def _fanout_webhooks(event: EventLog) -> None:
    filter_field = _WEBHOOK_FILTER_FIELD.get(event.entity_type)
    if filter_field is None:
        return

    verb = event.event_type.rsplit(".", 1)[-1]
    current_site = settings.APP_BASE_URL or settings.WEB_URL

    webhooks = Webhook.objects.filter(workspace_id=event.workspace_id, is_active=True, **{filter_field: True})
    for webhook in webhooks:
        webhook_send_task.delay(
            webhook_id=str(webhook.id),
            slug=event.workspace.slug,
            event=event.entity_type,
            event_data=({"id": str(event.entity_id)} if event.data is None else event.data),
            action=verb,
            current_site=current_site,
            activity={"changes": event.changes} if event.changes else None,
            outbox_event_id=str(event.id),
            dispatch_seq=event.dispatch_seq,
        )


@shared_task
def dispatch_event(event_log_id: str) -> None:
    """The on_commit fast path for a single, already-committed event."""
    try:
        if not _claim_event(event_log_id):
            # The relay already claimed it first — nothing to do.
            return
        event = EventLog.objects.select_related("workspace").get(id=event_log_id)
        _fanout_webhooks(event)
    except Exception as e:
        log_exception(e)


@shared_task
def relay_events(batch_size: int = 500) -> None:
    """
    Beat sweeper — the correctness backstop. Claims and dispatches anything
    still pending, in insert order. The advisory lock only guards the claim
    phase (held inside the atomic block below, released at its commit) so
    two sweeps can never claim the same row out of order; it does not extend
    to the fan-out loop after. That's fine — a claimed row's `dispatched_at`
    is already set and committed by the time fan-out runs, so an overlapping
    sweep has nothing left to claim there.
    """
    claimed_ids = []
    with transaction.atomic():
        with connection.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_xact_lock(%s)", [_RELAY_ADVISORY_LOCK_KEY])
            (acquired,) = cur.fetchone()
        if not acquired:
            return

        pending_ids = list(
            EventLog.objects.filter(dispatched_at__isnull=True).order_by("sequence").values_list("id", flat=True)[
                :batch_size
            ]
        )
        for event_id in pending_ids:
            if _claim_event(event_id):
                claimed_ids.append(event_id)

    if not claimed_ids:
        return

    events_by_id = EventLog.objects.filter(id__in=claimed_ids).select_related("workspace").in_bulk()
    for event_id in claimed_ids:
        event = events_by_id.get(event_id)
        if event is None:
            continue
        try:
            _fanout_webhooks(event)
        except Exception as e:
            log_exception(e)
