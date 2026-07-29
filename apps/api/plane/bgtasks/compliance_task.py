# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import json

# Third party imports
from celery import shared_task

# Django imports
from django.db import IntegrityError, transaction
from django.utils import timezone

# Module imports
from plane.bgtasks.issue_activities_task import issue_activity
from plane.db.models import ComplianceRun, ComplianceTemplate, Issue, IssueLabel, Label
from plane.utils.compliance_calendar import generate_due_task
from plane.utils.exception_logger import log_exception


def _get_or_create_compliance_label(project, category_name, created_by_id):
    """Get-or-create the project Label matching a compliance category.

    `Label` has a per-project conditional unique constraint, so a concurrent
    create loses the race with an `IntegrityError` rather than a duplicate
    row — filter first, and on that error re-fetch instead of raising.
    """
    label = Label.objects.filter(project=project, name__iexact=category_name).first()
    if label:
        return label
    try:
        with transaction.atomic():
            label = Label(project=project, name=category_name, color="#F59E0B")
            label.save(created_by_id=created_by_id)
        return label
    except IntegrityError:
        return Label.objects.filter(project=project, name__iexact=category_name).first()


def _create_compliance_issue(template, project, generated, created_by_id):
    """Create the work item for one due (template, project) pair.

    Returns the created Issue. State is left unset — `Issue.save()` already
    auto-assigns the project's default state (Todo) whenever `state` is
    None (see `Issue._ensure_default_state`), so generated items land in
    Todo like any other work item, matching what the client asked for
    instead of a dedicated "Compliance" state. Label attachment is
    best-effort — a failure here must not roll back the Issue itself,
    matching how `_create_occurrence` treats assignee/label copying as
    best-effort.
    """
    issue = Issue(
        project_id=project.id,
        name=generated.title,
        priority=template.priority,
        target_date=generated.target_date,
    )
    issue.save(created_by_id=created_by_id)

    label = _get_or_create_compliance_label(project, template.category.name, created_by_id)
    if label:
        try:
            IssueLabel.objects.create(
                label_id=label.id,
                issue=issue,
                project_id=project.id,
                workspace_id=project.workspace_id,
                created_by_id=created_by_id,
            )
        except IntegrityError:
            pass

    return issue


@shared_task
def generate_compliance_issues(as_of=None, workspace_slug=None):
    """Create due work items for every active compliance template, across
    every project it's marked applicable to.

    Runs daily via Celery Beat, and synchronously from the "Generate now"
    admin endpoint (hence the plain return value instead of `.delay()`
    semantics). Idempotent: claims a `ComplianceRun` row for
    (project, template, period_label) *before* creating anything, so two
    concurrent runs (a beat tick racing a manual trigger) can't both create
    an Issue for the same period.
    """
    as_of = as_of or timezone.now().date()

    created, skipped, failed = [], [], []

    templates = ComplianceTemplate.objects.filter(is_active=True).select_related("category").prefetch_related(
        "applicable_projects"
    )
    if workspace_slug:
        # The daily Celery Beat run covers every workspace; the "Generate
        # now" admin endpoint must only fan out within the calling
        # workspace, not every other workspace's templates too.
        templates = templates.filter(workspace__slug=workspace_slug)

    for template in templates:
        generated = generate_due_task(template, as_of)
        if generated is None:
            continue

        for project in template.applicable_projects.filter(archived_at__isnull=True):
            try:
                try:
                    with transaction.atomic():
                        run = ComplianceRun.objects.create(
                            project=project,
                            template=template,
                            period_label=generated.period_label,
                            target_date=generated.target_date,
                            issue=None,
                        )
                except IntegrityError:
                    # Another worker already claimed this (project, template,
                    # period) — confined to its own savepoint, so this loop
                    # can keep going even inside an outer transaction.
                    skipped.append({"project": project.name, "title": generated.title})
                    continue

                issue = _create_compliance_issue(template, project, generated, template.created_by_id)
                run.issue = issue
                run.save(update_fields=["issue", "updated_at"])

                issue_activity.delay(
                    type="issue.activity.created",
                    requested_data=json.dumps({"name": issue.name, "compliance": True}),
                    actor_id=str(template.created_by_id),
                    issue_id=str(issue.id),
                    project_id=str(project.id),
                    current_instance=None,
                    epoch=int(timezone.now().timestamp()),
                    notification=True,
                )

                created.append({"project": project.name, "title": generated.title, "issue_id": str(issue.id)})
            except Exception as e:
                log_exception(e)
                failed.append({"project": project.name, "title": generated.title, "reason": str(e)})
                continue

    return {
        "as_of": as_of.isoformat(),
        "created": len(created),
        "skipped": len(skipped),
        "failed": len(failed),
        "created_items": created,
        "failed_items": failed,
    }
