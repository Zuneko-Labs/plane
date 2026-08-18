# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
from datetime import timedelta
import logging
from typing import Callable, Iterable

# Django imports
from django.conf import settings
from django.utils import timezone
from django.db.models import F, Window, Subquery
from django.db.models.functions import RowNumber

# Third party imports
from celery import shared_task

# Module imports
from plane.db.models import (
    EmailNotificationLog,
    EventLog,
    PageVersion,
    APIActivityLog,
    IssueDescriptionVersion,
    WebhookLog,
)
from plane.utils.exception_logger import log_exception


logger = logging.getLogger("plane.worker")
BATCH_SIZE = 500


def process_cleanup_task(
    queryset_func: Callable[[], Iterable],
    model,
    task_name: str,
):
    """
    Batch-delete expired rows for the given model from PostgreSQL.

    Args:
        queryset_func: Callable returning an iterable of primary keys to delete.
        model: Django model class.
        task_name: Name of the task for logging.
    """
    logger.info(f"Starting {task_name} cleanup task")

    total_deleted = 0
    total_batches = 0
    batch: list = []

    def flush(ids: list) -> None:
        nonlocal total_deleted, total_batches
        if not ids:
            return
        total_batches += 1
        try:
            # `all_objects` is a plain manager, so this is a hard delete — rows
            # are removed from PostgreSQL immediately rather than soft-deleted.
            delete_result = model.all_objects.filter(id__in=ids).delete()
            deleted = delete_result[0] if isinstance(delete_result, tuple) else 0
            total_deleted += deleted
        except Exception as e:
            # Log and skip a failed batch rather than aborting the whole run, so
            # a single bad batch doesn't block cleanup of the remaining rows.
            log_exception(e)

    for record_id in queryset_func():
        batch.append(record_id)
        if len(batch) >= BATCH_SIZE:
            flush(batch)
            batch = []

    # Flush the final partial batch
    flush(batch)

    logger.info(
        f"{task_name} cleanup task completed",
        extra={"total_records_deleted": total_deleted, "total_batches": total_batches},
    )


# Queryset functions for each cleanup task — each yields primary keys to delete
def get_api_logs_queryset():
    """Get API activity logs older than the API retention window."""
    cutoff_time = timezone.now() - timedelta(days=settings.API_ACTIVITY_LOG_RETENTION_DAYS)
    logger.info(f"API logs cutoff time: {cutoff_time}")
    return (
        APIActivityLog.all_objects.filter(created_at__lte=cutoff_time)
        .values_list("id", flat=True)
        .iterator(chunk_size=BATCH_SIZE)
    )


def get_email_logs_queryset():
    """Get email logs older than the email retention window."""
    cutoff_time = timezone.now() - timedelta(days=settings.EMAIL_LOG_RETENTION_DAYS)
    logger.info(f"Email logs cutoff time: {cutoff_time}")
    return (
        EmailNotificationLog.all_objects.filter(sent_at__lte=cutoff_time)
        .values_list("id", flat=True)
        .iterator(chunk_size=BATCH_SIZE)
    )


def get_page_versions_queryset():
    """Get page versions beyond the maximum allowed (20 per page)."""
    subq = (
        PageVersion.all_objects.annotate(
            row_num=Window(
                expression=RowNumber(),
                partition_by=[F("page_id")],
                order_by=F("created_at").desc(),
            )
        )
        .filter(row_num__gt=20)
        .values("id")
    )

    return (
        PageVersion.all_objects.filter(id__in=Subquery(subq))
        .values_list("id", flat=True)
        .iterator(chunk_size=BATCH_SIZE)
    )


def get_issue_description_versions_queryset():
    """Get issue description versions beyond the maximum allowed (20 per issue)."""
    subq = (
        IssueDescriptionVersion.all_objects.annotate(
            row_num=Window(
                expression=RowNumber(),
                partition_by=[F("issue_id")],
                order_by=F("created_at").desc(),
            )
        )
        .filter(row_num__gt=20)
        .values("id")
    )

    return (
        IssueDescriptionVersion.all_objects.filter(id__in=Subquery(subq))
        .values_list("id", flat=True)
        .iterator(chunk_size=BATCH_SIZE)
    )


def get_webhook_logs_queryset():
    """Get webhook logs older than the webhook retention window."""
    cutoff_time = timezone.now() - timedelta(days=settings.WEBHOOK_LOG_RETENTION_DAYS)
    logger.info(f"Webhook logs cutoff time: {cutoff_time}")
    return (
        WebhookLog.all_objects.filter(created_at__lte=cutoff_time)
        .order_by("created_at")
        .values_list("id", flat=True)
        .iterator(chunk_size=BATCH_SIZE)
    )


@shared_task
def delete_api_logs():
    """Delete old API activity logs."""
    process_cleanup_task(
        queryset_func=get_api_logs_queryset,
        model=APIActivityLog,
        task_name="API Activity Log",
    )


@shared_task
def delete_email_notification_logs():
    """Delete old email notification logs."""
    process_cleanup_task(
        queryset_func=get_email_logs_queryset,
        model=EmailNotificationLog,
        task_name="Email Notification Log",
    )


@shared_task
def delete_page_versions():
    """Delete excess page versions."""
    process_cleanup_task(
        queryset_func=get_page_versions_queryset,
        model=PageVersion,
        task_name="Page Version",
    )


@shared_task
def delete_issue_description_versions():
    """Delete excess issue description versions."""
    process_cleanup_task(
        queryset_func=get_issue_description_versions_queryset,
        model=IssueDescriptionVersion,
        task_name="Issue Description Version",
    )


@shared_task
def delete_webhook_logs():
    """Delete old webhook logs."""
    process_cleanup_task(
        queryset_func=get_webhook_logs_queryset,
        model=WebhookLog,
        task_name="Webhook Log",
    )


def get_event_log_queryset():
    """Get outbox events past the event log retention window.

    Filters on `occurred_at`, not `created_at` — `occurred_at` is the wall
    clock the sync architecture treats as canonical for this table (see
    db/models/event_log.py), and is what the `event_log_occurred_idx` index
    is built for.

    Excludes rows still pending dispatch (`dispatched_at IS NULL`) — sweeping
    those would permanently lose a webhook/sync event that was never
    delivered (e.g. broker down longer than the retention window), instead of
    just running late.
    """
    cutoff_time = timezone.now() - timedelta(days=settings.EVENT_LOG_RETENTION_DAYS)
    logger.info(f"Event log cutoff time: {cutoff_time}")

    stuck = EventLog.all_objects.filter(occurred_at__lte=cutoff_time, dispatched_at__isnull=True).count()
    if stuck:
        logger.warning(f"{stuck} event_log rows past retention are still undispatched — skipping their deletion")

    return (
        EventLog.all_objects.filter(occurred_at__lte=cutoff_time, dispatched_at__isnull=False)
        .order_by("occurred_at")
        .values_list("id", flat=True)
        .iterator(chunk_size=BATCH_SIZE)
    )


@shared_task
def delete_event_logs():
    """Delete old outbox events past the retention window."""
    process_cleanup_task(
        queryset_func=get_event_log_queryset,
        model=EventLog,
        task_name="Event Log",
    )
