import datetime

import pytest
from django.utils import timezone

from activities import services
from activities.exceptions import (
    DuplicateRegistration,
    HoneypotTriggered,
    RegistrationClosed,
    RegistrationNotAvailable,
    RegistrationValidationError,
)
from activities.models import Registration


@pytest.mark.django_db
def test_confirmed_under_capacity(make_activity, valid_payload):
    activity = make_activity(capacity=5)
    registration = services.register(activity.pk, valid_payload)
    assert registration.status == Registration.Status.CONFIRMED


@pytest.mark.django_db
def test_waitlist_at_capacity(make_activity):
    activity = make_activity(capacity=1)
    services.register(
        activity.pk, {"name": "Eerste", "email": "eerste@example.com", "consent": True}
    )
    second = services.register(
        activity.pk, {"name": "Tweede", "email": "tweede@example.com", "consent": True}
    )
    assert second.status == Registration.Status.WAITLIST


@pytest.mark.django_db
def test_unlimited_capacity_always_confirmed(make_activity):
    activity = make_activity(capacity=None)
    for i in range(10):
        r = services.register(
            activity.pk, {"name": f"Persoon {i}", "email": f"p{i}@example.com", "consent": True}
        )
        assert r.status == Registration.Status.CONFIRMED


@pytest.mark.django_db
def test_duplicate_email_rejected_case_insensitive(make_activity, valid_payload):
    activity = make_activity(capacity=5)
    services.register(activity.pk, valid_payload)

    dup_payload = {**valid_payload, "email": "PIET@Example.com"}
    with pytest.raises(DuplicateRegistration):
        services.register(activity.pk, dup_payload)


@pytest.mark.django_db
def test_reregistration_allowed_after_cancellation(make_activity, valid_payload):
    activity = make_activity(capacity=5)
    first = services.register(activity.pk, valid_payload)
    first.status = Registration.Status.CANCELLED
    first.save()

    second = services.register(activity.pk, valid_payload)
    assert second.status == Registration.Status.CONFIRMED
    assert second.pk != first.pk


@pytest.mark.django_db
def test_registration_not_yet_open(make_activity, valid_payload):
    activity = make_activity(
        registration_opens_at=timezone.now() + datetime.timedelta(days=1)
    )
    with pytest.raises(RegistrationClosed):
        services.register(activity.pk, valid_payload)


@pytest.mark.django_db
def test_registration_already_closed(make_activity, valid_payload):
    activity = make_activity(
        registration_closes_at=timezone.now() - datetime.timedelta(days=1)
    )
    with pytest.raises(RegistrationClosed):
        services.register(activity.pk, valid_payload)


@pytest.mark.django_db
def test_consent_required(make_activity):
    activity = make_activity()
    with pytest.raises(RegistrationValidationError) as exc_info:
        services.register(
            activity.pk, {"name": "Piet", "email": "piet@example.com", "consent": False}
        )
    assert "consent" in exc_info.value.errors


@pytest.mark.django_db
def test_honeypot_rejected_silently(make_activity, valid_payload):
    activity = make_activity()
    payload = {**valid_payload, "website": "http://spam.example.com"}
    with pytest.raises(HoneypotTriggered):
        services.register(activity.pk, payload)
    assert not activity.registrations.filter(email=valid_payload["email"]).exists()


@pytest.mark.django_db
def test_requires_registration_false(make_activity, valid_payload):
    activity = make_activity(requires_registration=False)
    with pytest.raises(RegistrationNotAvailable):
        services.register(activity.pk, valid_payload)


@pytest.mark.django_db
def test_external_registration_url_blocks_standard_flow(make_activity, valid_payload):
    activity = make_activity(external_registration_url="https://forms.example.com/x")
    with pytest.raises(RegistrationNotAvailable):
        services.register(activity.pk, valid_payload)


@pytest.mark.django_db
class TestCustomFieldValidation:
    def test_required_field_missing(self, make_activity, valid_payload):
        activity = make_activity(
            custom_fields=[
                {"key": "tshirt", "label": "T-shirt maat", "type": "text", "required": True}
            ]
        )
        with pytest.raises(RegistrationValidationError) as exc_info:
            services.register(activity.pk, valid_payload)
        assert "tshirt" in exc_info.value.errors

    def test_select_invalid_option(self, make_activity, valid_payload):
        activity = make_activity(
            custom_fields=[
                {
                    "key": "maat", "label": "Maat", "type": "select",
                    "required": True, "options": ["S", "M", "L"],
                }
            ]
        )
        payload = {**valid_payload, "answers": {"maat": "XXL"}}
        with pytest.raises(RegistrationValidationError) as exc_info:
            services.register(activity.pk, payload)
        assert "maat" in exc_info.value.errors

    def test_select_valid_option_accepted(self, make_activity, valid_payload):
        activity = make_activity(
            custom_fields=[
                {
                    "key": "maat", "label": "Maat", "type": "select",
                    "required": True, "options": ["S", "M", "L"],
                }
            ]
        )
        payload = {**valid_payload, "answers": {"maat": "M"}}
        registration = services.register(activity.pk, payload)
        assert registration.answers == {"maat": "M"}

    def test_number_type_rejects_non_numeric(self, make_activity, valid_payload):
        activity = make_activity(
            custom_fields=[
                {"key": "leeftijd", "label": "Leeftijd", "type": "number", "required": True}
            ]
        )
        payload = {**valid_payload, "answers": {"leeftijd": "abc"}}
        with pytest.raises(RegistrationValidationError) as exc_info:
            services.register(activity.pk, payload)
        assert "leeftijd" in exc_info.value.errors

    def test_optional_field_may_be_omitted(self, make_activity, valid_payload):
        activity = make_activity(
            custom_fields=[
                {"key": "opmerking", "label": "Opmerking", "type": "text", "required": False}
            ]
        )
        registration = services.register(activity.pk, valid_payload)
        assert registration.answers == {}

    def test_unknown_answer_keys_are_dropped(self, make_activity, valid_payload):
        activity = make_activity(
            custom_fields=[
                {"key": "maat", "label": "Maat", "type": "text", "required": False}
            ]
        )
        payload = {**valid_payload, "answers": {"maat": "M", "unexpected": "value"}}
        registration = services.register(activity.pk, payload)
        assert registration.answers == {"maat": "M"}


@pytest.mark.django_db
def test_phone_study_dietary_stripped_when_not_collected(make_activity):
    activity = make_activity(
        collect_phone=False, collect_study=False, collect_dietary=False
    )
    registration = services.register(
        activity.pk,
        {
            "name": "Piet", "email": "piet@example.com", "consent": True,
            "phone": "0612345678", "study": "Natuurkunde", "dietary": "Vegetarisch",
        },
    )
    assert registration.phone == ""
    assert registration.study == ""
    assert registration.dietary == ""
