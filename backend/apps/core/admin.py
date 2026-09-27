from django.contrib import admin

from .models import AuditEvent, PipelineRun, StageTrace


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("action", "target_type", "target_id", "actor", "created_at")
    list_filter = ("action", "target_type")
    search_fields = ("actor", "target_id")


@admin.register(PipelineRun)
class PipelineRunAdmin(admin.ModelAdmin):
    list_display = ("id", "status", "started_at", "finished_at")
    list_filter = ("status",)


@admin.register(StageTrace)
class StageTraceAdmin(admin.ModelAdmin):
    list_display = ("stage", "status", "attempt", "story", "run", "started_at", "duration_ms")
    list_filter = ("stage", "status", "host_mode")
    search_fields = ("stage", "error")
    readonly_fields = tuple(field.name for field in StageTrace._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
