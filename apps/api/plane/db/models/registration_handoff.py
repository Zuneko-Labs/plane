# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.conf import settings
from django.db import models

# Module imports
from .project import ProjectBaseModel


class RegistrationHandoffConfig(ProjectBaseModel):
    """A work item moving into `trigger_state` requires naming an eligible
    registration agent (see plane.utils.registration_handoff) — a physical
    person has to go to the sub-registrar's office, and it's usually not
    whoever changed the state.

    `trigger_state` is an FK, not a name string, specifically so the trigger
    stage can be renamed (workstream E) without breaking this rule.
    """

    trigger_state = models.OneToOneField(
        "db.State",
        on_delete=models.CASCADE,
        related_name="registration_handoff_config",
    )
    eligible_agents = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="+", blank=True)

    def __str__(self):
        return f"{self.project.name} -> {self.trigger_state.name}"

    class Meta:
        verbose_name = "Registration Handoff Config"
        verbose_name_plural = "Registration Handoff Configs"
        db_table = "registration_handoff_configs"
        ordering = ("project",)


class RegistrationHandoffRecord(ProjectBaseModel):
    """Written the first time a work item enters the configured registration
    state with a named agent.

    Its existence is what makes the handoff a once-only prompt: the gate in
    plane.utils.registration_handoff asks for an agent only when no record
    exists yet, so a work item that leaves the registration state and later
    comes back keeps the agent it was already given instead of re-prompting.
    """

    issue = models.OneToOneField(
        "db.Issue",
        on_delete=models.CASCADE,
        related_name="registration_handoff_record",
    )
    agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="+",
    )

    def __str__(self):
        return f"{self.issue_id} -> {self.agent_id}"

    class Meta:
        verbose_name = "Registration Handoff Record"
        verbose_name_plural = "Registration Handoff Records"
        db_table = "registration_handoff_records"
        ordering = ("-created_at",)
