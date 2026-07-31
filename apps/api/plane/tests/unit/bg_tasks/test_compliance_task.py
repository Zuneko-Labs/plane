# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Unit tests for the compliance calendar engine and ``generate_compliance_issues``.

Covers the pure cadence math (monthly reports the previous month; quarterly
only fires in the month after a quarter closes; annual fires only in its due
month; advance_tax fires in Jun/Sep/Dec/Mar — and, on top of the month
gating, every cadence only actually fires on its exact due_day, not any other
day within an eligible month/period) and the task itself — in particular
that running it twice for the same date never creates a duplicate Issue
(the whole point of claiming the ``ComplianceRun`` row before creating
anything), that inactive templates and archived/non-applicable projects are
skipped, and that the category Label is attached.
"""

from datetime import date

import pytest

from plane.bgtasks.compliance_task import generate_compliance_issues
from plane.db.models import (
    ComplianceApplicability,
    ComplianceCategory,
    ComplianceRun,
    ComplianceTemplate,
    Issue,
    Label,
    State,
)
from plane.db.models.state import StateGroup
from plane.tests.factories import ProjectFactory
from plane.utils.compliance_calendar import generate_due_task


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
# Pure cadence math (no DB)
# --------------------------------------------------------------------------- #
class _Template:
    """Lightweight stand-in for a ComplianceTemplate — generate_due_task only
    reads these attributes, so a real model instance isn't needed."""

    def __init__(self, cadence, due_day=20, due_month=None, name_template="{title} - {period}", title="GSTR-3B"):
        self.cadence = cadence
        self.due_day = due_day
        self.due_month = due_month
        self.name_template = name_template
        self.title = title


@pytest.mark.unit
class TestGenerateDueTask:
    def test_monthly_fires_exactly_on_due_day(self):
        template = _Template("monthly", due_day=20)
        assert generate_due_task(template, date(2026, 8, 15)) is None
        assert generate_due_task(template, date(2026, 8, 21)) is None
        gen = generate_due_task(template, date(2026, 8, 20))
        assert gen.period_label == "July 2026"
        assert gen.due_date == date(2026, 8, 20)
        assert gen.title == "GSTR-3B - July 2026"

    def test_monthly_due_day_clamps_to_month_end(self):
        template = _Template("monthly", due_day=31)
        assert generate_due_task(template, date(2026, 2, 10)) is None
        gen = generate_due_task(template, date(2026, 2, 28))
        assert gen.due_date == date(2026, 2, 28)

    def test_quarterly_only_fires_on_due_day_in_closing_months(self):
        template = _Template("quarterly", due_day=31)
        assert generate_due_task(template, date(2026, 5, 31)) is None  # wrong month
        assert generate_due_task(template, date(2026, 7, 5)) is None  # right month, wrong day
        gen = generate_due_task(template, date(2026, 7, 31))
        assert gen.period_label == "Q1 2026"
        assert gen.due_date == date(2026, 7, 31)

    def test_annual_only_fires_on_due_day_in_due_month(self):
        template = _Template("annual", due_day=30, due_month=10)
        assert generate_due_task(template, date(2026, 9, 30)) is None  # wrong month
        assert generate_due_task(template, date(2026, 10, 1)) is None  # right month, wrong day
        gen = generate_due_task(template, date(2026, 10, 30))
        assert gen.period_label == "FY 2025-26"
        assert gen.due_date == date(2026, 10, 30)

    def test_advance_tax_only_fires_on_due_day_in_scheduled_months(self):
        template = _Template("advance_tax", due_day=15)
        assert generate_due_task(template, date(2026, 7, 15)) is None  # wrong month
        assert generate_due_task(template, date(2026, 6, 1)) is None  # right month, wrong day
        gen = generate_due_task(template, date(2026, 6, 15))
        assert gen.period_label == "June 2026"
        assert gen.due_date == date(2026, 6, 15)

    def test_malformed_name_template_falls_back(self):
        gen = generate_due_task(_Template("monthly", name_template="{tittle} - {period}"), date(2026, 8, 20))
        assert gen.title == "GSTR-3B - July 2026"


# --------------------------------------------------------------------------- #
# Task: generate_compliance_issues
# --------------------------------------------------------------------------- #
def _make_template(project, *, cadence="monthly", due_day=20, due_month=None, category_name="GST", is_active=True):
    category, _ = ComplianceCategory.objects.get_or_create(
        workspace_id=project.workspace_id, name=category_name, defaults={"created_by_id": project.created_by_id}
    )
    template = ComplianceTemplate.objects.create(
        workspace_id=project.workspace_id,
        key=f"{category_name.lower()}-{cadence}",
        title=f"{category_name} Return",
        category=category,
        cadence=cadence,
        due_day=due_day,
        due_month=due_month,
        is_active=is_active,
        created_by_id=project.created_by_id,
    )
    ComplianceApplicability.objects.create(
        project=project,
        template=template,
        workspace_id=project.workspace_id,
        created_by_id=project.created_by_id,
    )
    return template


@pytest.mark.unit
@pytest.mark.django_db
class TestGenerateComplianceIssues:
    @pytest.fixture(autouse=True)
    def _stub_side_effects(self, mocker):
        mocker.patch("plane.bgtasks.compliance_task.issue_activity.delay")

    def test_creates_issue_for_active_applicable_template(self):
        project = ProjectFactory()
        todo_state = _make_todo_state(project)
        template = _make_template(project)

        summary = generate_compliance_issues(as_of=date(2026, 8, 20))

        assert summary["created"] == 1
        issue = Issue.objects.get(project=project)
        assert issue.name == "GST Return - July 2026"
        # The due date is assigned as start_date (task is only ever created
        # exactly on its due date), not target_date.
        assert issue.start_date == date(2026, 8, 20)
        assert issue.target_date is None
        # Lands in the project's default (Todo) state, not a dedicated
        # "Compliance" state — the client asked for generated items to
        # behave like any other work item.
        assert issue.state_id == todo_state.id
        assert Label.objects.filter(project=project, name__iexact="GST").exists()
        assert issue.labels.filter(name__iexact="GST").exists()
        assert ComplianceRun.objects.filter(project=project, template=template, period_label="July 2026").exists()

    def test_running_twice_does_not_duplicate(self):
        """The whole point of claiming ComplianceRun before creating the Issue:
        two runs for the same as_of must only ever create one Issue."""
        project = ProjectFactory()
        _make_template(project)

        generate_compliance_issues(as_of=date(2026, 8, 20))
        generate_compliance_issues(as_of=date(2026, 8, 20))

        assert Issue.objects.filter(project=project).count() == 1
        assert ComplianceRun.objects.filter(project=project).count() == 1

    def test_inactive_template_is_skipped(self):
        project = ProjectFactory()
        _make_template(project, is_active=False)

        generate_compliance_issues(as_of=date(2026, 8, 20))

        assert Issue.objects.filter(project=project).count() == 0

    def test_non_applicable_project_is_not_generated_for(self):
        # Same workspace for both (a second independent WorkspaceFactory
        # would trip a UserFactory quirk: blank `username` collides across
        # unrelated users, unrelated to what this test is actually checking).
        # ProjectFactory doesn't randomize `identifier`, so two projects in
        # one workspace need explicit distinct identifiers or they collide
        # on Project's (identifier, workspace) unique constraint.
        project = ProjectFactory(name="Applicable Project", identifier="APP")
        other_project = ProjectFactory(name="Other Project", identifier="OTH", workspace=project.workspace)
        _make_template(project)

        generate_compliance_issues(as_of=date(2026, 8, 20))

        assert Issue.objects.filter(project=other_project).count() == 0

    def test_archived_project_is_excluded(self):
        from django.utils import timezone

        project = ProjectFactory()
        _make_template(project)
        project.archived_at = timezone.now()
        project.save(update_fields=["archived_at"])

        generate_compliance_issues(as_of=date(2026, 8, 20))

        assert Issue.objects.filter(project=project).count() == 0

    def test_quarterly_template_does_not_fire_outside_closing_month(self):
        project = ProjectFactory()
        _make_template(project, cadence="quarterly", due_day=31)

        generate_compliance_issues(as_of=date(2026, 5, 1))

        assert Issue.objects.filter(project=project).count() == 0
