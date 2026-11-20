import re
from decimal import Decimal

from django import forms

from accounts.bootstrap import BootstrapMixin
from inventory.models import Cereal

from .models import Payment


class CerealChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, cereal):
        return f"{cereal.name}  -  KES {cereal.price_per_kg:,.2f}/kg"


class AddItemForm(BootstrapMixin, forms.Form):
    cereal = CerealChoiceField(queryset=Cereal.objects.none(), empty_label="Choose a cereal")
    quantity_kg = forms.DecimalField(
        label="Weight (kg)", max_digits=8, decimal_places=3, min_value=Decimal("0.001"),
        widget=forms.NumberInput(attrs={"step": "0.001", "inputmode": "decimal"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cereal"].queryset = Cereal.objects.filter(is_active=True)


class PaymentForm(BootstrapMixin, forms.Form):
    cash = forms.DecimalField(label="Cash (KES)", max_digits=12, decimal_places=2,
                              min_value=Decimal("0"), required=False)
    mpesa = forms.DecimalField(label="M-Pesa (KES)", max_digits=12, decimal_places=2,
                               min_value=Decimal("0"), required=False)
    mpesa_ref = forms.CharField(label="M-Pesa confirmation code", max_length=20, required=False)
    card = forms.DecimalField(label="Card (KES)", max_digits=12, decimal_places=2,
                              min_value=Decimal("0"), required=False)

    def __init__(self, *args, total, **kwargs):
        super().__init__(*args, **kwargs)
        self.total = total

    def clean_mpesa_ref(self):
        return self.cleaned_data["mpesa_ref"].strip().upper()

    def clean(self):
        cleaned = super().clean()
        cash = cleaned.get("cash") or Decimal("0")
        mpesa = cleaned.get("mpesa") or Decimal("0")
        card = cleaned.get("card") or Decimal("0")
        paid = cash + mpesa + card
        if paid != self.total:
            raise forms.ValidationError(
                f"Payments add up to KES {paid:,.2f} but the sale total is KES {self.total:,.2f}."
            )
        if mpesa > 0:
            ref = cleaned.get("mpesa_ref", "")
            if not re.fullmatch(r"[A-Z0-9]{10}", ref or ""):
                self.add_error("mpesa_ref", "Enter the 10-character M-Pesa code (for example QGH7XYZ123).")
            else:
                used = Payment.objects.filter(method=Payment.Method.MPESA, reference=ref).select_related("sale").first()
                if used:
                    self.add_error("mpesa_ref", f"This code was already used on receipt {used.sale.receipt_no}.")
        return cleaned

    def payments(self):
        data = self.cleaned_data
        rows = []
        if data.get("cash"):
            rows.append({"method": Payment.Method.CASH, "amount": data["cash"], "reference": ""})
        if data.get("mpesa"):
            rows.append({"method": Payment.Method.MPESA, "amount": data["mpesa"], "reference": data["mpesa_ref"]})
        if data.get("card"):
            rows.append({"method": Payment.Method.CARD, "amount": data["card"], "reference": ""})
        return rows


class ClockInForm(BootstrapMixin, forms.Form):
    opening_float = forms.DecimalField(
        label="Cash in the drawer right now (KES)", max_digits=10, decimal_places=2,
        min_value=Decimal("0"), initial=0,
    )


class ClockOutForm(BootstrapMixin, forms.Form):
    counted_cash = forms.DecimalField(
        label="Count the drawer: total cash (KES)", max_digits=12, decimal_places=2, min_value=Decimal("0"),
    )
    note = forms.CharField(label="Note (optional)", max_length=200, required=False)