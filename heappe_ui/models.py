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
