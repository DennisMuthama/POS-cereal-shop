from datetime import timedelta

from django.conf import settings
from django.db.models import Count
from django.utils import timezone

from .models import Anomaly


def flag(kind, severity, message, employee=None, key=None):
    """Raise a flag once. The same `key` never creates a second flag."""
    if key is None:
        key = f"{kind}:{timezone.now().timestamp()}"
    anomaly, _ = Anomaly.objects.get_or_create(
        key=key,
        defaults={"kind": kind, "severity": severity, "message": message, "employee": employee},
    )
    return anomaly


def run_checks():
    """Time-based checks. Runs whenever the owner opens the dashboard."""
    from accounts.models import Employee
    from inventory.models import StockBatch
    from sales.models import Sale, Shift
    from sales.services import abandon_stale_sales

    abandon_stale_sales()
    now = timezone.now()
    today = timezone.localdate()

    # Shifts that were never closed
    limit = now - timedelta(hours=settings.SHIFT_MAX_HOURS)
    for shift in Shift.objects.filter(clock_out__isnull=True, clock_in__lt=limit).select_related("employee"):
        flag(
            "SHIFT_OPEN", "MEDIUM",
            f"{shift.employee.full_name} clocked in on {timezone.localtime(shift.clock_in):%d %b at %H:%M} "
            f"and has not clocked out.",
            shift.employee, f"SHIFT_OPEN:{shift.pk}",
        )

    # Many abandoned sales by one employee today
    rows = (
        Sale.objects.filter(status=Sale.Status.ABANDONED, updated_at__date=today)
        .values("employee").annotate(n=Count("id")).order_by().filter(n__gte=settings.ABANDONED_FLAG_COUNT)
    )
    for row in rows:
        emp = Employee.objects.get(pk=row["employee"])
        flag(
            "ABANDONED", "MEDIUM",
            f"{emp.full_name} has {row['n']} abandoned sales today.",
            emp, f"ABANDONED:{emp.pk}:{today}",
        )

    # Many voids against one employee's sales this week
    rows = (
        Sale.objects.filter(status=Sale.Status.VOID, voided_at__gte=now - timedelta(days=7))
        .values("employee").annotate(n=Count("id")).order_by().filter(n__gte=settings.VOID_FLAG_COUNT)
    )
    for row in rows:
        emp = Employee.objects.get(pk=row["employee"])
        flag(
            "VOIDS", "HIGH",
            f"{row['n']} of {emp.full_name}'s sales were voided in the last 7 days.",
            emp, f"VOIDS:{emp.pk}:{today}",
        )

    # Expired and expiring stock
    for batch in StockBatch.objects.filter(remaining_kg__gt=0).select_related("cereal"):
        status = batch.status
        if status == "EXPIRED":
            flag(
                "EXPIRED", "HIGH",
                f"{batch.cereal.name}: {batch.remaining_kg:.3f} kg from the {batch.received_date:%d %b} "
                f"delivery has expired. Record it under Wastage.",
                key=f"EXPIRED:{batch.pk}",
            )
        elif status == "EXPIRING":
            flag(
                "EXPIRING", "MEDIUM",
                f"{batch.cereal.name}: {batch.remaining_kg:.3f} kg from the {batch.received_date:%d %b} "
                f"delivery expires in {batch.days_to_expiry} day(s). Sell it first.",
                key=f"EXPIRING:{batch.pk}",
            )