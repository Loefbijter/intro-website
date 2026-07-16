import datetime

import pytest
from django.core.management import call_command
from django.utils import timezone

from activities.models import Registration


@pytest.mark.django_db
def test_purge_deletes_registrations_older_than_retention(make_activity, settings):
    settings.RETENTION_DAYS = 30
    activity = make_activity()

    old = Registration.objects.create(
        activity=activity, name="Oud", email="oud@example.com",
        status=Registration.Status.CONFIRMED,
    )
    Registration.objects.filter(pk=old.pk).update(
        created_at=timezone.now() - datetime.timedelta(days=31)
    )

    recent = Registration.objects.create(
        activity=activity, name="Recent", email="recent@example.com",
        status=Registration.Status.CONFIRMED,
    )

    call_command("purge_old_registrations")

    assert not Registration.objects.filter(pk=old.pk).exists()
    assert Registration.objects.filter(pk=recent.pk).exists()


@pytest.mark.django_db
def test_purge_deletes_regardless_of_status(make_activity, settings):
    settings.RETENTION_DAYS = 30
    activity = make_activity()

    for status in Registration.Status.values:
        reg = Registration.objects.create(
            activity=activity, name=status, email=f"{status}@example.com", status=status,
        )
        Registration.objects.filter(pk=reg.pk).update(
            created_at=timezone.now() - datetime.timedelta(days=31)
        )

    call_command("purge_old_registrations")

    assert Registration.objects.count() == 0


@pytest.mark.django_db
def test_purge_respects_boundary_exactly_at_retention_days(make_activity, settings):
    settings.RETENTION_DAYS = 30
    activity = make_activity()

    just_inside = Registration.objects.create(
        activity=activity, name="Net binnen", email="netbinnen@example.com",
        status=Registration.Status.CONFIRMED,
    )
    Registration.objects.filter(pk=just_inside.pk).update(
        created_at=timezone.now() - datetime.timedelta(days=29, hours=23)
    )

    call_command("purge_old_registrations")

    assert Registration.objects.filter(pk=just_inside.pk).exists()
