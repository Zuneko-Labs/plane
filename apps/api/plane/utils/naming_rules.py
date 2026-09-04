# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
B3: work item names must match a project- or module-specific naming
convention (the work item name is the folder name on the client's PC, so it
has to follow their filesystem naming convention exactly). Rules are stored
in `WorkItemNamingRule`, not code, so a wrong pattern can be corrected
without a deploy.

NOTE: the rules seeded via migration/admin at ship time are provisional —
derived only from the two examples in the ticket (CODE-NUMBER, and
CODE-Name-NUMBER for the shared B2C module). They still need confirming
against the client's actual live work item names before this is relied on
for real enforcement; see `plane.db.models.naming_rule.WorkItemNamingRule`.
"""

import re

from plane.db.models import WorkItemNamingRule


def get_naming_rule(project_id, module_id=None):
    """A module-level rule (if one exists for this project+module) wins over
    the project's default (module=None) rule. Returns None if neither is
    configured, meaning no naming constraint applies yet for this project."""
    if module_id:
        rule = WorkItemNamingRule.objects.filter(
            project_id=project_id, module_id=module_id, is_active=True
        ).first()
        if rule is not None:
            return rule

    return WorkItemNamingRule.objects.filter(
        project_id=project_id, module_id__isnull=True, is_active=True
    ).first()


def validate_work_item_name(project_id, module_id, name):
    """Returns an error message string if `name` violates the applicable
    naming rule, else None. Callers should 400 on a non-None return."""
    rule = get_naming_rule(project_id, module_id)
    if rule is None:
        return None

    if not name or not re.match(rule.regex_pattern, name):
        return f'Work item name must match the pattern "{rule.regex_pattern}" (example: "{rule.example}")'

    return None
