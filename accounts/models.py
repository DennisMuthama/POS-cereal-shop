from django.db import models
from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone


class EmployeeManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, employee_id, full_name, password=None, **extra_fields):
        if not employee_id:
            raise ValueError("Employees must have an employee ID.")
        employee = self.model(
            employee_id=employee_id.strip().upper(),
            full_name=full_name,
            **extra_fields,
        )
        employee.set_password(password)
        employee.save(using=self._db)
        return employee

    def create_superuser(self, employee_id, full_name, password=None, **extra_fields):
        extra_fields.setdefault("role", self.model.Role.ADMIN)
        return self.create_user(employee_id, full_name, password, **extra_fields)


class Employee(AbstractBaseUser, PermissionsMixin):
    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Admin / Owner"
        CASHIER = "CASHIER", "Cashier"

    employee_id = models.CharField(max_length=20, unique=True)
    full_name = models.CharField(max_length=120)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.CASHIER)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False, editable=False)

    must_change_passcode = models.BooleanField(default=False)
    failed_attempts = models.PositiveSmallIntegerField(default=0)
    is_locked = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = EmployeeManager()

    USERNAME_FIELD = "employee_id"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        ordering = ["employee_id"]

    def __str__(self):
        return f"{self.employee_id} - {self.full_name}"

    @property
    def is_owner(self):
        return self.role == self.Role.ADMIN

    def save(self, *args, **kwargs):
        self.employee_id = self.employee_id.strip().upper()
        # Role is the single source of truth for admin-site access.
        is_admin_role = self.role == self.Role.ADMIN
        self.is_staff = is_admin_role
        self.is_superuser = is_admin_role
        super().save(*args, **kwargs)

    def register_failed_attempt(self):
        self.failed_attempts += 1
        if self.failed_attempts >= settings.MAX_FAILED_ATTEMPTS:
            self.is_locked = True
        self.save(update_fields=["failed_attempts", "is_locked"])

    def reset_failed_attempts(self):
        if self.failed_attempts:
            self.failed_attempts = 0
            self.save(update_fields=["failed_attempts"])


class AuditLog(models.Model):
    """Append-only record of sensitive actions. Never edited or deleted."""

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_entries",
    )
    action = models.CharField(max_length=50)
    detail = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.action}"
