from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Sum
from django.utils import timezone

HEALTH = {
    "OUT": ("Out of stock", "danger"),
    "EXPIRED": ("Has expired stock", "danger"),
    "LOW": ("Running low", "warning"),
    "AGING": ("Aging - sell soon", "warning"),
    "OK": ("Healthy", "success"),
}

BATCH_STATUS = {
    "EMPTY": ("Empty", "secondary"),
    "EXPIRED": ("Expired", "danger"),
    "EXPIRING": ("Expiring soon", "warning"),
    "AGING": ("Aging", "warning"),
    "OK": ("Good", "success"),
}


class Cereal(models.Model):
    class Category(models.TextChoices):
        GRAIN = "GRAIN", "Grains"
        RICE = "RICE", "Rice"
        FLOUR = "FLOUR", "Flours"
        PULSE = "PULSE", "Beans & Pulses"
        OTHER = "OTHER", "Nuts & Other"

    name = models.CharField(max_length=100, unique=True)
    swahili_name = models.CharField("Local / Swahili name", max_length=100, blank=True)
    category = models.CharField(max_length=10, choices=Category.choices, default=Category.GRAIN)
    icon = models.CharField(
        max_length=8, blank=True, help_text="An emoji shown when there is no photo."
    )
    image = models.ImageField(upload_to="cereals/", blank=True)
    price_per_kg = models.DecimalField(
        "Selling price per kg (KES)", max_digits=10, decimal_places=2, default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    shelf_life_days = models.PositiveIntegerField(
        default=180, help_text="How many days a delivery stays good."
    )
    low_stock_kg = models.DecimalField(
        "Low-stock alert (kg)", max_digits=10, decimal_places=3, default=Decimal("10"),
        help_text="Warn when sellable stock falls to this level.",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def display_icon(self):
        return self.icon or "🌾"

    @property
    def stock_kg(self):
        """Everything physically on the shelf, including expired stock."""
        return self.batches.aggregate(t=Sum("remaining_kg"))["t"] or Decimal("0")

    @property
    def sellable_kg(self):
        total = self.batches.filter(
            remaining_kg__gt=0, expiry_date__gte=timezone.localdate()
        ).aggregate(t=Sum("remaining_kg"))["t"]
        return total or Decimal("0")

    def health_info(self):
        if self.stock_kg <= 0:
            code = "OUT"
        else:
            statuses = {b.status for b in self.batches.filter(remaining_kg__gt=0)}
            if "EXPIRED" in statuses:
                code = "EXPIRED"
            elif self.sellable_kg <= self.low_stock_kg:
                code = "LOW"
            elif statuses & {"EXPIRING", "AGING"}:
                code = "AGING"
            else:
                code = "OK"
        label, css = HEALTH[code]
        return {"code": code, "label": label, "css": css}


class StockBatch(models.Model):
    """One delivery of one cereal. Sales draw from the oldest batch first."""

    cereal = models.ForeignKey(Cereal, on_delete=models.PROTECT, related_name="batches")
    quantity_kg = models.DecimalField(max_digits=10, decimal_places=3)
    remaining_kg = models.DecimalField(max_digits=10, decimal_places=3, default=Decimal("0"))
    cost_price_per_kg = models.DecimalField(max_digits=10, decimal_places=2)
    received_date = models.DateField(default=timezone.localdate)
    expiry_date = models.DateField()
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["received_date", "id"]

    def __str__(self):
        return f"{self.cereal.name} ({self.received_date})"

    @property
    def days_to_expiry(self):
        return (self.expiry_date - timezone.localdate()).days

    @property
    def status(self):
        if self.remaining_kg <= 0:
            return "EMPTY"
        days_left = self.days_to_expiry
        if days_left < 0:
            return "EXPIRED"
        if days_left <= settings.EXPIRY_WARNING_DAYS:
            return "EXPIRING"
        shelf = (self.expiry_date - self.received_date).days
        if shelf > 0:
            used = (timezone.localdate() - self.received_date).days
            if used * 100 >= shelf * settings.AGING_PERCENT:
                return "AGING"
        return "OK"

    @property
    def status_info(self):
        code = self.status
        label, css = BATCH_STATUS[code]
        return {"code": code, "label": label, "css": css}


class WastageLog(models.Model):
    class Reason(models.TextChoices):
        SPOILAGE = "SPOILAGE", "Spoilage / expired"
        SPILLAGE = "SPILLAGE", "Spillage"
        PEST = "PEST", "Pest damage"
        SAMPLE = "SAMPLE", "Customer sample"
        OTHER = "OTHER", "Other"

    cereal = models.ForeignKey(Cereal, on_delete=models.PROTECT, related_name="wastage_logs")
    quantity_kg = models.DecimalField(max_digits=10, decimal_places=3)
    reason = models.CharField(max_length=10, choices=Reason.choices)
    note = models.CharField(max_length=200, blank=True)
    loss_value = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    logged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class StockCount(models.Model):
    cereal = models.ForeignKey(Cereal, on_delete=models.PROTECT, related_name="counts")
    expected_kg = models.DecimalField(max_digits=10, decimal_places=3)
    counted_kg = models.DecimalField(max_digits=10, decimal_places=3)
    difference_kg = models.DecimalField(max_digits=10, decimal_places=3)
    note = models.CharField(max_length=200, blank=True)
    counted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]