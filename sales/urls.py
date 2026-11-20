from django.urls import path

from . import views

app_name = "sales"

urlpatterns = [
    path("new/", views.new_sale, name="new_sale"),
    path("add-item/", views.add_item, name="add_item"),
    path("remove-item/<int:pk>/", views.remove_item, name="remove_item"),
    path("pay/", views.pay, name="pay"),
    path("receipt/done/", views.receipt_done, name="receipt_done"),
    path("receipt/clear/", views.receipt_clear, name="receipt_clear"),
    path("receipts/", views.receipts, name="receipts"),
    path("receipts/<int:pk>/", views.receipt_detail, name="receipt_detail"),
    path("receipts/<int:pk>/void/", views.void_sale, name="void_sale"),
    path("clock/", views.clock, name="clock"),
    path("shifts/", views.shifts, name="shifts"),
    path("shifts/<int:pk>/close/", views.force_close_shift, name="force_close_shift"),
]