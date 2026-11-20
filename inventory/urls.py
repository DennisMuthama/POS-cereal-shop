from django.urls import path

from . import views

app_name = "inventory"

urlpatterns = [
    path("", views.batches, name="batches"),
    path("cereals/", views.cereal_list, name="cereals"),
    path("cereals/add/", views.cereal_edit, name="cereal_add"),
    path("cereals/<int:pk>/edit/", views.cereal_edit, name="cereal_edit"),
    path("receive/", views.receive_stock, name="receive_stock"),
    path("wastage/", views.wastage, name="wastage"),
    path("counts/", views.stock_counts, name="stock_counts"),
]