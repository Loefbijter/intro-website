from django.core.exceptions import ValidationError
from django.db import models

CUSTOM_FIELD_TYPES = {"text", "textarea", "select", "checkbox", "number"}


def validate_custom_fields(value):
    if not isinstance(value, list):
        raise ValidationError("Aangepaste velden moeten een lijst zijn.")

    seen_keys = set()
    for i, field in enumerate(value):
        if not isinstance(field, dict):
            raise ValidationError(f"Veld {i + 1}: moet een object zijn.")

        key = field.get("key")
        label = field.get("label")
        field_type = field.get("type")

        if not key or not isinstance(key, str):
            raise ValidationError(f"Veld {i + 1}: 'key' is verplicht en moet tekst zijn.")
        if key in seen_keys:
            raise ValidationError(f"Veld {i + 1}: dubbele key '{key}'.")
        seen_keys.add(key)

        if not label or not isinstance(label, str):
            raise ValidationError(f"Veld {i + 1} ({key}): 'label' is verplicht en moet tekst zijn.")

        if field_type not in CUSTOM_FIELD_TYPES:
            raise ValidationError(
                f"Veld {i + 1} ({key}): 'type' moet een van de volgende zijn: "
                f"{', '.join(sorted(CUSTOM_FIELD_TYPES))}."
            )

        if "required" in field and not isinstance(field["required"], bool):
            raise ValidationError(f"Veld {i + 1} ({key}): 'required' moet true of false zijn.")

        if field_type == "select":
            options = field.get("options")
            if not isinstance(options, list) or not options:
                raise ValidationError(
                    f"Veld {i + 1} ({key}): 'options' is verplicht en moet een niet-lege lijst zijn "
                    "voor het type 'select'."
                )
            if not all(isinstance(o, str) for o in options):
                raise ValidationError(f"Veld {i + 1} ({key}): alle 'options' moeten tekst zijn.")


class Activity(models.Model):
    title = models.CharField("titel", max_length=140)
    slug = models.SlugField("slug", unique=True)
    date = models.DateField(
        "datum", null=True, blank=True,
        help_text="Leeg laten voor een 'nog aan te kondigen' activiteit.",
    )
    time_text = models.CharField(
        "tijd", max_length=120, blank=True,
        help_text="Bijv. \"21:00\" of \"12:00–18:00, BBQ 18:00\"",
    )
    theme = models.CharField(
        "thema", max_length=120, blank=True,
        help_text="Bijv. \"Piraten & Zeemeerminnen\"",
    )
    location_text = models.CharField(
        "locatie", max_length=140, blank=True,
        help_text="Bijv. \"Het Bastion\" of \"Villa van Schaeck\"",
    )
    description = models.TextField("beschrijving", blank=True, help_text="Markdown toegestaan.")
    image = models.ImageField("afbeelding", upload_to="activities/", blank=True)
    video_url = models.URLField(
        "promotievideo", blank=True,
        help_text="Instagram- of YouTube-link; wordt als video op de kaart getoond.",
    )
    cost_note = models.CharField(
        "kosten", max_length=120, blank=True,
        help_text="Betaling ter plekke, dit is alleen een opmerking.",
    )

    requires_registration = models.BooleanField(
        "inschrijving vereist", default=True,
        help_text="Uit = \"kom gewoon langs\", geen inschrijfformulier.",
    )
    external_registration_url = models.URLField(
        "externe inschrijflink", blank=True,
        help_text="Bijv. een bestaand Google Form of WAZ-link.",
    )
    capacity = models.PositiveIntegerField(
        "capaciteit", null=True, blank=True, help_text="Leeg = onbeperkt.",
    )
    registration_opens_at = models.DateTimeField("inschrijving opent", null=True, blank=True)
    registration_closes_at = models.DateTimeField("inschrijving sluit", null=True, blank=True)

    collect_phone = models.BooleanField("telefoonnummer vragen", default=True)
    collect_study = models.BooleanField("studie vragen", default=True)
    collect_dietary = models.BooleanField(
        "dieetwensen vragen", default=True,
        help_text="Wordt alleen gevraagd t.b.v. de catering.",
    )

    custom_fields = models.JSONField(
        "aangepaste velden", default=list, blank=True,
        validators=[validate_custom_fields],
        help_text=(
            'Lijst met velden, bijv.: '
            '[{"key": "tshirt_maat", "label": "T-shirt maat", "type": "select", '
            '"required": false, "options": ["S", "M", "L", "XL"]}]. '
            'type is een van: text, textarea, select, checkbox, number.'
        ),
    )

    is_published = models.BooleanField("gepubliceerd", default=False)
    sort_order = models.IntegerField("volgorde", default=0)

    class Meta:
        verbose_name = "activiteit"
        verbose_name_plural = "activiteiten"
        ordering = ["sort_order", "date"]

    def __str__(self):
        return self.title

    def clean(self):
        super().clean()
        validate_custom_fields(self.custom_fields)


class Registration(models.Model):
    class Status(models.TextChoices):
        CONFIRMED = "confirmed", "Bevestigd"
        WAITLIST = "waitlist", "Wachtlijst"
        CANCELLED = "cancelled", "Geannuleerd"

    activity = models.ForeignKey(
        Activity, related_name="registrations", on_delete=models.CASCADE,
        verbose_name="activiteit",
    )
    name = models.CharField("naam", max_length=140)
    email = models.EmailField("e-mailadres")
    phone = models.CharField("telefoonnummer", max_length=40, blank=True)
    study = models.CharField("studie", max_length=140, blank=True)
    dietary = models.CharField("dieetwensen", max_length=255, blank=True)
    answers = models.JSONField(
        "antwoorden aangepaste velden", default=dict, blank=True,
    )
    status = models.CharField("status", max_length=12, choices=Status.choices)
    consent = models.BooleanField("toestemming gegeven", default=False)
    created_at = models.DateTimeField("aangemaakt op", auto_now_add=True)

    class Meta:
        verbose_name = "inschrijving"
        verbose_name_plural = "inschrijvingen"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["activity", "email"],
                condition=~models.Q(status="cancelled"),
                name="uniq_active_email_per_activity",
            ),
        ]

    def __str__(self):
        return f"{self.name} <{self.email}> — {self.activity}"

    def save(self, *args, **kwargs):
        self.email = self.email.strip().lower()
        super().save(*args, **kwargs)
