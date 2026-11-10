from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("heappe_ui", "0013_qschedulerinstance_log_level"),
    ]

    operations = [
        migrations.AddField(
            model_name="qschedulerinstance",
            name="serve_options",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="qschedulerassignment",
            name="project_prefix",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="qschedulerassignment",
            name="projects_renamed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
