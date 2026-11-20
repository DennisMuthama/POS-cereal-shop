from django.shortcuts import render

from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts import audit
from accounts.decorators import owner_required
from inventory.models import Cereal
from inventory.services import InsufficientStock

from . import services
from .forms import AddItemForm, ClockInForm, ClockOutForm, PaymentForm
from .models import Sale, Shift


def _form_errors(form):
    return " ".join(str(e) for errors in form.errors.values() for e in errors)


def _active_sale(request):
    """The employee's sale in progress, or None if they have not clocked in."""
    if services.open_shift_for(request.user) is None:
        return None
    return services.get_or_start_sale(request.user)


# ---------- Sale screen ----------

@login_required
def new_sale(request):
    sale = _active_sale(request)
    if sale is None:
        messages.warning(request, "Clock in first. Sales are only allowed during an open shift.")
        return redirect("sales:clock")

    since = timezone.now() - timedelta(days=30)
    popular = list(
        Cereal.objects.filter(
            is_active=True,
            sale_items__sale__status=Sale.Status.PAID,
            sale_items__sale__paid_at__gte=since,
        ).annotate(n=Count("sale_items")).order_by("-n")[:8]
    )
    if not popular:
        popular = list(Cereal.objects.filter(is_active=True)[:8])

    form = AddItemForm(initial={"cereal": request.GET.get("cereal")})
    return render(request, "sales/new_sale.html", {
        "sale": sale, "items": sale.items.select_related("cereal"), "popular": popular, "form": form,
    })


@login_required
@require_POST
def add_item(request):
    sale = _active_sale(request)
    if sale is None:
        return redirect("sales:clock")
    form = AddItemForm(request.POST)
    if form.is_valid():
        try:
            services.add_item(sale, form.cleaned_data["cereal"], form.cleaned_data["quantity_kg"])
        except (InsufficientStock, ValueError) as exc:
            messages.error(request, str(exc))
    else:
        messages.error(request, _form_errors(form))
    return redirect("sales:new_sale")


@login_required
@require_POST
def remove_item(request, pk):
    sale = _active_sale(request)
    if sale is None:
        return redirect("sales:clock")
    get_object_or_404(sale.items, pk=pk).delete()
    sale.recalc_total()
    return redirect("sales:new_sale")


@login_required
def pay(request):
    sale = _active_sale(request)
    if sale is None:
        return redirect("sales:clock")
    if not sale.items.exists():
        messages.warning(request, "Add at least one cereal first.")
        return redirect("sales:new_sale")

    form = PaymentForm(request.POST or None, total=sale.total, initial={"cash": sale.total})
    if request.method == "POST" and form.is_valid():
        try:
            paid_sale = services.complete_sale(sale, form.payments())
        except InsufficientStock as exc:
            messages.error(request, f"{exc} Remove or reduce that item.")
            return redirect("sales:new_sale")
        except ValueError as exc:
            messages.error(request, str(exc))
        else:
            user = request.user
            audit.log(user, "SALE_PAID", f"{paid_sale.receipt_no}, KES {paid_sale.total}", request)
            audit.log(user, "LOGOUT", "Automatic logout after sale", request)
            logout(request)  # monitor is free for the next employee
            request.session["last_receipt_id"] = paid_sale.pk
            return redirect("sales:receipt_done")

    return render(request, "sales/pay.html", {
        "sale": sale, "items": sale.items.select_related("cereal"), "form": form,
    })


# ---------- Receipts ----------

def receipt_done(request):
    """Shown right after payment, when the employee has already been logged off."""
    sale_id = request.session.get("last_receipt_id")
    if not sale_id:
        return redirect("accounts:idle")
    sale = get_object_or_404(
        Sale.objects.select_related("employee").prefetch_related("items__cereal", "payments"),
        pk=sale_id, status=Sale.Status.PAID,
    )
    return render(request, "sales/receipt_done.html", {"sale": sale})


def receipt_clear(request):
    request.session.pop("last_receipt_id", None)
    return redirect("accounts:idle")


@login_required
def receipts(request):
    qs = Sale.objects.filter(status__in=[Sale.Status.PAID, Sale.Status.VOID]).select_related("employee")
    if not request.user.is_owner:
        qs = qs.filter(employee=request.user)
    query = request.GET.get("q", "").strip()
    if query:
        qs = qs.filter(receipt_no__icontains=query)
    return render(request, "sales/receipts.html", {"sales": qs.order_by("-paid_at")[:100], "query": query})


@login_required
def receipt_detail(request, pk):
    sale = get_object_or_404(
        Sale.objects.select_related("employee", "voided_by").prefetch_related("items__cereal", "payments"),
        pk=pk, status__in=[Sale.Status.PAID, Sale.Status.VOID],
    )
    if not request.user.is_owner and sale.employee_id != request.user.pk:
        raise Http404
    return render(request, "sales/receipt_detail.html", {"sale": sale})


@owner_required
@require_POST
def void_sale(request, pk):
    sale = get_object_or_404(Sale, pk=pk)
    reason = request.POST.get("reason", "").strip()
    if not reason:
        messages.error(request, "Give a reason for the void.")
    else:
        try:
            services.void_sale(sale, request.user, reason)
            messages.success(request, "Sale voided and stock returned.")
        except ValueError as exc:
            messages.error(request, str(exc))
    return redirect("sales:receipt_detail", pk=pk)


# ---------- Clock in / out ----------

@login_required
def clock(request):
    shift = services.open_shift_for(request.user)

    if shift is None:
        form = ClockInForm(request.POST or None)
        if request.method == "POST" and form.is_valid():
            services.clock_in(request.user, form.cleaned_data["opening_float"])
            messages.success(request, "You are clocked in. You can start selling.")
            return redirect("sales:new_sale")
        return render(request, "sales/clock.html", {"form": form, "shift": None})

    form = ClockOutForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = request.user
        services.clock_out(shift, form.cleaned_data["counted_cash"], form.cleaned_data["note"])
        audit.log(user, "LOGOUT", "Logout after clock out", request)
        logout(request)
        messages.success(request, f"Shift closed. You worked {shift.hours} hours. Your cash count was saved.")
        return redirect("accounts:idle")
    return render(request, "sales/clock.html", {"form": form, "shift": shift})


@owner_required
def shifts(request):
    return render(request, "sales/shifts.html", {
        "shifts": Shift.objects.select_related("employee", "cash_count")[:100],
    })


@owner_required
@require_POST
def force_close_shift(request, pk):
    shift = get_object_or_404(Shift, pk=pk, clock_out__isnull=True)
    reason = request.POST.get("reason", "").strip()
    if not reason:
        messages.error(request, "Give a reason for closing this shift.")
    else:
        services.force_close_shift(shift, request.user, reason)
        messages.success(request, "Shift closed.")
    return redirect("sales:shifts")