# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Unit tests for the recurring work-item scheduler.

Covers the pure date helpers (interval stepping, semi-monthly day derivation,
month-length clamping) and the ``generate_recurring_issues`` task — in
particular that EVERY active, due recurrence is recreated (not just one), that
inactive/future ones are skipped, that occurrences are linked back to their
recurrence, and that they land in the project's default (Todo) state.
"""

from datetime import date, timedelta

import pytest
from freezegun import freeze_time
from django.utils import timezone

from plane.bgtasks.recurring_issue_task import generate_recurring_issues
from plane.db.models import Issue, IssueRecurrence, State
from plane.db.models.state import StateGroup
from plane.tests.factories import ProjectFactory
from plane.utils.recurrence import add_interval, derive_days_of_month, next_month_day


def _make_todo_state(project):
    """Create the project's default (Todo) state, mirroring what a project
    creation flow normally seeds — bare ProjectFactory projects have none."""
    return State.objects.create(
        project=project,
        workspace_id=project.workspace_id,
        name="Todo",
        color="#565EAD",
        group=StateGroup.UNSTARTED.value,
        default=True,
        created_by_id=project.created_by_id,
    )


# --------------------------------------------------------------------------- #
# Pure date helpers (no DB)
# --------------------------------------------------------------------------- #
@pytest.mark.unit
class TestRecurrenceHelpers:
    def test_add_interval_daily_weekly_monthly(self):
        assert add_interval(date(2026, 1, 15), "daily", 1) == date(2026, 1, 16)
        assert add_interval(date(2026, 1, 15), "weekly", 2) == date(2026, 1, 29)
        assert add_interval(date(2026, 1, 15), "monthly", 1) == date(2026, 2, 15)

    def test_add_interval_monthly_clamps_month_end(self):
        # Jan 31 + 1 month -> Feb 28 (2026 is not a leap year)
        assert add_interval(date(2026, 1, 31), "monthly", 1) == date(2026, 2, 28)

    def test_derive_days_of_month(self):
        assert derive_days_of_month(23, 2) == [8, 23]
        assert derive_days_of_month(1, 2) == [1, 16]
        assert derive_days_of_month(15, 1) == [15]

    def test_next_month_day_walks_the_series(self):
        # twice-monthly on the 8th & 23rd, starting Jul 23
        assert next_month_day(date(2026, 7, 23), [8, 23]) == date(2026, 8, 8)
        assert next_month_day(date(2026, 8, 8), [8, 23]) == date(2026, 8, 23)
        assert next_month_day(date(2026, 8, 23), [8, 23]) == date(2026, 9, 8)

    def test_next_month_day_clamps_february(self):
        # a target day of 31 clamps to the last day of February
        assert next_month_day(date(2026, 1, 31), [31]) == date(2026, 2, 28)


# --------------------------------------------------------------------------- #
# Scheduler: generate_recurring_issues
# --------------------------------------------------------------------------- #
def _make_recurrence(project, name, *, frequency="monthly", is_active=True, next_run_at="today", days=None):
    """Create a source issue + an IssueRecurrence for it."""
    run_at = timezone.now().date() if next_run_at == "today" else next_run_at
    issue = Issue.objects.create(project=project, name=name)
    return IssueRecurrence.objects.create(
        source_issue=issue,
        project=project,
        workspace_id=project.workspace_id,
        frequency=frequency,
        start_date=timezone.now().date(),
        days_of_month=days or [],
        next_run_at=run_at,
        is_active=is_active,
    )


@pytest.mark.unit
@pytest.mark.django_db
class TestGenerateRecurringIssues:
    @pytest.fixture(autouse=True)
    def _stub_side_effects(self, mocker):
        # The task fires Celery .delay() side effects; stub them so the test
        # needs no broker.
        mocker.patch("plane.bgtasks.recurring_issue_task.issue_activity.delay")
        mocker.patch("plane.bgtasks.recurring_issue_task.issue_description_version_task.delay")

    def test_all_active_due_recurrences_recreate(self):
        """The key case: every active, due recurrence generates one occurrence
        — not just the first."""
        project = ProjectFactory()

        r1 = _make_recurrence(project, "weekly standup", frequency="weekly")
        r2 = _make_recurrence(project, "monthly report", frequency="monthly")
        r3 = _make_recurrence(project, "daily check", frequency="daily")
        paused = _make_recurrence(project, "paused", is_active=False)

        before = Issue.objects.filter(project=project).count()
        generate_recurring_issues()
        after = Issue.objects.filter(project=project).count()

        # one new occurrence per active due recurrence (3), paused one skipped
        assert after - before == 3
        assert r1.occurrences.count() == 1
        assert r2.occurrences.count() == 1
        assert r3.occurrences.count() == 1
        assert paused.occurrences.count() == 0

    def test_occurrence_lands_in_default_todo_state(self):
        project = ProjectFactory()
        todo_state = _make_todo_state(project)
        r = _make_recurrence(project, "task")

        generate_recurring_issues()

        occ = r.occurrences.first()
        assert occ is not None
        assert occ.state_id == todo_state.id

    def test_occurrence_is_linked_to_recurrence(self):
        project = ProjectFactory()
        r = _make_recurrence(project, "linked")

        generate_recurring_issues()

        occ = r.occurrences.first()
        # link is queryable from the occurrence side (drives the toggle lookup)
        assert IssueRecurrence.objects.filter(occurrences__id=occ.id).first() == r

    def test_future_recurrence_is_not_due(self):
        project = ProjectFactory()
        future = timezone.now().date() + timedelta(days=10)
        r = _make_recurrence(project, "later", next_run_at=future)

        generate_recurring_issues()

        assert r.occurrences.count() == 0

    def test_inactive_recurrence_not_recreated_even_if_due(self):
        project = ProjectFactory()
        r = _make_recurrence(project, "off", is_active=False, next_run_at=timezone.now().date())

        generate_recurring_issues()

        assert r.occurrences.count() == 0

    def test_next_run_advances_after_generation(self):
        project = ProjectFactory()
        today = timezone.now().date()
        r = _make_recurrence(project, "monthly", frequency="monthly", next_run_at=today)

        generate_recurring_issues()
        r.refresh_from_db()

        # monthly steps one month forward and remains active (indefinite series)
        assert r.next_run_at == add_interval(today, "monthly", 1)
        assert r.is_active is True

    @freeze_time("2026-08-31")
    def test_semi_monthly_generates_on_two_days(self):
        project = ProjectFactory()
        # twice-monthly on the 8th & 23rd, first due on the 8th. With "today"
        # frozen to Aug 31, both Aug days are due, so the catch-up loop creates
        # two occurrences in one run.
        r = _make_recurrence(
            project, "twice monthly", frequency="monthly", days=[8, 23], next_run_at=date(2026, 8, 8)
        )

        generate_recurring_issues()

        assert r.occurrences.count() == 2
        r.refresh_from_db()
        assert r.next_run_at == date(2026, 9, 8)
