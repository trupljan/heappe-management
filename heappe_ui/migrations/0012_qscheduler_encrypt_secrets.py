"""Store the SSH private key, key passphrase and DATABASE_URL of QScheduler instances encrypted (Fernet)."""
from django.db import migrations, models

SECRETS = ("ssh_private_key", "ssh_key_passphrase", "database_url")


def encrypt_existing(apps, schema_editor):
    from heappe_ui.models import encrypt_secret
    Q = apps.get_model("heappe_ui", "QSchedulerInstance")
    for inst in Q.objects.all():
        for f in SECRETS:
            value = getattr(inst, f)
            setattr(inst, f"{f}_encrypted", encrypt_secret(value) if value else "")
        inst.save(update_fields=[f"{f}_encrypted" for f in SECRETS])


def decrypt_existing(apps, schema_editor):
    from heappe_ui.models import decrypt_secret
    Q = apps.get_model("heappe_ui", "QSchedulerInstance")
    for inst in Q.objects.all():
        for f in SECRETS:
            setattr(inst, f, decrypt_secret(getattr(inst, f"{f}_encrypted")))
        inst.save(update_fields=list(SECRETS))


class Migration(migrations.Migration):

    dependencies = [
        ("heappe_ui", "0011_qscheduler_network_and_aliases"),
    ]

    operations = [
        *[migrations.AddField(model_name="qschedulerinstance", name=f"{f}_encrypted",
                              field=models.TextField(blank=True, default="")) for f in SECRETS],
        migrations.RunPython(encrypt_existing, decrypt_existing),
        migrations.RemoveField(model_name="qschedulerinstance", name="ssh_private_key"),
        migrations.RemoveField(model_name="qschedulerinstance", name="ssh_key_passphrase"),
        migrations.RemoveField(model_name="qschedulerinstance", name="database_url"),
    ]
