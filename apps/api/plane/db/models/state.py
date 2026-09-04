# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.db import models
from django.template.defaultfilters import slugify
from django.db.models import Q

# Module imports
from .project import ProjectBaseModel
from plane.db.mixins import SoftDeletionManager

class StateGroup(models.TextChoices):
    BACKLOG = "backlog", "Backlog"
    UNSTARTED = "unstarted", "Unstarted"
    STARTED = "started", "Started"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"
    TRIAGE = "triage", "Triage"


# Default states — the client's own workflow for "all other projects" (see
# the department-workflow Google Sheet); the other 4 department-specific
# workflows are applied to matching existing projects via the
# apply_department_workflows management command, not here.
DEFAULT_STATES = [
    {
        "name": "Drafting",
        "color": "#60646C",
        "sequence": 15000,
        "group": StateGroup.BACKLOG.value,
        "default": True,
    },
    {
        "name": "Invoice",
        "color": "#60646C",
        "sequence": 25000,
        "group": StateGroup.UNSTARTED.value,
    },
    {
        "name": "Data Entry",
        "color": "#F59E0B",
        "sequence": 35000,
        "group": StateGroup.STARTED.value,
    },
    {
        "name": "Challan + DHC",
        "color": "#F59E0B",
        "sequence": 45000,
        "group": StateGroup.STARTED.value,
    },
    {
        "name": "Draft Approval",
        "color": "#F59E0B",
        "sequence": 55000,
        "group": StateGroup.STARTED.value,
    },
    {
        "name": "Registration",
        "color": "#F59E0B",
        "sequence": 65000,
        "group": StateGroup.STARTED.value,
    },
    {
        "name": "Xerox and Binding",
        "color": "#F59E0B",
        "sequence": 75000,
        "group": StateGroup.STARTED.value,
    },
    {
        "name": "Closed",
        "color": "#46A758",
        "sequence": 85000,
        "group": StateGroup.COMPLETED.value,
    },
    {
        "name": "Excel entry and Handover",
        "color": "#46A758",
        "sequence": 95000,
        "group": StateGroup.COMPLETED.value,
    },
    {
        # Not part of the client's visible workflow — kept because the
        # Intake/triage feature (IntakeStateEndpoint, IssueCreateSerializer's
        # allow_triage_state) hard-requires exactly one triage-group state
        # per project to exist, with no auto-create fallback.
        "name": "Triage",
        "color": "#4E5355",
        "sequence": 105000,
        "group": StateGroup.TRIAGE.value,
    },
]


class StateManager(SoftDeletionManager):
    """Default manager - excludes triage states"""

    def get_queryset(self):
        return super().get_queryset().exclude(group=StateGroup.TRIAGE.value)


class TriageStateManager(SoftDeletionManager):
    """Manager for triage states only"""

    def get_queryset(self):
        return super().get_queryset().filter(group=StateGroup.TRIAGE.value)


class State(ProjectBaseModel):
    name = models.CharField(max_length=255, verbose_name="State Name")
    description = models.TextField(verbose_name="State Description", blank=True)
    color = models.CharField(max_length=255, verbose_name="State Color")
    slug = models.SlugField(max_length=100, blank=True)
    sequence = models.FloatField(default=65535)
    group = models.CharField(
        choices=StateGroup.choices,
        default=StateGroup.BACKLOG,
        max_length=20,
    )
    is_triage = models.BooleanField(default=False)
    default = models.BooleanField(default=False)
    external_source = models.CharField(max_length=255, null=True, blank=True)
    external_id = models.CharField(max_length=255, blank=True, null=True)

    objects = StateManager()
    all_state_objects = models.Manager()
    triage_objects = TriageStateManager()

    def __str__(self):
        """Return name of the state"""
        return f"{self.name} <{self.project.name}>"

    class Meta:
        unique_together = ["name", "project", "deleted_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["name", "project"],
                condition=Q(deleted_at__isnull=True),
                name="state_unique_name_project_when_deleted_at_null",
            )
        ]
        verbose_name = "State"
        verbose_name_plural = "States"
        db_table = "states"
        ordering = ("sequence",)

    def save(self, *args, **kwargs):
        self.slug = slugify(self.name)
        if self._state.adding:
            # Get the maximum sequence value from the database
            last_id = State.objects.filter(project=self.project).aggregate(largest=models.Max("sequence"))["largest"]
            # if last_id is not None
            if last_id is not None:
                self.sequence = last_id + 15000

        return super().save(*args, **kwargs)
