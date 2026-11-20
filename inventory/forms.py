from datetime import timedelta
from decimal import Decimal

from django import forms
from django.utils import timezone

from accounts.bootstrap import BootstrapMixin

from .models import Cereal, WastageLog


class CerealForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Cereal
        fields = [
            "name", "swahili_name", "category", "icon", "image",
            "price_per_kg", "shelf_life_days", "low_stock_kg", "is_active",
        ]

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("is_active") and (cleaned.get("price_per_kg") or 0) <= 0:
            self.add_error("price_per_kg", "Set a selling price before making a cereal active.")
        return cleaned


class ReceiveStockForm(BootstrapMixin, forms.Form):
    """
    One form for both cases:
      - an existing cereal (hidden `cereal` field is filled by clicking a card), or
      - a brand-new cereal (the `new_*` fields are filled; it is added to the catalogue and stocked in one go).
    """

    # Which cereal
    cereal = forms.ModelChoiceField(queryset=Cereal.objects.all(), required=False, widget=forms.HiddenInput())

    # Only used when adding a new cereal
    new_name = forms.CharField(label="Cereal name", max_length=100, required=False)
    new_swahili_name = forms.CharField(label="Local / Swahili name (optional)", max_length=100, required=False)
    new_category = forms.ChoiceField(
        label="Category", choices=Cereal.Category.choices, required=False, initial=Cereal.Category.GRAIN
    )
    new_icon = forms.CharField(label="Icon (optional)", max_length=8, required=False)
    new_shelf_life = forms.IntegerField(
        label="Shelf life (days)", min_value=1, max_value=3650, required=False, initial=180
    )

    # The delivery itself
    quantity_kg = forms.DecimalField(
        label="Quantity received (kg)", max_digits=10, decimal_places=3, min_value=Decimal("0.001")
    )
    cost_price_per_kg = forms.DecimalField(
        label="Cost price per kg (KES)", max_digits=10, decimal_places=2, min_value=Decimal("0")
    )
    selling_price = forms.DecimalField(
        label="Selling price per kg (KES)", required=False, max_digits=10, decimal_places=2,
        min_value=Decimal("0.01"),
        help_text="Change it only if the price changes with this delivery.",
    )
    received_date = forms.DateField(
        label="Received on", initial=timezone.localdate,
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    expiry_date = forms.DateField(
        label="Expiry (optional)", required=False,
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        help_text="Leave blank to use the shelf life.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.is_new = False
        self.fields["quantity_kg"].widget.attrs.update(
            {"class": "form-control form-control-lg", "step": "0.001", "inputmode": "decimal", "placeholder": "0"}
        )

    def clean(self):
        cleaned = super().clean()
        new_name = " ".join((cleaned.get("new_name") or "").split())
        cereal = cleaned.get("cereal")

        if new_name:
            # ----- Adding a brand-new cereal -----
            self.is_new = True
            cleaned["new_name"] = new_name
            cleaned["cereal"] = None
            existing = Cereal.objects.filter(name__iexact=new_name).first()
            if existing:
                self.add_error(
                    "new_name",
                    f'"{existing.name}" is already in the catalogue. Pick it from the list instead.',
                )
            if not cleaned.get("selling_price"):
                self.add_error("selling_price", "Set a selling price for the new cereal.")
            shelf_days = cleaned.get("new_shelf_life") or 180
            cleaned["new_shelf_life"] = shelf_days
        else:
            # ----- Stocking an existing cereal -----
            if not cereal:
                if "cereal" not in self.errors:
                    raise forms.ValidationError("Pick a cereal from the list, or add a new one.")
                return cleaned
            if cereal.price_per_kg <= 0 and not cleaned.get("selling_price"):
                self.add_error("selling_price", "Set a selling price. This cereal has none yet.")
            shelf_days = cereal.shelf_life_days

        received = cleaned.get("received_date")
        if received and not cleaned.get("expiry_date"):
            cleaned["expiry_date"] = received + timedelta(days=shelf_days)
        expiry = cleaned.get("expiry_date")
        if received and expiry and expiry < received:
            self.add_error("expiry_date", "Expiry cannot be before the received date.")
        return cleaned


class WastageForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = WastageLog
        fields = ["cereal", "quantity_kg", "reason", "note"]
        labels = {"quantity_kg": "Quantity lost (kg)"}
        widgets = {"note": forms.TextInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cereal"].queryset = Cereal.objects.filter(is_active=True)

    def clean_quantity_kg(self):
        value = self.cleaned_data["quantity_kg"]
        if value <= 0:
            raise forms.ValidationError("Quantity must be more than zero.")
        return value