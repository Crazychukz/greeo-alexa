"""Verified proverb corpus models."""

from __future__ import annotations

from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.ids import proverb_id

from .managers import ProverbManager


class Proverb(models.Model):
    class VerificationStatus(models.TextChoices):
        UNVERIFIED = "unverified", "Unverified"
        SINGLE_SOURCE = "single_source", "Single source"
        VERIFIED = "verified", "Verified"
        DISPUTED = "disputed", "Disputed"

    id = models.CharField(primary_key=True, max_length=15, default=proverb_id, editable=False)
    original_text = models.TextField()
    language = models.CharField(max_length=100)
    spoken_form = models.TextField()
    translation = models.TextField(blank=True)
    meaning_note = models.TextField()
    speak_original_ok = models.BooleanField(default=False)
    culture = models.CharField(max_length=120)
    region = models.CharField(max_length=100)
    source_citation = models.TextField()
    second_source_citation = models.TextField(blank=True)
    license = models.CharField(max_length=255)
    verification_status = models.CharField(max_length=16, choices=VerificationStatus.choices)
    dispute_note = models.TextField(blank=True)
    themes = ArrayField(models.CharField(max_length=80), default=list, blank=True)
    tone_ok = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ProverbManager()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    ~Q(verification_status="verified")
                    | (Q(source_citation__gt="") & Q(second_source_citation__gt=""))
                ),
                name="verified_proverb_needs_two_citations",
            )
        ]

    def clean(self) -> None:
        if self.verification_status == self.VerificationStatus.VERIFIED:
            errors = {}
            if not self.source_citation.strip():
                errors["source_citation"] = "Verified proverbs need a first citation."
            if not self.second_source_citation.strip():
                errors["second_source_citation"] = "Verified proverbs need a second citation."
            if errors:
                raise ValidationError(errors)

    def __str__(self) -> str:
        return f"{self.culture}: {self.spoken_form[:60]}"
