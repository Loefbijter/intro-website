from django.db import IntegrityError, transaction
from django.utils import timezone

from .exceptions import (
    DuplicateRegistration,
    HoneypotTriggered,
    RegistrationClosed,
    RegistrationNotAvailable,
    RegistrationValidationError,
)
from .models import Activity, Registration


def registration_window_open(activity, now=None):
    now = now or timezone.now()
    if activity.registration_opens_at and now < activity.registration_opens_at:
        return False
    if activity.registration_closes_at and now > activity.registration_closes_at:
        return False
    return True


def confirmed_count(activity):
    return activity.registrations.filter(status=Registration.Status.CONFIRMED).count()


def spots_remaining(activity):
    if activity.capacity is None:
        return None
    return max(activity.capacity - confirmed_count(activity), 0)


def is_full(activity):
    remaining = spots_remaining(activity)
    return remaining is not None and remaining <= 0


def _validate_answers(custom_fields, answers):
    errors = {}
    if not isinstance(answers, dict):
        raise RegistrationValidationError({"answers": "Ongeldig antwoordformaat."})

    for field in custom_fields:
        key = field["key"]
        label = field["label"]
        field_type = field["type"]
        required = field.get("required", False)
        value = answers.get(key)
        is_empty = value is None or value == ""

        if required and is_empty:
            errors[key] = f"{label} is verplicht."
            continue
        if is_empty:
            continue

        if field_type == "select" and value not in field.get("options", []):
            errors[key] = f"Ongeldige keuze voor {label}."
        elif field_type == "checkbox" and not isinstance(value, bool):
            errors[key] = f"{label} moet aan of uit staan."
        elif field_type == "number":
            try:
                float(value)
            except (TypeError, ValueError):
                errors[key] = f"{label} moet een getal zijn."

    if errors:
        raise RegistrationValidationError(errors)

    known_keys = {field["key"] for field in custom_fields}
    return {key: value for key, value in answers.items() if key in known_keys}


def _validate(activity, payload):
    if not activity.requires_registration:
        raise RegistrationNotAvailable("Voor deze activiteit is geen inschrijving nodig.")
    if activity.external_registration_url:
        raise RegistrationNotAvailable("Voor deze activiteit wordt extern ingeschreven.")
    if not registration_window_open(activity):
        raise RegistrationClosed("Inschrijving is gesloten.")
    if payload.get("website"):
        raise HoneypotTriggered()
    if not payload.get("consent"):
        raise RegistrationValidationError(
            {"consent": "Je moet akkoord gaan met de privacyverklaring."}
        )


def register(activity_id, payload):
    with transaction.atomic():
        activity = Activity.objects.get(pk=activity_id)
        _validate(activity, payload)

        clean_answers = _validate_answers(activity.custom_fields, payload.get("answers", {}))

        email = payload["email"].strip().lower()
        if activity.registrations.exclude(status=Registration.Status.CANCELLED).filter(
            email=email
        ).exists():
            raise DuplicateRegistration(
                "Dit e-mailadres is al ingeschreven voor deze activiteit."
            )

        if activity.capacity is None:
            status = Registration.Status.CONFIRMED
        else:
            status = (
                Registration.Status.CONFIRMED
                if confirmed_count(activity) < activity.capacity
                else Registration.Status.WAITLIST
            )

        fields = {
            "name": payload["name"],
            "email": email,
            "phone": payload.get("phone", "") if activity.collect_phone else "",
            "study": payload.get("study", "") if activity.collect_study else "",
            "dietary": payload.get("dietary", "") if activity.collect_dietary else "",
            "answers": clean_answers,
            "consent": bool(payload.get("consent")),
        }
        try:
            return Registration.objects.create(activity=activity, status=status, **fields)
        except IntegrityError:
            raise DuplicateRegistration(
                "Dit e-mailadres is al ingeschreven voor deze activiteit."
            )
