from django.db import migrations

# Mirrors plane.utils.approval's alias sets and
# plane.db.models.state.DEFAULT_APPROVAL_GATE_STATES — duplicated here
# (rather than imported) because data migrations must not depend on
# application code that can change out from under them. Keep in sync if
# either changes.
_PENDING_APPROVAL_NAMES = ["closed", "pending approval", "sent for approval"]
_APPROVED_NAMES = ["excel entry and handover", "approved", "handedover", "publish/close", "post/close", "completed"]
_SENT_BACK_NAMES = ["xerox and binding", "sent back"]


def backfill_approval_gate_configs(apps, schema_editor):
    Project = apps.get_model("db", "Project")
    State = apps.get_model("db", "State")
    ApprovalGateConfig = apps.get_model("db", "ApprovalGateConfig")

    existing_project_ids = set(
        ApprovalGateConfig.objects.filter(deleted_at__isnull=True).values_list("project_id", flat=True)
    )

    for project in Project.objects.exclude(id__in=existing_project_ids).iterator():
        states = list(
            State.objects.filter(project_id=project.id, deleted_at__isnull=True)
            .order_by("sequence")
            .only("id", "name")
        )
        if not states:
            continue

        pending_id = approved_id = sent_back_id = None
        for state in states:
            key = state.name.strip().lower()
            if pending_id is None and key in _PENDING_APPROVAL_NAMES:
                pending_id = state.id
            if approved_id is None and key in _APPROVED_NAMES:
                approved_id = state.id
            if sent_back_id is None and key in _SENT_BACK_NAMES:
                sent_back_id = state.id

        if pending_id is None and approved_id is None and sent_back_id is None:
            continue  # nothing resolves for this project — leave it to the fallback

        ApprovalGateConfig.objects.create(
            project_id=project.id,
            workspace_id=project.workspace_id,
            is_enabled=True,
            pending_approval_state_id=pending_id,
            approved_state_id=approved_id,
            sent_back_state_id=sent_back_id,
        )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("db", "0133_approvalgateconfig_is_enabled"),
    ]

    operations = [
        migrations.RunPython(backfill_approval_gate_configs, noop_reverse),
    ]
