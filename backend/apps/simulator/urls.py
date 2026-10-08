"""Routes for the simulator host API."""

from django.urls import path

from . import views

urlpatterns = [
    path("turn", views.turn, name="simulator-turn"),
    path("reset", views.reset, name="simulator-reset"),
    path("resource", views.resource, name="simulator-resource"),
    path("tts", views.tts, name="simulator-tts"),
    path("stories", views.stories, name="simulator-stories"),
]
