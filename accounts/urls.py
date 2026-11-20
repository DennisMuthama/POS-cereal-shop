from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("", views.idle_screen, name="idle"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("home/", views.home, name="home"),
    path("change-passcode/", views.change_passcode, name="change_passcode"),
    path("ping/", views.ping, name="ping"),
]