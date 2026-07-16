from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from activities.models import Registration


class Command(BaseCommand):
    help = "Verwijdert inschrijvingen die ouder zijn dan RETENTION_DAYS (privacy/GDPR-retentie)."

    def handle(self, *args, **options):
        cutoff = timezone.now() - timezone.timedelta(days=settings.RETENTION_DAYS)
        old_registrations = Registration.objects.filter(created_at__lt=cutoff)
        count = old_registrations.count()
        old_registrations.delete()
        self.stdout.write(
            self.style.SUCCESS(
                f"{count} inschrijving(en) ouder dan {settings.RETENTION_DAYS} dagen verwijderd."
            )
        )
