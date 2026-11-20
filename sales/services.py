from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from accounts import audit
from inventory.services import InsufficientStock, deduct_fifo
from reports.engine import flag

from .models import BatchAllocation, CashCount, Payment, Sale, SaleItem, Shift


def money(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------- Shifts ----------

def open_shift_for(employee):
    return Shift.objects.filter(employee=employee, clock_out__isnull=True).first()


@transaction.atomic
def clock_in(employee, opening_float):
    if open_shift_for(employee):
        raise ValueError("You are already clocked in.")
    shift = Shift.objects.create(employee=employee, opening_float=opening_float)
    audit.log(employee, "CLOCK_IN", f"Opening cash KES {opening_float}")
    return shift


@transaction.atomic
def clock_out(shift, counted_cash, note=""):
    """Closes the shift and records the drawer count. Returns counted - expected."""
    abandon_open_sales(shift.employee, "Clocked out")
    expected = shift.expected_cash()
    diff = counted_cash - expected
    CashCount.objects.create(
        shift=shift, counted_cash=counted_cash, expected_cash=expected, difference=diff, note=note
    )
    shift.clock_out = timezone.now()
    shift.save(update_fields=["clock_out"])
    audit.log(shift.employee, "CLOCK_OUT", f"Counted {counted_cash}, expected {expected}")

    if abs(diff) > Decimal(str(settings.CASH_TOLERANCE_KES)):
        side = "short" if diff < 0 else "over"
        flag(
            "CASH_SHORT" if diff < 0 else "CASH_OVER",
            "HIGH" if diff < 0 else "MEDIUM",
            f"{shift.employee.full_name}'s till is {side} by KES {abs(diff):,.2f} "
            f"(counted {counted_cash:,.2f}, expected {expected:,.2f}).",
            employee=shift.employee, key=f"CASH:{shift.pk}",
        )
    return diff


@transaction.atomic
def force_close_shift(shift, owner, reason):
    abandon_open_sales(shift.employee, "Shift closed by admin")
    shift.clock_out = timezone.now()
    shift.closed_by_admin = True
    shift.note = reason
    shift.save(update_fields=["clock_out", "closed_by_admin", "note"])
    audit.log(owner, "SHIFT_FORCE_CLOSED", f"{shift.employee.employee_id}: {reason}")


# ---------- Sales ----------

def get_or_start_sale(employee):
    sale = Sale.objects.filter(employee=employee, status=Sale.Status.OPEN).first()
    if sale is None:
        sale = Sale.objects.create(employee=employee, shift=open_shift_for(employee))
    return sale


def add_item(sale, cereal, qty):
    qty = Decimal(qty)
    if qty <= 0:
        raise ValueError("Weight must be more than zero.")
    already = sum((i.quantity_kg for i in sale.items.filter(cereal=cereal)), Decimal("0"))
    available = cereal.sellable_kg
    if available < already + qty:
        raise InsufficientStock(f"Only {available:.3f} kg of {cereal.name} available.")
    item = SaleItem.objects.create(
        sale=sale, cereal=cereal, quantity_kg=qty,
        unit_price=cereal.price_per_kg, line_total=money(qty * cereal.price_per_kg),
    )
    sale.recalc_total()
    return item


def abandon_open_sales(employee, reason=""):
    """Sales left unfinished are kept as Abandoned (never silently deleted). Empty ones are dropped."""
    for sale in Sale.objects.filter(employee=employee, status=Sale.Status.OPEN):
        if sale.items.exists():
            sale.status = Sale.Status.ABANDONED
            sale.save(update_fields=["status", "updated_at"])
            audit.log(employee, "SALE_ABANDONED", f"Sale #{sale.pk}, KES {sale.total}. {reason}")
        else:
            sale.delete()


def abandon_stale_sales():
    cutoff = timezone.now() - timedelta(minutes=settings.STALE_SALE_MINUTES)
    stale = Sale.objects.filter(status=Sale.Status.OPEN, updated_at__lt=cutoff).select_related("employee")
    for employee in {s.employee for s in stale}:
        abandon_open_sales(employee, "Session expired")


def _next_receipt_no(moment):
    prefix = f"RCP-{timezone.localtime(moment):%Y%m%d}-"
    last = Sale.objects.filter(receipt_no__startswith=prefix).order_by("-receipt_no").first()
    number = int(last.receipt_no.split("-")[-1]) + 1 if last else 1
    return f"{prefix}{number:04d}"


@transaction.atomic
def complete_sale(sale, payments):
    """Deduct stock (oldest first), record payments, issue the receipt number. All or nothing."""
    sale = Sale.objects.select_for_update().get(pk=sale.pk)
    if sale.status != Sale.Status.OPEN:
        raise ValueError("This sale is no longer open.")
    items = list(sale.items.select_related("cereal"))
    if not items:
        raise ValueError("Add at least one cereal first.")

    sale.recalc_total()
    paid = sum((p["amount"] for p in payments), Decimal("0"))
    if money(paid) != sale.total:
        raise ValueError(f"Payments add up to KES {paid:,.2f} but the total is KES {sale.total:,.2f}.")

    for item in items:
        for batch, kg in deduct_fifo(item.cereal, item.quantity_kg):
            BatchAllocation.objects.create(
                sale_item=item, batch=batch, quantity_kg=kg, cost_price_per_kg=batch.cost_price_per_kg
            )
    for p in payments:
        Payment.objects.create(sale=sale, **p)

    now = timezone.now()
    sale.status = Sale.Status.PAID
    sale.paid_at = now
    sale.receipt_no = _next_receipt_no(now)
    sale.save(update_fields=["status", "paid_at", "receipt_no", "updated_at"])
    _check_sale(sale, items)
    return sale


def _check_sale(sale, items):
    local = timezone.localtime(sale.paid_at)
    if local.hour < settings.SHOP_OPEN_HOUR or local.hour >= settings.SHOP_CLOSE_HOUR:
        flag(
            "ODD_HOURS", "MEDIUM",
            f"Sale {sale.receipt_no} by {sale.employee.full_name} was made at {local:%H:%M}, outside shop hours.",
            sale.employee, f"ODD_HOURS:{sale.pk}",
        )
    limit = Decimal(str(settings.LARGE_SALE_KG))
    for item in items:
        if item.quantity_kg >= limit:
            flag(
                "LARGE_SALE", "LOW",
                f"{sale.receipt_no}: {item.quantity_kg:.3f} kg of {item.cereal.name} sold in one line "
                f"by {sale.employee.full_name}.",
                sale.employee, f"LARGE:{item.pk}",
            )


@transaction.atomic
def void_sale(sale, owner, reason):
    """Owner-only. Puts the stock back and keeps the receipt on record as VOID."""
    sale = Sale.objects.select_for_update().get(pk=sale.pk)
    if sale.status != Sale.Status.PAID:
        raise ValueError("Only paid sales can be voided.")
    for item in sale.items.all():
        for alloc in item.allocations.select_related("batch"):
            batch = alloc.batch
            batch.remaining_kg += alloc.quantity_kg
            batch.save(update_fields=["remaining_kg"])
    sale.status = Sale.Status.VOID
    sale.void_reason = reason
    sale.voided_by = owner
    sale.voided_at = timezone.now()
    sale.save(update_fields=["status", "void_reason", "voided_by", "voided_at", "updated_at"])
    audit.log(owner, "SALE_VOIDED", f"{sale.receipt_no}: {reason}")