from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("db", "0123_issuerecurrence_days_of_month"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="issuerecurrence",
            name="field_snapshot",
        ),
    ]
