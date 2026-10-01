from django.contrib import admin

from .models import ApiToken, EndUser, Follow, RecallItem, StoryEncounter, StoryUpdate


@admin.register(EndUser)
class EndUserAdmin(admin.ModelAdmin):
    list_display = ("external_id", "display_name", "created_at")
    search_fields = ("external_id", "display_name")


@admin.register(StoryEncounter)
class StoryEncounterAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "story",
        "tone_heard",
        "last_beat",
        "tale_completed",
        "saved",
        "heard_at",
    )
    list_filter = ("tone_heard", "tale_completed", "saved")
    search_fields = ("user__external_id", "story__handle")


@admin.register(RecallItem)
class RecallItemAdmin(admin.ModelAdmin):
    list_display = ("user", "story", "box", "due_at", "streak")


@admin.register(Follow)
class FollowAdmin(admin.ModelAdmin):
    list_display = ("user", "story", "created_at", "last_notified_at")


@admin.register(StoryUpdate)
class StoryUpdateAdmin(admin.ModelAdmin):
    list_display = ("story", "summary", "created_at")
    search_fields = ("story__handle", "summary")


@admin.register(ApiToken)
class ApiTokenAdmin(admin.ModelAdmin):
    """Tokens can be revoked here. The hash is shown only so records can be told apart."""

    list_display = ("user", "label", "revoked", "created_at", "last_used_at")
    list_filter = ("revoked",)
    search_fields = ("user__external_id", "label")
    readonly_fields = ("user", "token_hash", "created_at", "last_used_at")

    def has_add_permission(self, request):
        return False
