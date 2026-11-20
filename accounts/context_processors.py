from django.conf import settings


def idle_timeout(request):
    """Values every template can use: shop name, idle limit, and the owner's new-flag count."""
    context = {"shop_name": settings.SHOP_NAME}
    user = request.user
    if user.is_authenticated:
        context["idle_seconds"] = (
            settings.OWNER_IDLE_SECONDS if user.is_owner else settings.CASHIER_IDLE_SECONDS
        )
        if user.is_owner:
            from reports.models import Anomaly

            context["new_anomaly_count"] = Anomaly.objects.filter(status=Anomaly.Status.NEW).count()
    return context