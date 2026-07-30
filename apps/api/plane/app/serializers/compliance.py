# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from rest_framework import serializers

from plane.db.models import ComplianceCategory, ComplianceTemplate

from .base import BaseSerializer


class ComplianceCategorySerializer(BaseSerializer):
    class Meta:
        model = ComplianceCategory
        fields = ["id", "name", "workspace_id"]
        read_only_fields = ["workspace_id"]

    def validate_name(self, value):
        workspace_id = self.context.get("workspace_id")
        category = ComplianceCategory.objects.filter(workspace_id=workspace_id, name__iexact=value)
        if self.instance:
            category = category.exclude(id=self.instance.pk)
        if category.exists():
            raise serializers.ValidationError(detail="COMPLIANCE_CATEGORY_NAME_ALREADY_EXISTS")
        return value


class ComplianceTemplateSerializer(BaseSerializer):
    category_detail = ComplianceCategorySerializer(source="category", read_only=True)
    # Read-only: a ManyToManyField with a `through` model that carries extra
    # fields (is_active, audit columns) can't be written via DRF's default
    # `.set()`-based M2M save — Django itself forbids `.set()`/`.add()` on
    # such fields. Applicability is mutated exclusively through
    # ComplianceApplicabilityToggleEndpoint, which creates/soft-deletes the
    # through-model rows directly.
    applicable_project_ids = serializers.PrimaryKeyRelatedField(
        source="applicable_projects", many=True, read_only=True
    )

    class Meta:
        model = ComplianceTemplate
        fields = [
            "id",
            "key",
            "title",
            "category",
            "category_detail",
            "cadence",
            "due_day",
            "due_month",
            "name_template",
            "priority",
            "is_active",
            "applicable_project_ids",
            "workspace_id",
        ]
        read_only_fields = ["workspace_id"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Scope the `category` choice to the current workspace — the
        # auto-generated PrimaryKeyRelatedField would otherwise let a
        # template reference any workspace's category.
        workspace_id = self.context.get("workspace_id")
        if workspace_id:
            self.fields["category"].queryset = ComplianceCategory.objects.filter(workspace_id=workspace_id)

    def validate_key(self, value):
        workspace_id = self.context.get("workspace_id")
        template = ComplianceTemplate.objects.filter(workspace_id=workspace_id, key__iexact=value)
        if self.instance:
            template = template.exclude(id=self.instance.pk)
        if template.exists():
            raise serializers.ValidationError(detail="COMPLIANCE_TEMPLATE_KEY_ALREADY_EXISTS")
        return value

    def validate_due_day(self, value):
        if not (1 <= value <= 31):
            raise serializers.ValidationError("due_day must be between 1 and 31.")
        return value

    def validate_name_template(self, value):
        # Test-format against a dummy context so a malformed pattern (an
        # operator typo like "{tittle}") is rejected here, at edit time,
        # instead of failing the same way every time the engine runs.
        try:
            value.format(title="x", period="y", month="m", year="2026")
        except (KeyError, IndexError, ValueError) as e:
            raise serializers.ValidationError(f"Invalid name pattern: {e}")
        return value

    def validate(self, attrs):
        cadence = attrs.get("cadence", getattr(self.instance, "cadence", None))
        due_month = attrs.get("due_month", getattr(self.instance, "due_month", None))
        if cadence == "annual" and not due_month:
            raise serializers.ValidationError({"due_month": "due_month is required for annual cadence."})
        if due_month is not None and not (1 <= due_month <= 12):
            raise serializers.ValidationError({"due_month": "due_month must be between 1 and 12."})
        return attrs
