"""Per-user listening state models."""

from __future__ import annotations

from django.db import models


class EndUser(models.Model):
    external_id = models.CharField(max_length=255, unique=True)
    display_name = models.CharField(max_length=255, blank=True)
    preferences = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.display_name or self.external_id


class StoryEncounter(models.Model):
    user = models.ForeignKey(EndUser, on_delete=models.CASCADE, related_name="encounters")
    story = models.ForeignKey("stories.Story", on_delete=models.CASCADE, related_name="encounters")
    tone_heard = models.CharField(max_length=10, blank=True)
    last_beat = models.PositiveSmallIntegerField(default=0)
    tale_completed = models.BooleanField(default=False)
    heard_at = models.DateTimeField(auto_now=True)
    saved = models.BooleanField(default=False)
    layers_explored = models.JSONField(default=list, blank=True)
    last_layer = models.CharField(max_length=20, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("user", "story"), name="unique_user_story_encounter")
        ]


class RecallItem(models.Model):
    user = models.ForeignKey(EndUser, on_delete=models.CASCADE, related_name="recall_items")
    story = models.ForeignKey(
        "stories.Story", on_delete=models.CASCADE, related_name="recall_items"
    )
    box = models.PositiveSmallIntegerField(default=1)
    due_at = models.DateTimeField(null=True, blank=True)
    last_result = models.CharField(max_length=32, blank=True)
    streak = models.PositiveSmallIntegerField(default=0)


class Follow(models.Model):
    user = models.ForeignKey(EndUser, on_delete=models.CASCADE, related_name="follows")
    story = models.ForeignKey("stories.Story", on_delete=models.CASCADE, related_name="follows")
    created_at = models.DateTimeField(auto_now_add=True)
    last_notified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("user", "story"), name="unique_user_story_follow")
        ]


class StoryUpdate(models.Model):
    story = models.ForeignKey("stories.Story", on_delete=models.CASCADE, related_name="updates")
    summary = models.CharField(max_length=300)
    articles = models.ManyToManyField("news.Article", related_name="story_updates")
    created_at = models.DateTimeField(auto_now_add=True)


class ApiToken(models.Model):
    """A demo bearer token for the simulator and local tools. Only its hash is stored.

    This is NOT Alexa+ production authentication. In production the identity comes from
    an OAuth 2.1 access token issued through account linking; see
    docs/ALEXA_ACCOUNT_LINKING.md.
    """

    user = models.ForeignKey(EndUser, on_delete=models.CASCADE, related_name="api_tokens")
    token_hash = models.CharField(max_length=64, unique=True)
    label = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked = models.BooleanField(default=False)

    def __str__(self) -> str:
        return f"{self.user} ({self.label or 'token'})"
