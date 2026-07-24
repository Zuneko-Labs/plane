from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("db", "0122_issuerecurrence"),
    ]

    operations = [
        migrations.AddField(
            model_name="issuerecurrence",
            name="days_of_month",
            field=models.JSONField(default=list),
        ),
    ]
