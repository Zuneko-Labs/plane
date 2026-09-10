# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from rest_framework import serializers

from plane.db.models import ApprovalGateConfig, ApprovalRecord, RegistrationHandoffConfig, State

from .base import BaseSerializer


class ApprovalGateConfigSerializer(BaseSerializer):
    pending_approval_state_id = serializers.PrimaryKeyRelatedField(
        source="pending_approval_state", queryset=State.objects.all(), required=False, allow_null=True
    )
    approved_state_id = serializers.PrimaryKeyRelatedField(
        source="approved_state", queryset=State.objects.all(), required=False, allow_null=True
    )
    sent_back_state_id = serializers.PrimaryKeyRelatedField(
        source="sent_back_state", queryset=State.objects.all(), required=False, allow_null=True
    )

    class Meta:
        model = ApprovalGateConfig
        fields = [
            "id",
            "project",
            "is_enabled",
            "pending_approval_state_id",
            "approved_state_id",
            "sent_back_state_id",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "project", "created_at", "updated_at"]

    def _validate_state_in_project(self, state):
        project_id = self.context.get("project_id")
        if project_id and str(state.project_id) != str(project_id):
            raise serializers.ValidationError("State must belong to this project.")
        return state

    def validate_pending_approval_state_id(self, state):
        return self._validate_state_in_project(state)

    def validate_approved_state_id(self, state):
        return self._validate_state_in_project(state)

    def validate_sent_back_state_id(self, state):
        return self._validate_state_in_project(state)

    def validate(self, attrs):
        pending = attrs.get("pending_approval_state") or getattr(self.instance, "pending_approval_state", None)
        approved = attrs.get("approved_state") or getattr(self.instance, "approved_state", None)
        sent_back = attrs.get("sent_back_state") or getattr(self.instance, "sent_back_state", None)

        roles = {"Pending Approval": pending, "Approved": approved, "Sent Back": sent_back}
        seen = {}
        for role_name, state in roles.items():
            if state is None:
                continue
            if state.id in seen:
                raise serializers.ValidationError(
                    f'"{state.name}" is already used as {seen[state.id]} — each role needs its own state.'
                )
            seen[state.id] = role_name

        project_id = self.context.get("project_id")
        if project_id:
            handoff_trigger_id = (
                RegistrationHandoffConfig.objects.filter(project_id=project_id)
                .values_list("trigger_state_id", flat=True)
                .first()
            )
            if handoff_trigger_id and handoff_trigger_id in seen:
                raise serializers.ValidationError(
                    f'That state is already the registration hand-off trigger state — entering it already requires '
                    f"naming an agent. Pick a different state for {seen[handoff_trigger_id]}."
                )

        is_enabled = attrs.get("is_enabled", getattr(self.instance, "is_enabled", True))
        if is_enabled and approved is None and sent_back is None:
            raise serializers.ValidationError(
                "Turn the gate off, or pick at least an Approved or a Sent Back state for it to gate."
            )

        return attrs


class ApprovalRecordSerializer(BaseSerializer):
    """Read-only sign-off register entry — the exportable record of who
    approved or sent back a work item, and why. Written server-side only
    (see plane.utils.approval), never created directly through this API.
    """

    issue_name = serializers.CharField(source="issue.name", read_only=True)
    issue_sequence_id = serializers.IntegerField(source="issue.sequence_id", read_only=True)
    actor_email = serializers.CharField(source="actor.email", read_only=True)

    class Meta:
        model = ApprovalRecord
        fields = [
            "id",
            "project",
            "issue",
            "issue_name",
            "issue_sequence_id",
            "actor",
            "actor_email",
            "decision",
            "comment",
            "created_at",
        ]
        read_only_fields = fields
