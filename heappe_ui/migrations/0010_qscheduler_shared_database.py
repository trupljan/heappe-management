from django.db import migrations, models
import django.db.models.deletion


def backfill_db_kind(apps, schema_editor):
    """Instances deployed by HEAppE Management with their own PostgreSQL container are 'dedicated'."""
    Q = apps.get_model("heappe_ui", "QSchedulerInstance")
    for inst in Q.objects.filter(kind="managed"):
        if f"@{inst.container_name}-pgsql:" in (inst.database_url or ""):
            inst.db_kind = "dedicated"
            inst.save(update_fields=["db_kind"])


class Migration(migrations.Migration):

    dependencies = [
        ("heappe_ui", "0009_qschedulerinstance_admin_token"),
    ]

    operations = [
        migrations.CreateModel(
            name="QSchedulerDatabase",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=63, unique=True)),
                ("image", models.CharField(max_length=255)),
                ("volume", models.CharField(max_length=255)),
                ("database", models.CharField(default="qscheduler", max_length=63)),
                ("home_network", models.CharField(max_length=255)),
                ("backup_dir", models.CharField(max_length=1024)),
                ("admin_password_encrypted", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.AddField(
            model_name="qschedulerinstance",
            name="db_kind",
            field=models.CharField(choices=[("dedicated", "Dedicated PostgreSQL container"), ("shared", "Shared database"),
                                            ("external", "External database")], default="external", max_length=16),
        ),
        migrations.AddField(
            model_name="qschedulerinstance",
            name="db_schema",
            field=models.CharField(blank=True, default="", max_length=63),
        ),
        migrations.AddField(
            model_name="qschedulerinstance",
            name="shared_database",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name="instances", to="heappe_ui.qschedulerdatabase"),
        ),
        migrations.RunPython(backfill_db_kind, migrations.RunPython.noop),
    ]
