"""Report corpus readiness without changing any proverb record."""

from django.core.management.base import BaseCommand
from django.db.models import Count, Q

from apps.wisdom.models import Proverb
from apps.wisdom.themes import theme_vocabulary


class Command(BaseCommand):
    help = "Report verification, citation, culture, and theme coverage for the proverb corpus."

    def handle(self, *args, **options) -> None:
        self.stdout.write("Counts by verification status:")
        for status in Proverb.VerificationStatus.values:
            self.stdout.write(
                f"  {status}: {Proverb.objects.filter(verification_status=status).count()}"
            )
        missing = Proverb.objects.filter(
            Q(source_citation="") | Q(second_source_citation="")
        ).count()
        disputed = Proverb.objects.filter(
            verification_status=Proverb.VerificationStatus.DISPUTED
        ).count()
        self.stdout.write(f"Missing either citation: {missing}")
        self.stdout.write(f"Disputed: {disputed}")
        self.stdout.write("Cultures:")
        for row in (
            Proverb.objects.values("culture").annotate(count=Count("id")).order_by("culture")
        ):
            self.stdout.write(f"  {row['culture']}: {row['count']}")
        servable_themes = set()
        for proverb in Proverb.objects.servable():
            servable_themes.update(proverb.themes)
        zero_coverage = sorted(set(theme_vocabulary()) - servable_themes)
        self.stdout.write("Themes with zero servable proverbs:")
        self.stdout.write("  " + (", ".join(zero_coverage) or "none"))
