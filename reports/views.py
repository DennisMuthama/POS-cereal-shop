import calendar
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.db.models import DecimalField, ExpressionWrapper, F, Sum
from django.db.models.functions import TruncDate, TruncHour, TruncMonth
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from accounts import audit
from accounts.decorators import owner_required
from accounts.models import Employee
from inventory.models import Cereal, WastageLog
from sales.models import BatchAllocation, Payment, Sale, SaleItem, Shift

from . import engine
from .models import Anomaly

RANK = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}

PERIODS = [("day", "Today"), ("week", "This week"), ("month", "This month"), ("year", "This year")]
NOUN = {"day": "today", "week": "this week", "month": "this month", "year": "this year"}
PREVIOUS = {"day": "yesterday", "week": "last week", "month": "last month", "year": "last year"}

MONEY = DecimalField(max_digits=18, decimal_places=5)


def period_range(period, today):
    """Returns (start, end, prev_start, prev_end). prev_end stops at the same point in the previous period."""
    if period == "week":
        start = today - timedelta(days=today.weekday())  # Monday
        end = start + timedelta(days=6)
        prev_start = start - timedelta(days=7)
        prev_full_end = start - timedelta(days=1)
    elif period == "month":
        start = today.replace(day=1)
        end = (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        prev_full_end = start - timedelta(days=1)
        prev_start = prev_full_end.replace(day=1)
    elif period == "year":
        start = date(today.year, 1, 1)
        end = date(today.year, 12, 31)
        prev_start = date(today.year - 1, 1, 1)
        prev_full_end = date(today.year - 1, 12, 31)
    else:  # day
        start = end = today
        prev_start = prev_full_end = today - timedelta(days=1)

    elapsed = (today - start).days
    prev_end = min(prev_start + timedelta(days=elapsed), prev_full_end)
    return start, end, prev_start, prev_end


def build_trend(period, paid_period, start, end):
    """Sales per hour / day / month as a list of bars: [{label, value, pct}]."""
    zero = Decimal("0")

    if period == "day":
        rows = paid_period.annotate(b=TruncHour("paid_at")).values("b").annotate(t=Sum("total")).order_by()
        data = {r["b"].hour: r["t"] for r in rows}
        hours = sorted(set(range(settings.SHOP_OPEN_HOUR, settings.SHOP_CLOSE_HOUR)) | set(data))
        points = [(f"{h:02d}", data.get(h, zero)) for h in hours]
        unit = "Sales per hour"

    elif period in ("week", "month"):
        rows = paid_period.annotate(b=TruncDate("paid_at")).values("b").annotate(t=Sum("total")).order_by()
        data = {r["b"]: r["t"] for r in rows}
        days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
        if period == "week":
            points = [(f"{d:%a} {d.day}", data.get(d, zero)) for d in days]
        else:
            points = [(str(d.day), data.get(d, zero)) for d in days]
        unit = "Sales per day"

    else:  # year
        rows = paid_period.annotate(b=TruncMonth("paid_at")).values("b").annotate(t=Sum("total")).order_by()
        data = {r["b"].month: r["t"] for r in rows}
        points = [(calendar.month_abbr[m], data.get(m, zero)) for m in range(1, 13)]
        unit = "Sales per month"

    biggest = max((v for _, v in points), default=zero)
    bars = []
    for label, value in points:
        pct = int(value / biggest * 100) if biggest else 0
        if value and pct < 3:
            pct = 3
        bars.append({"label": label, "value": value, "pct": pct})
    return unit, bars


@owner_required
def dashboard(request):
    engine.run_checks()

    period = request.GET.get("period", "day")
    if period not in NOUN:
        period = "day"

    today = timezone.localdate()
    start, end, prev_start, prev_end = period_range(period, today)

    paid_all = Sale.objects.filter(status=Sale.Status.PAID)
    paid_period = paid_all.filter(paid_at__date__gte=start, paid_at__date__lte=end)
    paid_prev = paid_all.filter(paid_at__date__gte=prev_start, paid_at__date__lte=prev_end)

    # ---- Sales figures for the selected period ----
    total = paid_period.aggregate(t=Sum("total"))["t"] or Decimal("0")
    prev_total = paid_prev.aggregate(t=Sum("total"))["t"] or Decimal("0")
    sales_count = paid_period.count()
    prev_count = paid_prev.count()
    average = (total / sales_count) if sales_count else Decimal("0")

    change = None
    if prev_total:
        change = int(((total - prev_total) / prev_total * 100).quantize(Decimal("1")))

    split = {
        row["method"]: row["t"]
        for row in Payment.objects.filter(sale__in=paid_period).values("method").annotate(t=Sum("amount")).order_by()
    }

    money = BatchAllocation.objects.filter(sale_item__sale__in=paid_period).aggregate(
        revenue=Sum(ExpressionWrapper(F("quantity_kg") * F("sale_item__unit_price"), output_field=MONEY)),
        cost=Sum(ExpressionWrapper(F("quantity_kg") * F("cost_price_per_kg"), output_field=MONEY)),
    )
    profit = (money["revenue"] or Decimal("0")) - (money["cost"] or Decimal("0"))

    trend_label, trend = build_trend(period, paid_period, start, end)

    top_sellers = (
        SaleItem.objects.filter(sale__in=paid_period)
        .values("cereal__name").annotate(kg=Sum("quantity_kg"), amount=Sum("line_total")).order_by("-kg")[:5]
    )

    waste = WastageLog.objects.filter(
        created_at__date__gte=start, created_at__date__lte=end
    ).aggregate(kg=Sum("quantity_kg"), value=Sum("loss_value"))

    # ---- Staff for the selected period ----
    staff = []
    for emp in Employee.objects.filter(is_active=True).order_by("employee_id"):
        mine = paid_period.filter(employee=emp)
        shifts = Shift.objects.filter(employee=emp, clock_in__date__gte=start, clock_in__date__lte=end)
        staff.append({
            "emp": emp,
            "sales": mine.count(),
            "total": mine.aggregate(t=Sum("total"))["t"] or Decimal("0"),
            "abandoned": Sale.objects.filter(
                employee=emp, status=Sale.Status.ABANDONED,
                updated_at__date__gte=start, updated_at__date__lte=end,
            ).count(),
            "voids": Sale.objects.filter(
                employee=emp, status=Sale.Status.VOID,
                voided_at__date__gte=start, voided_at__date__lte=end,
            ).count(),
            "hours": round(sum(s.hours for s in shifts), 2),
            "flags": Anomaly.objects.filter(employee=emp, status=Anomaly.Status.NEW).count(),
        })

    # ---- Right-now sections (not tied to the period) ----
    flags = sorted(
        Anomaly.objects.filter(status=Anomaly.Status.NEW).select_related("employee"),
        key=lambda a: (RANK[a.severity], -a.created_at.timestamp()),
    )
    high = sum(1 for a in flags if a.severity == Anomaly.Severity.HIGH)
    if high:
        banner = {"css": "danger", "text": f"{len(flags)} item(s) need your attention, {high} of them serious."}
    elif flags:
        banner = {"css": "warning", "text": f"{len(flags)} item(s) to review."}
    else:
        banner = {"css": "success", "text": "All clear. No issues found."}

    stock_rows = [
        {"cereal": c, "stock": c.stock_kg, "health": c.health_info()}
        for c in Cereal.objects.filter(is_active=True)
    ]
    sold_ids = set(
        SaleItem.objects.filter(
            sale__status=Sale.Status.PAID, sale__paid_at__gte=timezone.now() - timedelta(days=14)
        ).values_list("cereal_id", flat=True)
    )
    slow = [r["cereal"] for r in stock_rows if r["stock"] > 0 and r["cereal"].pk not in sold_ids]

    context = {
        "banner": banner,
        # period selection
        "period": period, "periods": PERIODS,
        "noun": NOUN[period], "prev_noun": PREVIOUS[period],
        "start": start, "end": end,
        # period figures
        "total": total, "prev_total": prev_total,
        "sales_count": sales_count, "prev_count": prev_count, "average": average,
        "change": change, "change_abs": abs(change) if change is not None else None,
        "split": split, "profit": profit,
        "trend_label": trend_label, "trend": trend,
        "top_sellers": top_sellers, "waste": waste, "staff": staff,
        # right-now sections
        "flags": flags[:10], "flag_total": len(flags),
        "on_shift": Shift.objects.filter(clock_out__isnull=True).select_related("employee"),
        "stock_rows": stock_rows, "slow": slow,
    }
    return render(request, "reports/dashboard.html", context)


@owner_required
def anomalies(request):
    show = request.GET.get("show", "new")
    qs = Anomaly.objects.select_related("employee", "reviewed_by")
    if show == "new":
        qs = qs.filter(status=Anomaly.Status.NEW)
    elif show == "reviewed":
        qs = qs.filter(status=Anomaly.Status.REVIEWED)
    return render(request, "reports/anomalies.html", {"anomalies": qs[:200], "show": show})


@owner_required
@require_POST
def anomaly_review(request, pk):
    anomaly = get_object_or_404(Anomaly, pk=pk)
    anomaly.status = Anomaly.Status.REVIEWED
    anomaly.note = request.POST.get("note", "").strip()
    anomaly.reviewed_by = request.user
    anomaly.reviewed_at = timezone.now()
    anomaly.save()
    audit.log(request.user, "ANOMALY_REVIEWED", anomaly.message[:150], request)
    messages.success(request, "Marked as reviewed.")
    next_url = request.POST.get("next")
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return redirect(next_url)
    return redirect("reports:anomalies")