from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render

from accounts import audit
from accounts.decorators import owner_required

from . import services
from .forms import CerealForm, ReceiveStockForm, WastageForm
from .models import Cereal, StockBatch, StockCount, WastageLog

# Used when a new cereal is added without choosing an icon
DEFAULT_ICONS = {
    "GRAIN": "🌾",
    "RICE": "🍚",
    "FLOUR": "🌾",
    "PULSE": "🫘",
    "OTHER": "🥜",
}


@owner_required
def batches(request):
    show_all = request.GET.get("all") == "1"
    qs = StockBatch.objects.select_related("cereal", "received_by")
    if not show_all:
        qs = qs.filter(remaining_kg__gt=0)
    summary = [
        {"cereal": c, "stock": c.stock_kg, "health": c.health_info()}
        for c in Cereal.objects.filter(is_active=True)
    ]
    return render(request, "inventory/batches.html", {"summary": summary, "batches": qs, "show_all": show_all})


@owner_required
def cereal_list(request):
    show_all = request.GET.get("all") == "1"
    qs = Cereal.objects.all() if show_all else Cereal.objects.filter(is_active=True)
    rows = [{"cereal": c, "stock": c.stock_kg, "health": c.health_info()} for c in qs]
    return render(request, "inventory/cereal_list.html", {"rows": rows, "show_all": show_all})


@owner_required
def cereal_edit(request, pk=None):
    cereal = get_object_or_404(Cereal, pk=pk) if pk else None
    old_price = cereal.price_per_kg if cereal else None
    form = CerealForm(request.POST or None, request.FILES or None, instance=cereal)
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        if cereal is None:
            audit.log(request.user, "CEREAL_ADDED", f"{saved.name} at KES {saved.price_per_kg}/kg", request)
            messages.success(request, f"{saved.name} added. Now receive stock for it.")
        else:
            if old_price != saved.price_per_kg:
                audit.log(request.user, "PRICE_CHANGED", f"{saved.name}: {old_price} -> {saved.price_per_kg}", request)
            messages.success(request, f"{saved.name} updated.")
        return redirect("inventory:cereals")
    return render(request, "inventory/cereal_form.html", {"form": form, "cereal": cereal})


@owner_required
def receive_stock(request):
    form = ReceiveStockForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data

        with transaction.atomic():
            if form.is_new:
                # Add the cereal to the catalogue first, so it is a normal selectable cereal from now on
                category = data.get("new_category") or Cereal.Category.OTHER
                icon = (data.get("new_icon") or "").strip() or DEFAULT_ICONS.get(category, "🌾")
                cereal = Cereal.objects.create(
                    name=data["new_name"],
                    swahili_name=data.get("new_swahili_name") or "",
                    category=category,
                    icon=icon,
                    price_per_kg=data["selling_price"],
                    shelf_life_days=data["new_shelf_life"],
                    is_active=True,
                )
                audit.log(
                    request.user, "CEREAL_ADDED",
                    f"{cereal.name} at KES {cereal.price_per_kg}/kg (added while receiving stock)", request,
                )
            else:
                cereal = data["cereal"]
                new_price = data.get("selling_price")
                if new_price and new_price != cereal.price_per_kg:
                    audit.log(
                        request.user, "PRICE_CHANGED",
                        f"{cereal.name}: {cereal.price_per_kg} -> {new_price}", request,
                    )
                    cereal.price_per_kg = new_price
                if not cereal.is_active:
                    cereal.is_active = True
                    audit.log(request.user, "CEREAL_ACTIVATED", cereal.name, request)
                cereal.save()

            batch = StockBatch.objects.create(
                cereal=cereal,
                quantity_kg=data["quantity_kg"],
                remaining_kg=data["quantity_kg"],
                cost_price_per_kg=data["cost_price_per_kg"],
                received_date=data["received_date"],
                expiry_date=data["expiry_date"],
                received_by=request.user,
            )
            audit.log(
                request.user, "STOCK_RECEIVED",
                f"{batch.quantity_kg} kg {cereal.name} at cost {batch.cost_price_per_kg}", request,
            )

        if form.is_new:
            messages.success(
                request,
                f"{cereal.name} added to the catalogue and {batch.quantity_kg} kg received. "
                f"You can add a photo under Cereals & Prices.",
            )
        else:
            messages.success(request, f"Received {batch.quantity_kg} kg of {cereal.name}.")
        return redirect("inventory:batches")

    cereals = list(Cereal.objects.all())
    for c in cereals:
        last = c.batches.order_by("-received_date", "-id").first()
        c.last_cost = last.cost_price_per_kg if last else ""
        c.stock_now = c.stock_kg
    return render(request, "inventory/receive_stock.html", {
        "form": form, "cereals": cereals, "categories": Cereal.Category.choices,
    })


@login_required
def wastage(request):
    form = WastageForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            services.record_wastage(data["cereal"], data["quantity_kg"], data["reason"], data["note"], request.user)
        except services.InsufficientStock as exc:
            form.add_error("quantity_kg", str(exc))
        else:
            messages.success(request, "Wastage recorded and stock reduced.")
            return redirect("inventory:wastage")
    logs = WastageLog.objects.select_related("cereal", "logged_by")
    if not request.user.is_owner:
        logs = logs.filter(logged_by=request.user)
    return render(request, "inventory/wastage.html", {"form": form, "logs": logs[:30]})


@owner_required
def stock_counts(request):
    cereals = list(Cereal.objects.filter(is_active=True))
    if request.method == "POST":
        note = request.POST.get("note", "").strip()
        saved, problems = 0, []
        for cereal in cereals:
            raw = request.POST.get(f"count_{cereal.pk}", "").strip()
            if not raw:
                continue
            try:
                counted = Decimal(raw).quantize(Decimal("0.001"))
                if counted < 0:
                    raise InvalidOperation
            except InvalidOperation:
                problems.append(cereal.name)
                continue
            services.record_stock_count(cereal, counted, note, request.user)
            saved += 1
        if saved:
            messages.success(request, f"{saved} count(s) recorded. System stock now matches what you counted.")
        if problems:
            messages.error(request, "Invalid number for: " + ", ".join(problems))
        if not saved and not problems:
            messages.warning(request, "Enter at least one counted weight.")
        return redirect("inventory:stock_counts")

    rows = [{"cereal": c, "expected": c.stock_kg} for c in cereals]
    recent = StockCount.objects.select_related("cereal", "counted_by")[:30]
    return render(request, "inventory/stock_counts.html", {"rows": rows, "recent": recent})