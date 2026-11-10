from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("heappe_ui", "0012_qscheduler_encrypt_secrets"),
    ]

    operations = [
        migrations.AddField(
            model_name="qschedulerinstance",
            name="log_level",
            field=models.CharField(blank=True, default="", max_length=200),
        ),
    ]
