from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Sum
from django.utils import timezone


class Shift(models.Model):
    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="shifts")
    clock_in = models.DateTimeField(default=timezone.now)
    clock_out = models.DateTimeField(null=True, blank=True)
    opening_float = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    closed_by_admin = models.BooleanField(default=False)
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-clock_in"]

    def __str__(self):
        return f"{self.employee.employee_id} {self.clock_in:%Y-%m-%d %H:%M}"

    @property
    def is_open(self):
        return self.clock_out is None

    @property
    def hours(self):
        end = self.clock_out or timezone.now()
        return round((end - self.clock_in).total_seconds() / 3600, 2)

    def cash_sales(self):
        total = Payment.objects.filter(
            sale__shift=self, sale__status=Sale.Status.PAID, method=Payment.Method.CASH
        ).aggregate(t=Sum("amount"))["t"]
        return total or Decimal("0")

    def expected_cash(self):
        return self.opening_float + self.cash_sales()


class CashCount(models.Model):
    """End-of-shift drawer count, compared with what the system expects."""

    shift = models.OneToOneField(Shift, on_delete=models.CASCADE, related_name="cash_count")
    counted_cash = models.DecimalField(max_digits=12, decimal_places=2)
    expected_cash = models.DecimalField(max_digits=12, decimal_places=2)
    difference = models.DecimalField(max_digits=12, decimal_places=2)  # counted - expected
    note = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Sale(models.Model):
    class Status(models.TextChoices):
        OPEN = "OPEN", "In progress"
        PAID = "PAID", "Paid"
        ABANDONED = "ABANDONED", "Abandoned"
        VOID = "VOID", "Voided"

    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="sales")
    shift = models.ForeignKey(Shift, null=True, blank=True, on_delete=models.PROTECT, related_name="sales")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    receipt_no = models.CharField(max_length=30, unique=True, null=True, blank=True)
    tax_invoice_ref = models.CharField(max_length=50, blank=True)  # KRA eTIMS invoice number, later phase
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    void_reason = models.CharField(max_length=200, blank=True)
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    voided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.receipt_no or f"Sale #{self.pk}"

    def recalc_total(self):
        self.total = self.items.aggregate(t=Sum("line_total"))["t"] or Decimal("0")
        self.save(update_fields=["total", "updated_at"])


class SaleItem(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="items")
    cereal = models.ForeignKey("inventory.Cereal", on_delete=models.PROTECT, related_name="sale_items")
    quantity_kg = models.DecimalField(max_digits=10, decimal_places=3)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)  # price at the time of sale
    line_total = models.DecimalField(max_digits=12, decimal_places=2)


class BatchAllocation(models.Model):
    """Which delivery(ies) a sale line was taken from. Gives true profit and lets a void restore stock."""

    sale_item = models.ForeignKey(SaleItem, on_delete=models.CASCADE, related_name="allocations")
    batch = models.ForeignKey("inventory.StockBatch", on_delete=models.PROTECT, related_name="allocations")
    quantity_kg = models.DecimalField(max_digits=10, decimal_places=3)
    cost_price_per_kg = models.DecimalField(max_digits=10, decimal_places=2)


class Payment(models.Model):
    class Method(models.TextChoices):
        CASH = "CASH", "Cash"
        MPESA = "MPESA", "M-Pesa"
        CARD = "CARD", "Card"

    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="payments")
    method = models.CharField(max_length=10, choices=Method.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reference = models.CharField(max_length=30, blank=True)  # M-Pesa confirmation code