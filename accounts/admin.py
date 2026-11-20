from django.contrib import admin

from .forms import EmployeeAdminForm
from .models import AuditLog, Employee


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    form = EmployeeAdminForm
    fields = ("employee_id", "full_name", "role", "is_active", "is_locked", "temp_passcode")
    list_display = ("employee_id", "full_name", "role", "is_active", "is_locked", "must_change_passcode")
    list_filter = ("role", "is_active", "is_locked")
    search_fields = ("employee_id", "full_name")
    ordering = ("employee_id",)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "actor", "action", "detail", "ip_address")
    list_filter = ("action",)
    search_fields = ("actor__employee_id", "actor__full_name", "detail")
    date_hierarchy = "created_at"

    # The audit log is read-only for everyone, including the owner.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False