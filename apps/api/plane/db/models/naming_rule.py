# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.core.exceptions import ValidationError
from django.db import models

# Module imports
from .project import ProjectBaseModel


def validate_regex_pattern(value):
    """A rule's regex_pattern must itself compile, or every save/rename
    using it would start throwing 500s instead of a clean 400."""
    import re

    try:
        re.compile(value)
    except re.error as exc:
        raise ValidationError(f"'{value}' is not a valid regular expression: {exc}")


class WorkItemNamingRule(ProjectBaseModel):
    """Validates a work item's `name` against a regex, scoped to a project
    or — when `module` is set — to one module within that project (a
    module-level rule takes precedence over the project's default rule for
    work items in that module). Stored in a table, not code, so the pattern
    can be corrected without a deploy — B3 ships with provisional patterns
    that still need confirming against the client's real live data; see
    `regex_pattern`/`example` on the seeded rows.
    """

    module = models.ForeignKey(
        "db.Module",
        on_delete=models.CASCADE,
        related_name="naming_rules",
        null=True,
        blank=True,
    )
    regex_pattern = models.CharField(max_length=500, validators=[validate_regex_pattern])
    example = models.CharField(
        max_length=255,
        help_text="A real, valid work item name shown to the user alongside the pattern in the error message.",
    )
    is_active = models.BooleanField(default=True)

    def __str__(self):
        scope = self.module.name if self.module_id else "<project default>"
        return f"{self.project.name} / {scope}: {self.regex_pattern}"

    class Meta:
        unique_together = ["project", "module", "deleted_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["project", "module"],
                condition=models.Q(deleted_at__isnull=True),
                name="naming_rule_unique_project_module_when_deleted_at_null",
            )
        ]
        verbose_name = "Work Item Naming Rule"
        verbose_name_plural = "Work Item Naming Rules"
        db_table = "work_item_naming_rules"
        ordering = ("project", "module")
