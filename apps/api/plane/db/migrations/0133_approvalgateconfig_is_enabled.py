import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("db", "0132_registrationhandoffrecord"),
    ]

    operations = [
        migrations.AddField(
            model_name="approvalgateconfig",
            name="is_enabled",
            field=models.BooleanField(default=True),
        ),
        migrations.AlterField(
            model_name="approvalgateconfig",
            name="pending_approval_state",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
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
                on_delete=django.db.models.deletion.CASCADE,
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
                on_delete=django.db.models.deletion.CASCADE,
                related_name="+",
                to="db.state",
            ),
        ),
        migrations.AddConstraint(
            model_name="approvalgateconfig",
            constraint=models.UniqueConstraint(
                condition=models.Q(("deleted_at__isnull", True)),
                fields=("project",),
                name="approval_gate_config_unique_project_when_deleted_at_null",
            ),
        ),
    ]
