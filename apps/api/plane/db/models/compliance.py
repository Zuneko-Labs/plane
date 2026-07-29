# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.db import models
from django.db.models import Q

from .issue import Issue
from .workspace import WorkspaceBaseModel


class ComplianceCategory(WorkspaceBaseModel):
    """A grouping label for compliance templates (e.g. GST, TDS, ROC).

    Kept as a lookup table (rather than free text on the template) so the
    Applicability grid's column groups can't fragment from casing/typo
    variants of the same category.
    """

    name = models.CharField(max_length=255)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "name"],
                condition=Q(deleted_at__isnull=True),
                name="unique_workspace_category_name_when_not_deleted",
            ),
        ]
        verbose_name = "Compliance Category"
        verbose_name_plural = "Compliance Categories"
        db_table = "compliance_categories"
        ordering = ("name",)

    def __str__(self):
        return str(self.name)


class ComplianceTemplate(WorkspaceBaseModel):
    """A recurring statutory task definition.

    ``generate_compliance_issues`` (``plane.bgtasks.compliance_task``) walks
    every active template and, for each project it's marked applicable to
    (via ``ComplianceApplicability``), creates a work item titled from
    ``name_template`` once the template's cadence falls due for that date.
    """

    CADENCE_CHOICES = (
        ("monthly", "Monthly"),
        ("quarterly", "Quarterly"),
        ("annual", "Annual"),
        ("advance_tax", "Advance Tax"),
    )

    key = models.SlugField(max_length=100)
    title = models.CharField(max_length=255)
    category = models.ForeignKey(
        "db.ComplianceCategory",
        on_delete=models.PROTECT,
        related_name="templates",
    )
    cadence = models.CharField(max_length=30, choices=CADENCE_CHOICES)
    # Day of month the task is due. For "annual" cadence this pairs with
    # due_month; for other cadences the due date always falls in the month
    # the task is generated.
    due_day = models.PositiveSmallIntegerField()
    due_month = models.PositiveSmallIntegerField(null=True, blank=True)
    # Placeholders: {title} {period} {month} {year}. Validated at the
    # serializer layer so a malformed pattern is rejected at edit time
    # instead of failing silently every time the engine runs.
    name_template = models.CharField(max_length=255, default="{title} - {period}")
    priority = models.CharField(
        max_length=30,
        choices=Issue.PRIORITY_CHOICES,
        default="medium",
    )
    is_active = models.BooleanField(default=True)
    applicable_projects = models.ManyToManyField(
        "db.Project",
        through="db.ComplianceApplicability",
        related_name="compliance_templates",
        blank=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "key"],
                condition=Q(deleted_at__isnull=True),
                name="unique_workspace_template_key_when_not_deleted",
            ),
        ]
        verbose_name = "Compliance Template"
        verbose_name_plural = "Compliance Templates"
        db_table = "compliance_templates"
        ordering = ("category__name", "title")

    def __str__(self):
        return str(self.title)


class ComplianceApplicability(WorkspaceBaseModel):
    """Through-model backing ``ComplianceTemplate.applicable_projects``.

    An explicit model (not a bare M2M) so toggling a cell in the
    Applicability grid carries the usual audit trail (created_by,
    soft-delete) that every other cross-entity join in this codebase has.
    """

    project = models.ForeignKey(
        "db.Project",
        on_delete=models.CASCADE,
        related_name="project_complianceapplicability",
    )
    template = models.ForeignKey(
        "db.ComplianceTemplate",
        on_delete=models.CASCADE,
        related_name="applicabilities",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["project", "template"],
                condition=Q(deleted_at__isnull=True),
                name="unique_project_template_when_not_deleted",
            ),
        ]
        verbose_name = "Compliance Applicability"
        verbose_name_plural = "Compliance Applicabilities"
        db_table = "compliance_applicabilities"
        ordering = ("-created_at",)


class ComplianceRun(WorkspaceBaseModel):
    """Idempotency + generation record for one (project, template, period).

    ``project`` overrides the inherited ``WorkspaceBaseModel.project`` field
    as required (the generic base declares it nullable since most
    workspace-scoped models don't need a project at all).
    """

    project = models.ForeignKey(
        "db.Project",
        on_delete=models.CASCADE,
        related_name="project_compliancerun",
    )
    template = models.ForeignKey(
        "db.ComplianceTemplate",
        on_delete=models.CASCADE,
        related_name="runs",
    )
    period_label = models.CharField(max_length=100)
    target_date = models.DateField()
    issue = models.ForeignKey(
        "db.Issue",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="compliance_run",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["project", "template", "period_label"],
                condition=Q(deleted_at__isnull=True),
                name="unique_project_template_period_when_not_deleted",
            ),
        ]
        verbose_name = "Compliance Run"
        verbose_name_plural = "Compliance Runs"
        db_table = "compliance_runs"
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.template.title} - {self.period_label} <{self.project.name}>"
