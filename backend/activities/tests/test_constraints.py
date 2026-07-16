import pytest
from django.db import IntegrityError, transaction

from activities.models import Registration


@pytest.mark.django_db
def test_db_rejects_duplicate_active_email_bypassing_service(make_activity):
    activity = make_activity()
    Registration.objects.create(
        activity=activity, name="Piet", email="piet@example.com",
        status=Registration.Status.CONFIRMED,
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Registration.objects.create(
                activity=activity, name="Piet Duplicate", email="piet@example.com",
                status=Registration.Status.WAITLIST,
            )


@pytest.mark.django_db
def test_db_allows_duplicate_email_when_previous_is_cancelled(make_activity):
    activity = make_activity()
    Registration.objects.create(
        activity=activity, name="Piet", email="piet@example.com",
        status=Registration.Status.CANCELLED,
    )
    registration = Registration.objects.create(
        activity=activity, name="Piet Again", email="piet@example.com",
        status=Registration.Status.CONFIRMED,
    )
    assert registration.pk is not None


@pytest.mark.django_db
def test_db_allows_same_email_across_different_activities(make_activity):
    activity_a = make_activity()
    activity_b = make_activity()
    Registration.objects.create(
        activity=activity_a, name="Piet", email="piet@example.com",
        status=Registration.Status.CONFIRMED,
    )
    registration = Registration.objects.create(
        activity=activity_b, name="Piet", email="piet@example.com",
        status=Registration.Status.CONFIRMED,
    )
    assert registration.pk is not None
