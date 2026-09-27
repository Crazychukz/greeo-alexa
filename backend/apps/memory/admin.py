from django.contrib import admin

from .models import EndUser, Follow, RecallItem, StoryEncounter, StoryUpdate


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
