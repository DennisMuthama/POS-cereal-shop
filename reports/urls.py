from django.urls import path

from . import views

app_name = "reports"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("anomalies/", views.anomalies, name="anomalies"),
    path("anomalies/<int:pk>/review/", views.anomaly_review, name="anomaly_review"),
]