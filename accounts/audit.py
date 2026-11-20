from .models import AuditLog


def log(actor, action, detail="", request=None):
    """Write one audit entry. `actor` may be None (e.g. unknown employee ID)."""
    ip = request.META.get("REMOTE_ADDR") if request else None
    AuditLog.objects.create(actor=actor, action=action, detail=detail, ip_address=ip)