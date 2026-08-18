# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.db import models

# Module imports
from plane.db.models import BaseModel


class EventLog(BaseModel):
    """
    Append-only transactional outbox. Every mutation the sync architecture
    covers writes one row here in the same DB transaction as the mutation
    itself; the relay (a Celery beat sweeper) later stamps `dispatch_seq` and
    fans the row out to webhooks and the incremental pull API.

    `sequence` is insert order and is internal only — it exists purely so the
    relay can claim pending rows in a stable order. `dispatch_seq` is
    commit order, assigned by the relay after the row is committed and
    visible, and is the only field a consumer may use as a cursor: a
    Postgres identity/sequence value handed out at insert time can commit
    out of order under concurrent transactions, which silently reopens gaps
    a consumer has already advanced past. `dispatch_seq` cannot have that
    problem because it is never assigned before commit.
    """

    # Insert-order tiebreak / relay pickup order. Auto-populated by a
    # Postgres sequence + BEFORE INSERT trigger (see the 0126 migration) —
    # not a GENERATED ALWAYS AS IDENTITY column, because Django's ORM always
    # sends an explicit value (including NULL) for every field on INSERT,
    # which is incompatible with identity-column semantics that only
    # auto-generate when the column is omitted from the insert list.
    sequence = models.BigIntegerField(null=True, editable=False)

    # The consumer cursor. NULL until the relay claims and stamps this row;
    # never assigned before commit.
    dispatch_seq = models.BigIntegerField(null=True, editable=False, unique=True)

    # NULL means "outbox pending" — this is the relay's work queue.
    dispatched_at = models.DateTimeField(null=True, blank=True)

    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="event_logs")
    # NULL for workspace-scoped events (e.g. WorkspaceMember changes).
    project = models.ForeignKey(
        "db.Project", on_delete=models.CASCADE, related_name="event_logs", null=True, blank=True
    )

    # e.g. "project", "issue", "state" — matches the existing webhook `event`
    # vocabulary where one exists.
    entity_type = models.CharField(max_length=255)
    entity_id = models.UUIDField()
    # "{entity_type}.{created|updated|archived|unarchived|deleted}"
    event_type = models.CharField(max_length=255)

    # NULL for system-generated changes (no request-scoped user).
    actor = models.ForeignKey(
        "db.User", on_delete=models.SET_NULL, related_name="event_logs", null=True, blank=True
    )

    # Wall clock — NOT an ordering key. Used only for the retention sweep and
    # for display; ties are possible and expected.
    occurred_at = models.DateTimeField()

    # Full snapshot via the entity's existing DRF serializer. NULL for a
    # `deleted` event, which carries only `entity_id`.
    data = models.JSONField(null=True, blank=True)
    # All fields changed by this mutation, in one row — this is what fixes
    # the per-field webhook fan-out at the source. NULL for created/deleted,
    # where a diff is meaningless.
    changes = models.JSONField(null=True, blank=True)

    # Additive-only wire contract: fields are added, never removed or
    # repurposed. Consumers ignore fields they don't recognize.
    schema_version = models.SmallIntegerField(default=1)

    class Meta:
        verbose_name = "Event Log"
        verbose_name_plural = "Event Logs"
        db_table = "event_log"
        ordering = ("sequence",)
        indexes = [
            # The consumer query: WHERE workspace_id = ? AND dispatch_seq > ?
            models.Index(fields=["workspace", "dispatch_seq"], name="event_log_ws_dispatch_idx"),
            # The retention sweep's WHERE occurred_at <= cutoff.
            models.Index(fields=["occurred_at"], name="event_log_occurred_idx"),
            # The relay's pickup query. Partial so it stays tiny — it only
            # ever covers the pending backlog, not the whole table.
            models.Index(
                fields=["dispatched_at"],
                name="event_log_pending_idx",
                condition=models.Q(dispatched_at__isnull=True),
            ),
        ]

    def __str__(self):
        return f"{self.entity_type}:{self.entity_id} {self.event_type}"
