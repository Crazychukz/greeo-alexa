from django.contrib import admin

from .models import Article, FetchLog, SourceFeed


@admin.register(SourceFeed)
class SourceFeedAdmin(admin.ModelAdmin):
    list_display = ("name", "region", "language", "active", "use_policy", "circuit_state")
    list_filter = ("active", "use_policy", "circuit_state", "region")
    search_fields = ("name", "feed_url")


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ("title", "source", "evidence_kind", "published_at", "cluster_key")
    list_filter = ("evidence_kind", "language", "source")
    search_fields = ("title", "url_clean", "cluster_key")


@admin.register(FetchLog)
class FetchLogAdmin(admin.ModelAdmin):
    list_display = ("source", "outcome", "status_code", "requested_at", "latency_ms")
    list_filter = ("outcome", "source")
    search_fields = ("error",)
