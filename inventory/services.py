from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from accounts import audit
from reports.engine import flag

from .models import StockBatch, StockCount, WastageLog


class InsufficientStock(Exception):
    pass


def deduct_fifo(cereal, kg, include_expired=False):
    """
    Take `kg` from the oldest batches first.
    Returns [(batch, kg_taken), ...]. Call this inside transaction.atomic().
    Sales skip expired stock; wastage and counts include it.
    """
    kg = Decimal(kg)
    qs = cereal.batches.select_for_update().filter(remaining_kg__gt=0)
    if not include_expired:
        qs = qs.filter(expiry_date__gte=timezone.localdate())
    batches = list(qs.order_by("received_date", "id"))

    available = sum((b.remaining_kg for b in batches), Decimal("0"))
    if available < kg:
        raise InsufficientStock(f"Only {available:.3f} kg of {cereal.name} available.")

    taken, needed = [], kg
    for batch in batches:
        if needed <= 0:
            break
        take = min(batch.remaining_kg, needed)
        batch.remaining_kg -= take
        batch.save(update_fields=["remaining_kg"])
        taken.append((batch, take))
        needed -= take
    return taken


def adjust_to_count(cereal, counted, user=None):
    """Make system stock equal the physical count (shortage oldest-first, surplus to newest batch)."""
    diff = counted - cereal.stock_kg
    if diff < 0:
        deduct_fifo(cereal, -diff, include_expired=True)
    elif diff > 0:
        batch = cereal.batches.order_by("-received_date", "-id").first()
        if batch is None:
            today = timezone.localdate()
            StockBatch.objects.create(
                cereal=cereal, quantity_kg=diff, remaining_kg=diff, cost_price_per_kg=0,
                received_date=today, expiry_date=today + timedelta(days=cereal.shelf_life_days),
                received_by=user,
            )
        else:
            batch.remaining_kg += diff
            batch.save(update_fields=["remaining_kg"])


@transaction.atomic
def record_wastage(cereal, kg, reason, note, user):
    taken = deduct_fifo(cereal, kg, include_expired=True)
    loss = sum((b.cost_price_per_kg * used for b, used in taken), Decimal("0"))
    log = WastageLog.objects.create(
        cereal=cereal, quantity_kg=kg, reason=reason, note=note,
        loss_value=loss.quantize(Decimal("0.01")), logged_by=user,
    )
    audit.log(user, "WASTAGE", f"{kg} kg {cereal.name} ({log.get_reason_display()})")
    if kg >= Decimal(str(settings.WASTAGE_FLAG_KG)):
        flag(
            "WASTAGE", "MEDIUM",
            f"{user.full_name} wrote off {kg:.3f} kg of {cereal.name} as "
            f"{log.get_reason_display().lower()} (KES {loss:,.2f}).",
            employee=user, key=f"WASTAGE:{log.pk}",
        )
    return log


@transaction.atomic
def record_stock_count(cereal, counted, note, user):
    expected = cereal.stock_kg
    diff = counted - expected
    count = StockCount.objects.create(
        cereal=cereal, expected_kg=expected, counted_kg=counted,
        difference_kg=diff, note=note, counted_by=user,
    )
    if diff != 0:
        adjust_to_count(cereal, counted, user)
    audit.log(user, "STOCK_COUNT", f"{cereal.name}: expected {expected}, counted {counted}")

    if abs(diff) > Decimal(str(settings.STOCK_TOLERANCE_KG)):
        if diff < 0:
            flag(
                "STOCK_SHORT", "HIGH",
                f"{cereal.name}: system says {expected:.3f} kg, counted {counted:.3f} kg "
                f"({-diff:.3f} kg missing).",
                key=f"STOCK:{count.pk}",
            )
        else:
            flag(
                "STOCK_OVER", "MEDIUM",
                f"{cereal.name}: system says {expected:.3f} kg, counted {counted:.3f} kg "
                f"({diff:.3f} kg more than expected).",
                key=f"STOCK:{count.pk}",
            )
    return count