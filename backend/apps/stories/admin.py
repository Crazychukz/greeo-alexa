from django.contrib import admin

from .models import (
    Story,
    StoryContext,
    StoryFact,
    StoryPerspective,
    StoryTelling,
    TellingBeat,
    TellingProverb,
)


@admin.register(Story)
class StoryAdmin(admin.ModelAdmin):
    list_display = ("id", "handle", "status", "tone_class", "is_synthetic", "published_at")
    list_filter = ("status", "tone_class", "is_synthetic", "region")
    search_fields = ("id", "handle", "cluster_key")


@admin.register(StoryFact, StoryContext, StoryPerspective)
class EvidenceLayerAdmin(admin.ModelAdmin):
    list_display = ("story", "order")
    list_filter = ("story__status",)
    search_fields = ("story__handle",)


@admin.register(StoryTelling)
class StoryTellingAdmin(admin.ModelAdmin):
    list_display = ("story", "tone", "status", "closing_kind", "is_curated", "revision_count")
    list_filter = ("tone", "status", "closing_kind", "is_curated")
    search_fields = ("story__handle", "moral")


@admin.register(TellingBeat)
class TellingBeatAdmin(admin.ModelAdmin):
    list_display = ("telling", "order")
    search_fields = ("telling__story__handle", "text_template")


@admin.register(TellingProverb)
class TellingProverbAdmin(admin.ModelAdmin):
    list_display = ("telling", "slot", "role", "proverb")
    list_filter = ("role",)
    search_fields = ("telling__story__handle", "proverb__spoken_form")
