from django.db import models

class InstanceCredentials(models.Model):
    instance_name = models.CharField(max_length=255, unique=True)
    heappe_host = models.CharField(max_length=255)
    heappe_login = models.CharField(max_length=255)
    heappe_password = models.CharField(max_length=255)
    heappe_port = models.CharField(max_length=10)

    log_db_host = models.CharField(max_length=255)
    log_db_port = models.CharField(max_length=10)
    log_db_user = models.CharField(max_length=255)
    log_db_password = models.CharField(max_length=255)
    log_db_database = models.CharField(max_length=255)
    deployment_date_time = models.DateTimeField(auto_now_add=True)
    is_deployed = models.BooleanField(default=False)
    is_updating = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.heappe_host} - {self.heappe_login} - {self.log_db_database}"

    class Meta:
        verbose_name = "Database Credential"
        verbose_name_plural = "Database Credentials"
        constraints = [
            models.UniqueConstraint(
                fields=['instance_name'],
                name='unique_instance_name'
            )
        ]


class QSchedulerInstance(models.Model):
    """
    A QScheduler service known to HEAppE Management. It is shared: several HEAppE instances can be
    assigned to it (QSchedulerAssignment), and each of them registers its own clusters on its machines.

    kind:
      managed       - deployed by HEAppE Management on the local Docker host (service + PostgreSQL)
      local         - an existing container on the local Docker host, adopted (not removed on unregister)
      ssh_host      - an existing container on a remote VM, managed over SSH to the VM (docker CLI there)
      ssh_container - an existing remote container, managed over SSH directly into the container
    """
    KIND_MANAGED = "managed"
    KIND_LOCAL = "local"
    KIND_SSH_HOST = "ssh_host"
    KIND_SSH_CONTAINER = "ssh_container"
    KIND_CHOICES = [
        (KIND_MANAGED, "Deployed by HEAppE Management"),
        (KIND_LOCAL, "Existing local container"),
        (KIND_SSH_HOST, "Existing remote container (SSH to VM)"),
        (KIND_SSH_CONTAINER, "Existing remote container (SSH into container)"),
    ]

    name = models.CharField(max_length=63, unique=True)
    kind = models.CharField(max_length=16, choices=KIND_CHOICES)
    container_name = models.CharField(max_length=255, blank=True, default="")
    # Host name / IP and port under which HEAppE reaches the QScheduler REST API (cluster MasterNodeName).
    service_host = models.CharField(max_length=255)
    port = models.IntegerField(default=4300)

    # Remote access (ssh_host / ssh_container)
    ssh_host = models.CharField(max_length=255, blank=True, default="")
    ssh_port = models.IntegerField(default=22)
    ssh_user = models.CharField(max_length=255, blank=True, default="")
    ssh_private_key = models.TextField(blank=True, default="")
    ssh_key_passphrase = models.CharField(max_length=255, blank=True, default="")
    ssh_host_key = models.TextField(blank=True, default="")      # pinned on registration: "<type> <base64>"
    docker_command = models.CharField(max_length=255, blank=True, default="docker")   # ssh_host, e.g. "sudo docker"
    database_url = models.CharField(max_length=1024, blank=True, default="")          # ssh_container (optional); managed: for restore
    restart_command = models.CharField(max_length=1024, blank=True, default="")       # ssh_container

    # Image source (managed / update)
    source = models.CharField(max_length=16, blank=True, default="")    # git | image | external
    repo = models.CharField(max_length=512, blank=True, default="")
    ref = models.CharField(max_length=128, blank=True, default="")
    image = models.CharField(max_length=255, blank=True, default="")

    restart_pending = models.BooleanField(default=False)
    # Custom extra hosts ("host:ip") applied with --add-host when the container is (re)created; None = never
    # managed from the UI (a recreate keeps whatever the container has).
    extra_hosts = models.JSONField(null=True, blank=True, default=None)
    # Archived: the QScheduler service disappeared (e.g. removed manually); the record, its assignments and the
    # HEAppE clusters are kept until the instance is restored or deleted with its clusters.
    archived_at = models.DateTimeField(null=True, blank=True)
    archived_reason = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.kind})"

    @property
    def is_remote(self):
        return self.kind in (self.KIND_SSH_HOST, self.KIND_SSH_CONTAINER)

    @property
    def is_archived(self):
        return self.archived_at is not None


class QSchedulerAssignment(models.Model):
    """
    A HEAppE instance assigned to a QScheduler instance: network access and whether its clusters on this
    QScheduler use notifications. Notifiers are per cluster ("<heappe_identifier>.<machine>", own token kept in
    HEAppE Vault) and are created on the Clusters page; this record only holds the shared callback URL.
    """
    qscheduler = models.ForeignKey(QSchedulerInstance, on_delete=models.CASCADE, related_name="assignments")
    heappe_instance = models.ForeignKey(InstanceCredentials, on_delete=models.CASCADE, related_name="qscheduler_assignments")
    heappe_identifier = models.CharField(max_length=255, blank=True, default="")   # prefix of its notifier names
    network = models.CharField(max_length=255, blank=True, default="")   # Docker network joined for this HEAppE
    notifications_enabled = models.BooleanField(default=False)
    callback_url = models.CharField(max_length=1024, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["qscheduler", "heappe_instance"], name="unique_qscheduler_assignment"),
        ]

    def __str__(self):
        return f"{self.heappe_instance.instance_name} -> {self.qscheduler.name}"


class QSchedulerMachine(models.Model):
    """
    Definition of a machine registered in a QScheduler instance by HEAppE Management, used to register it again
    when the instance is restored. Secrets (the IQM token) are not stored; they are asked for on restore.
    """
    qscheduler = models.ForeignKey(QSchedulerInstance, on_delete=models.CASCADE, related_name="machines")
    name = models.CharField(max_length=64)
    backend = models.CharField(max_length=16, default="test")   # test | iqm
    options = models.JSONField(default=dict, blank=True)       # queue_size, limits, iqm_url, iqm_device, ...
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["qscheduler", "name"], name="unique_qscheduler_machine"),
        ]

    def __str__(self):
        return f"{self.name} ({self.backend}) on {self.qscheduler.name}"
