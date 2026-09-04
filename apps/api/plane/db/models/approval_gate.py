# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.conf import settings
from django.db import models

# Module imports
from .project import ProjectBaseModel


class ApprovalGateConfig(ProjectBaseModel):
    """Names the three states of the handover sign-off flow for a project.
    FK-keyed, not name-string-matched, since State names are per-project
    free text and can be renamed without breaking this rule (see
    RegistrationHandoffConfig for the same reasoning).

    Only a project Admin (see plane.utils.approval.is_project_approver) may
    move a work item into `approved_state` or `sent_back_state`.
    `pending_approval_state` stays open to anyone entering it, but triggers
    an approver notification.
    """

    pending_approval_state = models.OneToOneField(
        "db.State",
        on_delete=models.CASCADE,
        related_name="+",
    )
    approved_state = models.OneToOneField(
        "db.State",
        on_delete=models.CASCADE,
        related_name="+",
    )
    sent_back_state = models.OneToOneField(
        "db.State",
        on_delete=models.CASCADE,
        related_name="+",
    )

    def __str__(self):
        return f"{self.project.name} -> {self.approved_state.name}/{self.sent_back_state.name}"

    class Meta:
        verbose_name = "Approval Gate Config"
        verbose_name_plural = "Approval Gate Configs"
        db_table = "approval_gate_configs"
        ordering = ("project",)


class ApprovalRecord(ProjectBaseModel):
    """Sign-off register entry, written alongside the existing IssueActivity
    audit trail whenever a work item is Approved or Sent Back — kept
    separate from activity so it can be queried/exported without parsing
    generic activity rows.
    """

    class Decision(models.TextChoices):
        APPROVED = "approved", "Approved"
        SENT_BACK = "sent_back", "Sent Back"

    issue = models.ForeignKey(
        "db.Issue",
        on_delete=models.CASCADE,
        related_name="approval_records",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="+",
    )
    decision = models.CharField(max_length=20, choices=Decision.choices)
    comment = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.issue_id} {self.decision} by {self.actor_id}"

    class Meta:
        verbose_name = "Approval Record"
        verbose_name_plural = "Approval Records"
        db_table = "approval_records"
        ordering = ("-created_at",)
