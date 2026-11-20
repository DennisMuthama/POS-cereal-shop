from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse


class IdleTimeoutMiddleware:
    """
    Server-side safety net: the session dies shortly after the browser-side
    idle timer would have fired. The browser timer logs out first (so the
    logout is recorded properly); this covers a closed tab or a dead browser.
    """

    GRACE_SECONDS = 30

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if user.is_authenticated:
            seconds = settings.OWNER_IDLE_SECONDS if user.is_owner else settings.CASHIER_IDLE_SECONDS
            request.session.set_expiry(seconds + self.GRACE_SECONDS)
        return self.get_response(request)


class ForcePasscodeChangeMiddleware:
    """Employees with a temporary passcode must choose their own before doing anything else."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if user.is_authenticated and user.must_change_passcode:
            allowed = {reverse("accounts:change_passcode"), reverse("accounts:logout")}
            if request.path not in allowed and not request.path.startswith(settings.STATIC_URL):
                return redirect("accounts:change_passcode")
        return self.get_response(request)