# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import json
from datetime import timedelta

# Third party imports
from celery import shared_task

# Django imports
from django.db import IntegrityError
from django.utils import timezone

# Module imports
from plane.bgtasks.issue_activities_task import issue_activity
from plane.bgtasks.issue_description_version_task import issue_description_version_task
from plane.db.models import Issue, IssueAssignee, IssueLabel, IssueRecurrence
from plane.utils.exception_logger import log_exception
from plane.utils.recurrence import add_interval, next_month_day


def _occurrence_dates(source, anchor):
    """Compute a new occurrence's (start, target) from the live source issue.

    The occurrence starts on its scheduled ``anchor`` date and preserves the
    source's start->target duration. Missing source dates stay missing.
    """
    if source.start_date and source.target_date:
        duration = (source.target_date - source.start_date).days
        return anchor, anchor + timedelta(days=duration)
    if source.start_date:
        return anchor, None
    if source.target_date:
        return None, anchor
    return None, None


def _create_occurrence(recurrence, anchor):
    """Create one work item cloned from the LIVE source issue, anchored at
    ``anchor``. Reading the source live (not a frozen snapshot) means later
    edits to the source — assignees, dates, labels, description — are reflected
    in every future occurrence.

    Returns the created issue, or None if creation failed.
    """
    source = recurrence.source_issue
    project_id = recurrence.project_id
    workspace_id = recurrence.workspace_id
    created_by_id = recurrence.created_by_id

    start_date, target_date = _occurrence_dates(source, anchor)

    issue = Issue(
        project_id=project_id,
        name=source.name,
        description_html=source.description_html,
        description_json=source.description_json,
        priority=source.priority,
        # State is left unset — Issue.save() auto-assigns the project's
        # default state (Todo) whenever state is None (see
        # Issue._ensure_default_state). Occurrences land in Todo like any
        # other work item, matching what the client asked for instead of a
        # dedicated "Recurring" state.
        parent_id=source.parent_id,
        estimate_point_id=source.estimate_point_id,
        type_id=source.type_id,
        start_date=start_date,
        target_date=target_date,
    )
    # Preserve the original creator; there is no request context in a task.
    issue.save(created_by_id=created_by_id)

    # Copy assignees and labels from the live source (best-effort — a member or
    # label may have been removed from the project since).
    for assignee_id in source.assignees.values_list("id", flat=True):
        try:
            IssueAssignee.objects.create(
                assignee_id=assignee_id,
                issue=issue,
                project_id=project_id,
                workspace_id=workspace_id,
                created_by_id=created_by_id,
            )
        except IntegrityError:
            pass

    for label_id in source.labels.values_list("id", flat=True):
        try:
            IssueLabel.objects.create(
                label_id=label_id,
                issue=issue,
                project_id=project_id,
                workspace_id=workspace_id,
                created_by_id=created_by_id,
            )
        except IntegrityError:
            pass

    # Link the occurrence back to its recurrence so the Recurring toggle can be
    # shown and controlled from the occurrence too.
    recurrence.occurrences.add(issue)

    return issue


# Safety cap on how many missed occurrences a single run will backfill, so a
# long outage cannot flood a project with tickets in one pass.
MAX_CATCHUP_PER_RUN = 50


@shared_task
def generate_recurring_issues():
    """Create due occurrences for every active recurring work item.

    Runs daily via Celery Beat. Each series runs indefinitely until its toggle
    is turned off (``is_active=False``). Catches up on occurrences that fell due
    since the last run, bounded by ``MAX_CATCHUP_PER_RUN``.
    """
    today = timezone.now().date()

    recurrences = IssueRecurrence.objects.filter(
        is_active=True,
        next_run_at__isnull=False,
        next_run_at__lte=today,
    ).select_related("project")

    for recurrence in recurrences:
        try:
            created = 0
            while (
                recurrence.is_active
                and recurrence.next_run_at is not None
                and recurrence.next_run_at <= today
                and created < MAX_CATCHUP_PER_RUN
            ):
                anchor = recurrence.next_run_at
                issue = _create_occurrence(recurrence, anchor)

                if issue is None:
                    break

                created += 1
                if recurrence.days_of_month:
                    recurrence.next_run_at = next_month_day(anchor, recurrence.days_of_month)
                else:
                    recurrence.next_run_at = add_interval(anchor, recurrence.frequency, recurrence.interval)
                recurrence.save(update_fields=["next_run_at", "updated_at"])

                # Fire the same post-create side effects as the create view.
                issue_activity.delay(
                    type="issue.activity.created",
                    requested_data=json.dumps({"name": issue.name, "recurrence": True}),
                    actor_id=str(recurrence.created_by_id),
                    issue_id=str(issue.id),
                    project_id=str(recurrence.project_id),
                    current_instance=None,
                    epoch=int(timezone.now().timestamp()),
                    notification=True,
                )
                issue_description_version_task.delay(
                    updated_issue=json.dumps({"description_html": issue.description_html}),
                    issue_id=str(issue.id),
                    user_id=recurrence.created_by_id,
                    is_creating=True,
                )
        except Exception as e:
            log_exception(e)
            continue

    return
