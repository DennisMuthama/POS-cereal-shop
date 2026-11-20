from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET

from inventory.models import Cereal
from sales import services as sales_services

from . import audit
from .forms import ChangePasscodeForm, LoginForm
from .models import Employee

INVALID_MESSAGE = "Invalid employee ID or passcode."


def _safe_next(request):
    """Returns the ?next= address only if it points back to this site."""
    next_url = request.GET.get("next")
    if next_url and url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return next_url
    return None


def idle_screen(request):
    """The screen the shop monitor sits on between sales, with a price board for customers."""
    if request.user.is_authenticated:
        return redirect("accounts:home")

    cereals = []
    if getattr(settings, "SHOW_PRICE_BOARD", True):
        candidates = Cereal.objects.filter(is_active=True, price_per_kg__gt=0)
        cereals = [c for c in candidates if c.sellable_kg > 0][:12]
    return render(request, "accounts/idle.html", {"cereals": cereals})


def login_view(request):
    if request.user.is_authenticated:
        return redirect(_safe_next(request) or "accounts:home")

    form = LoginForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        employee_id = form.cleaned_data["employee_id"].strip().upper()
        passcode = form.cleaned_data["passcode"]

        employee = Employee.objects.filter(employee_id=employee_id).first()

        if employee is None or not employee.is_active:
            audit.log(None, "LOGIN_FAILED", f"Unknown or inactive ID: {employee_id}", request)
            messages.error(request, INVALID_MESSAGE)

        elif employee.is_locked:
            audit.log(employee, "LOGIN_BLOCKED", "Account is locked", request)
            messages.error(request, "This account is locked. Please ask the admin to unlock it.")

        else:
            user = authenticate(request, username=employee.employee_id, password=passcode)
            if user is None:
                employee.register_failed_attempt()
                audit.log(employee, "LOGIN_FAILED", f"Wrong passcode (attempt {employee.failed_attempts})", request)
                if employee.is_locked:
                    audit.log(employee, "ACCOUNT_LOCKED", "Too many failed attempts", request)
                    messages.error(request, "Too many wrong attempts. This account is now locked. Ask the admin.")
                else:
                    left = settings.MAX_FAILED_ATTEMPTS - employee.failed_attempts
                    messages.error(request, f"{INVALID_MESSAGE} {left} attempt(s) left.")
            else:
                user.reset_failed_attempts()
                login(request, user)
                audit.log(user, "LOGIN", "", request)
                return redirect(_safe_next(request) or "accounts:home")

        form = LoginForm()  # clear the fields after a failed attempt

    return render(request, "accounts/login.html", {"form": form})


def logout_view(request):
    """Log out button, browser idle timer (?reason=idle). A half-built sale is saved as Abandoned."""
    if request.user.is_authenticated:
        reason = request.GET.get("reason")
        sales_services.abandon_open_sales(
            request.user, "Idle timeout" if reason == "idle" else "Logged out mid-sale"
        )
        audit.log(request.user, "LOGOUT_IDLE" if reason == "idle" else "LOGOUT", "", request)
        logout(request)
        if reason == "idle":
            messages.warning(request, "You were logged off because of inactivity.")
    return redirect("accounts:idle")


@login_required
def home(request):
    """Sends each person to their own starting page."""
    if request.user.is_owner:
        return redirect("reports:dashboard")
    return redirect("sales:new_sale")


@login_required
def change_passcode(request):
    form = ChangePasscodeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = request.user
        user.set_password(form.cleaned_data["new_passcode"])
        user.must_change_passcode = False
        user.save()
        update_session_auth_hash(request, user)
        audit.log(user, "PASSCODE_CHANGED", "", request)
        messages.success(request, "Your passcode has been set.")
        return redirect("accounts:home")
    return render(request, "accounts/change_passcode.html", {"form": form})


@require_GET
@login_required
def ping(request):
    """Keep-alive: the browser calls this while the employee is active."""
    return HttpResponse(status=204)