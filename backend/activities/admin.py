import csv

from django.contrib import admin, messages
from django.http import HttpResponse

from .models import Activity, Registration


class RegistrationInline(admin.TabularInline):
    model = Registration
    extra = 0
    can_delete = False
    fields = ("name", "email", "status", "created_at")
    readonly_fields = ("name", "email", "status", "created_at")
    verbose_name_plural = "inschrijvingen (overzicht)"

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Activity)
class ActivityAdmin(admin.ModelAdmin):
    list_display = (
        "title", "date", "is_published", "capacity",
        "confirmed_count", "waitlist_count",
    )
    list_filter = ("is_published", "requires_registration", "date")
    search_fields = ("title", "theme", "location_text")
    prepopulated_fields = {"slug": ("title",)}
    ordering = ("sort_order", "date")
    inlines = [RegistrationInline]

    @admin.display(description="Bevestigd")
    def confirmed_count(self, obj):
        return obj.registrations.filter(status=Registration.Status.CONFIRMED).count()

    @admin.display(description="Wachtlijst")
    def waitlist_count(self, obj):
        return obj.registrations.filter(status=Registration.Status.WAITLIST).count()


@admin.register(Registration)
class RegistrationAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "activity", "status", "created_at")
    list_filter = ("activity", "status")
    search_fields = ("name", "email")
    actions = ["promote_to_confirmed", "cancel_registration", "export_as_csv"]

    @admin.action(description="Promoot naar bevestigd")
    def promote_to_confirmed(self, request, queryset):
        promoted = 0
        for registration in queryset.filter(status=Registration.Status.WAITLIST):
            registration.status = Registration.Status.CONFIRMED
            registration.save(update_fields=["status"])
            promoted += 1

        self.message_user(request, f"{promoted} inschrijving(en) gepromoveerd naar bevestigd.")

        affected_activities = Activity.objects.filter(
            pk__in=queryset.values_list("activity_id", flat=True)
        )
        for activity in affected_activities:
            if activity.capacity is None:
                continue
            confirmed = activity.registrations.filter(status=Registration.Status.CONFIRMED).count()
            if confirmed > activity.capacity:
                self.message_user(
                    request,
                    f"Let op: \"{activity.title}\" zit nu over capaciteit "
                    f"({confirmed}/{activity.capacity} bevestigd).",
                    level=messages.WARNING,
                )

    @admin.action(description="Annuleer inschrijving")
    def cancel_registration(self, request, queryset):
        updated = queryset.exclude(status=Registration.Status.CANCELLED).update(
            status=Registration.Status.CANCELLED
        )
        self.message_user(request, f"{updated} inschrijving(en) geannuleerd.")

    @admin.action(description="Exporteer als CSV")
    def export_as_csv(self, request, queryset):
        queryset = queryset.select_related("activity")

        answer_keys = []
        seen = set()
        for registration in queryset:
            for key in registration.answers.keys():
                if key not in seen:
                    seen.add(key)
                    answer_keys.append(key)

        standard_fields = [
            "activiteit", "naam", "email", "telefoonnummer",
            "studie", "dieetwensen", "status", "toestemming", "aangemaakt_op",
        ]
        header = standard_fields + answer_keys

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="inschrijvingen.csv"'
        writer = csv.writer(response)
        writer.writerow(header)

        for registration in queryset:
            row = [
                registration.activity.title,
                registration.name,
                registration.email,
                registration.phone,
                registration.study,
                registration.dietary,
                registration.get_status_display(),
                "Ja" if registration.consent else "Nee",
                registration.created_at.isoformat(),
            ]
            row += [registration.answers.get(key, "") for key in answer_keys]
            writer.writerow(row)

        return response
