from django.contrib import admin

from .models import LLMCall


@admin.register(LLMCall)
class LLMCallAdmin(admin.ModelAdmin):
    list_display = ("prompt_name", "prompt_version", "model", "backend", "ok", "created_at")
    list_filter = ("backend", "ok", "prompt_name")
    search_fields = ("prompt_name", "model", "story__handle", "error")
