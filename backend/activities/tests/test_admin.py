import pytest
from django.contrib import admin as django_admin

from activities.models import Registration


class DummyRequest:
    pass


def _registration_admin():
    return django_admin.site._registry[Registration]


@pytest.mark.django_db
class TestPromoteAction:
    def test_promotes_waitlist_to_confirmed(self, make_activity):
        activity = make_activity(capacity=1)
        confirmed = Registration.objects.create(
            activity=activity, name="Eerste", email="eerste@example.com",
            status=Registration.Status.CONFIRMED,
        )
        waitlisted = Registration.objects.create(
            activity=activity, name="Tweede", email="tweede@example.com",
            status=Registration.Status.WAITLIST,
        )

        reg_admin = _registration_admin()
        reg_admin.message_user = lambda request, message, level=None: None
        reg_admin.promote_to_confirmed(
            DummyRequest(), Registration.objects.filter(pk=waitlisted.pk)
        )

        waitlisted.refresh_from_db()
        confirmed.refresh_from_db()
        assert waitlisted.status == Registration.Status.CONFIRMED
        assert confirmed.status == Registration.Status.CONFIRMED

    def test_warns_when_exceeding_capacity(self, make_activity):
        activity = make_activity(capacity=1)
        Registration.objects.create(
            activity=activity, name="Eerste", email="eerste@example.com",
            status=Registration.Status.CONFIRMED,
        )
        waitlisted = Registration.objects.create(
            activity=activity, name="Tweede", email="tweede@example.com",
            status=Registration.Status.WAITLIST,
        )

        messages = []
        reg_admin = _registration_admin()
        reg_admin.message_user = lambda request, message, level=None: messages.append(
            (message, level)
        )
        reg_admin.promote_to_confirmed(
            DummyRequest(), Registration.objects.filter(pk=waitlisted.pk)
        )

        assert any("over capaciteit" in m for m, _ in messages)


@pytest.mark.django_db
class TestCancelAction:
    def test_cancels_without_auto_promotion(self, make_activity):
        activity = make_activity(capacity=1)
        confirmed = Registration.objects.create(
            activity=activity, name="Eerste", email="eerste@example.com",
            status=Registration.Status.CONFIRMED,
        )
        waitlisted = Registration.objects.create(
            activity=activity, name="Tweede", email="tweede@example.com",
            status=Registration.Status.WAITLIST,
        )

        reg_admin = _registration_admin()
        reg_admin.message_user = lambda request, message, level=None: None
        reg_admin.cancel_registration(
            DummyRequest(), Registration.objects.filter(pk=confirmed.pk)
        )

        confirmed.refresh_from_db()
        waitlisted.refresh_from_db()
        assert confirmed.status == Registration.Status.CANCELLED
        # No auto-promotion: the waitlisted registration stays on the waitlist.
        assert waitlisted.status == Registration.Status.WAITLIST


@pytest.mark.django_db
class TestCsvExportAction:
    def test_export_includes_custom_answers(self, make_activity):
        activity = make_activity(
            custom_fields=[{"key": "maat", "label": "Maat", "type": "text", "required": False}]
        )
        Registration.objects.create(
            activity=activity, name="Piet", email="piet@example.com",
            status=Registration.Status.CONFIRMED, answers={"maat": "L"},
        )

        reg_admin = _registration_admin()
        response = reg_admin.export_as_csv(DummyRequest(), Registration.objects.all())

        content = response.content.decode()
        rows = content.splitlines()
        header = rows[0].split(",")
        assert "maat" in header
        data_row = rows[1]
        assert "piet@example.com" in data_row
        assert data_row.split(",")[header.index("maat")] == "L"
