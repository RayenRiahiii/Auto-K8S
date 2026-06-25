from django.db import models

class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

#credentials to connect to machines
class Credential(TimeStampedModel):
    class AuthType(models.TextChoices):
        SSH_KEY = "ssh_key", "SSH Key"
        PASSWORD = "password", "Password"

    name = models.CharField(max_length=100, unique=True)
    auth_type = models.CharField(max_length=20, choices=AuthType.choices)
    username = models.CharField(max_length=100)
    private_key = models.TextField(blank=True)
    password = models.CharField(max_length=255, blank=True)
    become_password = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return self.name

#target machine
class Host(TimeStampedModel):
    name = models.CharField(max_length=100, unique=True)
    hostname = models.CharField(max_length=255, blank=True)
    ip_address = models.GenericIPAddressField(protocol="IPv4", unique=True)
    ssh_port = models.PositiveIntegerField(default=22)
    os_type = models.CharField(max_length=50, blank=True)
    enabled = models.BooleanField(default=True)
    credential = models.ForeignKey(
        Credential,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="hosts",
    )

    def __str__(self):
        return self.name

#template to select the playbook
class InstallationTemplate(TimeStampedModel):
    name = models.CharField(max_length=100, unique=True)
    playbook_path = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name

#installation process for all targets selected
class Installation(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"

    template = models.ForeignKey(
        InstallationTemplate,
        on_delete=models.CASCADE,
        related_name="installations",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Installation #{self.pk} - {self.template.name}"

#installation process for one target
class InstallationTarget(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"

    installation = models.ForeignKey(
        Installation,
        on_delete=models.CASCADE,
        related_name="targets",
    )
    host = models.ForeignKey(
        Host,
        on_delete=models.CASCADE,
        related_name="installation_targets",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    output = models.TextField(blank=True)

    class Meta:
        unique_together = ("installation", "host")

    def __str__(self):
        return f"{self.installation} -> {self.host.name}"
