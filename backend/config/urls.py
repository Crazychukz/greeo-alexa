"""URL configuration for the Django web service."""

from apps.core.views import healthz
from django.contrib import admin
from django.urls import path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz", healthz, name="healthz"),
]
