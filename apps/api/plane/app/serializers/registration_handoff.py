# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from rest_framework import serializers

from plane.db.models import RegistrationHandoffConfig, State, User

from .base import BaseSerializer


class RegistrationHandoffConfigSerializer(BaseSerializer):
    trigger_state_id = serializers.PrimaryKeyRelatedField(source="trigger_state", queryset=State.objects.all())
    eligible_agent_ids = serializers.PrimaryKeyRelatedField(
        source="eligible_agents", queryset=User.objects.all(), many=True, required=False
    )

    class Meta:
        model = RegistrationHandoffConfig
        fields = ["id", "project", "trigger_state_id", "eligible_agent_ids", "created_at", "updated_at"]
        read_only_fields = ["id", "project", "created_at", "updated_at"]

    def validate_trigger_state_id(self, state):
        project_id = self.context.get("project_id")
        if project_id and str(state.project_id) != str(project_id):
            raise serializers.ValidationError("Trigger state must belong to this project.")
        return state
