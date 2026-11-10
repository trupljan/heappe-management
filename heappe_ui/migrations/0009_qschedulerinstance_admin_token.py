from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("heappe_ui", "0008_qschedulerinstance_extra_hosts"),
    ]

    operations = [
        migrations.AddField(
            model_name="qschedulerinstance",
            name="admin_token_encrypted",
            field=models.TextField(blank=True, default=""),
        ),
    ]
