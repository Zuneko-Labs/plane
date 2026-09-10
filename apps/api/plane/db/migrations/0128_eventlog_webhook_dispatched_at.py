# Generated manually to accompany event_log.py's webhook_dispatched_at field.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('db', '0127_webhooklog_outbox_event_id'),
    ]

    operations = [
        migrations.AddField(
            model_name='eventlog',
            name='webhook_dispatched_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddIndex(
            model_name='eventlog',
            index=models.Index(
                condition=models.Q(('dispatched_at__isnull', False), ('webhook_dispatched_at__isnull', True)),
                fields=['webhook_dispatched_at'],
                name='event_log_webhook_retry_idx',
            ),
        ),
    ]
