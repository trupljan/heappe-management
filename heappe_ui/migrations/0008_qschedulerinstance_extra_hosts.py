from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("heappe_ui", "0007_qscheduler_archive_and_machines"),
    ]

    operations = [
        migrations.AddField(
            model_name="qschedulerinstance",
            name="extra_hosts",
            field=models.JSONField(blank=True, default=None, null=True),
        ),
    ]
