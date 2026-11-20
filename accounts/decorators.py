from functools import wraps

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.shortcuts import redirect


def owner_required(view_func):
    """Only logged-in owners/admins may open this page."""

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not request.user.is_owner:
            messages.error(request, "That page is for the owner only.")
            return redirect("accounts:home")
        return view_func(request, *args, **kwargs)

    return wrapper