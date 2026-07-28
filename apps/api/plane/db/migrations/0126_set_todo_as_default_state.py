# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.db import migrations


def set_todo_as_default_state(apps, schema_editor):
    State = apps.get_model("db", "State")
    db_alias = schema_editor.connection.alias

    # Unset default on any Backlog-group states
    State.objects.using(db_alias).filter(group="backlog", default=True).update(default=False)

    # For each project with an unstarted (Todo) state, mark its first one as default
    project_ids = (
        State.objects.using(db_alias).filter(group="unstarted").values_list("project_id", flat=True).distinct()
    )
    for project_id in project_ids.iterator():
        todo_state = (
            State.objects.using(db_alias)
            .filter(project_id=project_id, group="unstarted")
            .order_by("sequence")
            .first()
        )
        if todo_state and not todo_state.default:
            todo_state.default = True
            todo_state.save(update_fields=["default"])


def reverse_set_todo_as_default_state(apps, schema_editor):
    State = apps.get_model("db", "State")
    db_alias = schema_editor.connection.alias

    State.objects.using(db_alias).filter(group="unstarted", default=True).update(default=False)

    project_ids = (
        State.objects.using(db_alias).filter(group="backlog").values_list("project_id", flat=True).distinct()
    )
    for project_id in project_ids.iterator():
        backlog_state = (
            State.objects.using(db_alias)
            .filter(project_id=project_id, group="backlog")
            .order_by("sequence")
            .first()
        )
        if backlog_state:
            backlog_state.default = True
            backlog_state.save(update_fields=["default"])


class Migration(migrations.Migration):
    dependencies = [("db", "0125_issuerecurrence_occurrences")]

    operations = [migrations.RunPython(set_todo_as_default_state, reverse_set_todo_as_default_state)]
