from django.conf import settings
from django.db import models


class Anomaly(models.Model):
    class Severity(models.TextChoices):
        HIGH = "HIGH", "Serious"
        MEDIUM = "MEDIUM", "Check"
        LOW = "LOW", "Note"

    class Status(models.TextChoices):
        NEW = "NEW", "New"
        REVIEWED = "REVIEWED", "Reviewed"

    kind = models.CharField(max_length=30)
    severity = models.CharField(max_length=10, choices=Severity.choices)
    employee = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="anomalies"
    )
    message = models.TextField()
    key = models.CharField(max_length=120, unique=True)  # prevents the same flag being raised twice
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.NEW)
    note = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "anomalies"

    def __str__(self):
        return self.message[:60]

    @property
    def css(self):
        return {"HIGH": "danger", "MEDIUM": "warning", "LOW": "secondary"}[self.severity]