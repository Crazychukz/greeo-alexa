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


class FactInline(admin.StackedInline):
    model = StoryFact
    extra = 0
    filter_horizontal = ("articles",)


class ContextInline(admin.StackedInline):
    model = StoryContext
    extra = 0
    filter_horizontal = ("articles",)


class PerspectiveInline(admin.StackedInline):
    model = StoryPerspective
    extra = 0
    filter_horizontal = ("articles",)


class TellingInline(admin.TabularInline):
    """Links to each telling; beats and proverbs are edited on the telling page."""

    model = StoryTelling
    extra = 0
    fields = ("tone", "status", "closing_kind", "moral", "is_curated")
    show_change_link = True


@admin.register(Story)
class StoryAdmin(admin.ModelAdmin):
    list_display = ("id", "handle", "status", "tone_class", "is_synthetic", "published_at")
    list_filter = ("status", "tone_class", "is_synthetic", "region")
    search_fields = ("id", "handle", "cluster_key")
    inlines = (FactInline, ContextInline, PerspectiveInline, TellingInline)


@admin.register(StoryFact, StoryContext, StoryPerspective)
class EvidenceLayerAdmin(admin.ModelAdmin):
    list_display = ("story", "order")
    list_filter = ("story__status",)
    search_fields = ("story__handle",)


class BeatInline(admin.StackedInline):
    model = TellingBeat
    extra = 0


class TellingProverbInline(admin.TabularInline):
    model = TellingProverb
    extra = 0
    autocomplete_fields = ("proverb",)


@admin.register(StoryTelling)
class StoryTellingAdmin(admin.ModelAdmin):
    list_display = (
        "story",
        "tone",
        "voice_style",
        "status",
        "closing_kind",
        "is_curated",
        "revision_count",
    )
    list_filter = ("tone", "status", "closing_kind", "is_curated")
    search_fields = ("story__handle", "moral")
    inlines = (BeatInline, TellingProverbInline)


@admin.register(TellingBeat)
class TellingBeatAdmin(admin.ModelAdmin):
    list_display = ("telling", "order")
    search_fields = ("telling__story__handle", "text_template")


@admin.register(TellingProverb)
class TellingProverbAdmin(admin.ModelAdmin):
    list_display = ("telling", "slot", "role", "proverb")
    list_filter = ("role",)
    search_fields = ("telling__story__handle", "proverb__spoken_form")
