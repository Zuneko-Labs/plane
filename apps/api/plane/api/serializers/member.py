# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Third party imports
from rest_framework import serializers

# Module imports
from plane.db.models import ProjectMember, WorkspaceMember
from .base import BaseSerializer
from plane.db.models import User
from plane.utils.permissions import ROLE


class ProjectMemberSerializer(BaseSerializer):
    """
    Serializer for project members.
    """

    member = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        required=True,
    )

    def validate_member(self, value):
        slug = self.context.get("slug")
        if not slug:
            raise serializers.ValidationError("Slug is required", code="INVALID_SLUG")
        if not value:
            raise serializers.ValidationError("Member is required", code="INVALID_MEMBER")
        if not WorkspaceMember.objects.filter(workspace__slug=slug, member=value).exists():
            raise serializers.ValidationError("Member not found in workspace", code="INVALID_MEMBER")
        return value

    def validate_role(self, value):
        if value not in [ROLE.ADMIN.value, ROLE.MEMBER.value, ROLE.GUEST.value]:
            raise serializers.ValidationError("Invalid role", code="INVALID_ROLE")
        return value

    class Meta:
        model = ProjectMember
        fields = ["id", "member", "role", "project", "workspace", "is_active", "created_at", "updated_at"]
        read_only_fields = ["id", "project", "workspace", "is_active", "created_at", "updated_at"]

    def to_representation(self, instance):
        from plane.api.serializers.user import UserLiteSerializer
        from plane.api.serializers.project import ProjectLiteSerializer
        from plane.api.serializers.workspace import WorkspaceLiteSerializer
        data = super().to_representation(instance)
        data["member"] = UserLiteSerializer(instance.member).data
        data["project"] = ProjectLiteSerializer(instance.project).data
        data["workspace"] = WorkspaceLiteSerializer(instance.workspace).data
        return data
