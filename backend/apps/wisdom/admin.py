from django.contrib import admin, messages

from .models import Proverb


@admin.register(Proverb)
class ProverbAdmin(admin.ModelAdmin):
    list_display = ("id", "culture", "spoken_form", "verification_status", "tone_ok", "created_at")
    list_filter = ("verification_status", "tone_ok", "culture", "region")
    search_fields = ("id", "original_text", "spoken_form", "culture")
    actions = ("mark_as_verified",)

    @admin.action(description="Mark selected proverbs as verified")
    def mark_as_verified(self, request, queryset):
        verified = 0
        refused = 0
        for proverb in queryset:
            if proverb.source_citation.strip() and proverb.second_source_citation.strip():
                proverb.verification_status = Proverb.VerificationStatus.VERIFIED
                proverb.full_clean()
                proverb.save(update_fields=["verification_status"])
                verified += 1
            else:
                refused += 1
        if verified:
            self.message_user(request, f"Verified {verified} proverb(s).", messages.SUCCESS)
        if refused:
            self.message_user(
                request,
                f"Refused {refused} proverb(s) without two citations.",
                messages.ERROR,
            )
