# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from rest_framework import serializers

from plane.db.models import ProjectMember, RegistrationHandoffConfig, State, User
from plane.utils.permissions.base import ROLE

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

    def validate_eligible_agent_ids(self, users):
        # only active Members/Admins can be assigned a work item - a guest or
        # outsider named here would be emailed but never actually assigned
        project_id = self.context.get("project_id")
        if not project_id or not users:
            return users
        member_ids = {
            str(uid)
            for uid in ProjectMember.objects.filter(
                project_id=project_id,
                is_active=True,
                role__gte=ROLE.MEMBER.value,
                member_id__in=[user.id for user in users],
            ).values_list("member_id", flat=True)
        }
        invalid = [user.display_name or user.email for user in users if str(user.id) not in member_ids]
        if invalid:
            raise serializers.ValidationError(
                f"Registrars must be active members of this project: {', '.join(invalid)}."
            )
        return users
