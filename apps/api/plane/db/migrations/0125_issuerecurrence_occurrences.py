from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("db", "0124_remove_issuerecurrence_field_snapshot"),
    ]

    operations = [
        migrations.AddField(
            model_name="issuerecurrence",
            name="occurrences",
            field=models.ManyToManyField(blank=True, related_name="+", to="db.issue"),
        ),
    ]
