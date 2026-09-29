import django.db.models.deletion
from django.db import migrations, models

# Mirrors plane.db.models.state.DEFAULT_STATES' registration stage name —
# duplicated (not imported) because data migrations must not depend on
# application code that can change out from under them.
_REGISTRATION_STATE_NAMES = ["registration"]


def backfill_registration_handoff_configs(apps, schema_editor):
    """Projects created before RegistrationHandoffConfig existed never got
    one, so moving their work items into "Registration" silently skipped the
    registrar step. Give every such project the same config a new project
    gets: triggered by its "Registration" state, open to any member."""
    Project = apps.get_model("db", "Project")
    State = apps.get_model("db", "State")
    RegistrationHandoffConfig = apps.get_model("db", "RegistrationHandoffConfig")

    configured_project_ids = set(
        RegistrationHandoffConfig.objects.filter(deleted_at__isnull=True).values_list("project_id", flat=True)
    )
    taken_state_ids = set(RegistrationHandoffConfig.objects.values_list("trigger_state_id", flat=True))

    for project in Project.objects.exclude(id__in=configured_project_ids).iterator():
        state = next(
            (
                state
                for state in State.objects.filter(project_id=project.id, deleted_at__isnull=True)
                .exclude(id__in=taken_state_ids)
                .order_by("sequence")
                .only("id", "name")
                if state.name.strip().lower() in _REGISTRATION_STATE_NAMES
            ),
            None,
        )
        if state is None:
            continue
        RegistrationHandoffConfig.objects.create(
            project_id=project.id,
            workspace_id=project.workspace_id,
            trigger_state_id=state.id,
        )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("db", "0134_backfill_approval_gate_configs"),
    ]

    operations = [
        migrations.AlterField(
            model_name="approvalgateconfig",
            name="pending_approval_state",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="db.state",
            ),
        ),
        migrations.AlterField(
            model_name="approvalgateconfig",
            name="approved_state",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="db.state",
            ),
        ),
        migrations.AlterField(
            model_name="approvalgateconfig",
            name="sent_back_state",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="db.state",
            ),
        ),
        migrations.RunPython(backfill_registration_handoff_configs, noop_reverse),
    ]
