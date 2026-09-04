# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from rest_framework import serializers

from plane.db.models import WorkItemNamingRule

from .base import BaseSerializer


class WorkItemNamingRuleSerializer(BaseSerializer):
    class Meta:
        model = WorkItemNamingRule
        fields = ["id", "project", "module", "regex_pattern", "example", "is_active", "created_at", "updated_at"]
        read_only_fields = ["id", "project", "created_at", "updated_at"]

    def validate(self, attrs):
        # Every rule needs a real example that actually satisfies its own
        # pattern - otherwise the error message we show users ("example:
        # ...") could itself be invalid, and no one would notice until a
        # confused support ticket showed up.
        import re

        pattern = attrs.get("regex_pattern", getattr(self.instance, "regex_pattern", None))
        example = attrs.get("example", getattr(self.instance, "example", None))
        if pattern and example and not re.match(pattern, example):
            raise serializers.ValidationError(
                {"example": f"Example \"{example}\" does not itself match pattern \"{pattern}\""}
            )
        return attrs
