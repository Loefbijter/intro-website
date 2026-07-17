import datetime

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from activities.models import Registration


@pytest.fixture
def client():
    return APIClient()


@pytest.mark.django_db
class TestActivityListEndpoint:
    @pytest.fixture(autouse=True)
    def _disable_ratelimit(self, settings):
        settings.RATELIMIT_ENABLE = False

    def test_unpublished_activities_are_hidden(self, client, make_activity):
        make_activity(is_published=True, slug="gepubliceerd")
        make_activity(is_published=False, slug="niet-gepubliceerd")

        response = client.get("/api/activities/")

        slugs = [item["slug"] for item in response.data]
        assert "gepubliceerd" in slugs
        assert "niet-gepubliceerd" not in slugs

    def test_unpublished_activity_detail_is_404(self, client, make_activity):
        make_activity(is_published=False, slug="verborgen")
        response = client.get("/api/activities/verborgen/")
        assert response.status_code == 404

    def test_image_returned_as_relative_media_url(self, client, make_activity):
        activity = make_activity(slug="met-foto")
        activity.image = "activities/zeilen.jpg"
        activity.save()
        response = client.get("/api/activities/met-foto/")
        # Relative /media/ URL, not an absolute one built from the request host
        # (which would be wrong behind the Apache->nginx->gunicorn chain).
        assert response.data["image"] == "/media/activities/zeilen.jpg"

    def test_image_is_null_when_absent(self, client, make_activity):
        make_activity(slug="zonder-foto")
        response = client.get("/api/activities/zonder-foto/")
        assert response.data["image"] is None

    def test_video_url_passthrough(self, client, make_activity):
        make_activity(slug="met-video", video_url="https://www.instagram.com/p/ABC123/")
        response = client.get("/api/activities/met-video/")
        assert response.data["video_url"] == "https://www.instagram.com/p/ABC123/"

    def test_date_can_be_null_for_tba(self, client, make_activity):
        make_activity(slug="tba", date=None)
        response = client.get("/api/activities/tba/")
        assert response.status_code == 200
        assert response.data["date"] is None

    def test_no_personal_data_in_list_response(self, client, make_activity):
        activity = make_activity()
        Registration.objects.create(
            activity=activity, name="Geheime Naam", email="geheim@example.com",
            phone="0612345678", status=Registration.Status.CONFIRMED,
        )

        response = client.get("/api/activities/")
        body = str(response.content)

        assert "Geheime Naam" not in body
        assert "geheim@example.com" not in body
        assert "0612345678" not in body

    def test_no_personal_data_in_detail_response(self, client, make_activity):
        activity = make_activity()
        Registration.objects.create(
            activity=activity, name="Geheime Naam", email="geheim@example.com",
            status=Registration.Status.CONFIRMED,
        )

        response = client.get(f"/api/activities/{activity.slug}/")
        body = str(response.content)

        assert "Geheime Naam" not in body
        assert "geheim@example.com" not in body

    def test_spots_remaining_reflects_confirmed_count(self, client, make_activity):
        activity = make_activity(capacity=2)
        Registration.objects.create(
            activity=activity, name="Piet", email="piet@example.com",
            status=Registration.Status.CONFIRMED,
        )
        response = client.get(f"/api/activities/{activity.slug}/")
        assert response.data["spots_remaining"] == 1
        assert response.data["is_full"] is False


@pytest.mark.django_db
class TestRegisterEndpoint:
    @pytest.fixture(autouse=True)
    def _disable_ratelimit(self, settings):
        settings.RATELIMIT_ENABLE = False

    def test_happy_path_confirmed(self, client, make_activity):
        activity = make_activity(capacity=5)
        response = client.post(
            f"/api/activities/{activity.slug}/register/",
            {"name": "Piet Jansen", "email": "piet@example.com", "consent": True},
            format="json",
        )
        assert response.status_code == 201
        assert response.data["status"] == "confirmed"

    def test_happy_path_waitlist(self, client, make_activity):
        activity = make_activity(capacity=1)
        Registration.objects.create(
            activity=activity, name="Eerste", email="eerste@example.com",
            status=Registration.Status.CONFIRMED,
        )
        response = client.post(
            f"/api/activities/{activity.slug}/register/",
            {"name": "Tweede", "email": "tweede@example.com", "consent": True},
            format="json",
        )
        assert response.status_code == 201
        assert response.data["status"] == "waitlist"

    def test_duplicate_email_error_in_dutch(self, client, make_activity):
        activity = make_activity(capacity=5)
        payload = {"name": "Piet", "email": "piet@example.com", "consent": True}
        client.post(f"/api/activities/{activity.slug}/register/", payload, format="json")

        response = client.post(
            f"/api/activities/{activity.slug}/register/", payload, format="json"
        )
        assert response.status_code == 409
        assert "al ingeschreven" in response.data["detail"]

    def test_registration_closed_error_in_dutch(self, client, make_activity):
        activity = make_activity(
            registration_closes_at=timezone.now() - datetime.timedelta(days=1)
        )
        response = client.post(
            f"/api/activities/{activity.slug}/register/",
            {"name": "Piet", "email": "piet@example.com", "consent": True},
            format="json",
        )
        assert response.status_code == 403
        assert "gesloten" in response.data["detail"]

    def test_missing_consent_validation_error(self, client, make_activity):
        activity = make_activity()
        response = client.post(
            f"/api/activities/{activity.slug}/register/",
            {"name": "Piet", "email": "piet@example.com", "consent": False},
            format="json",
        )
        assert response.status_code == 400

    def test_invalid_email_format_rejected(self, client, make_activity):
        activity = make_activity()
        response = client.post(
            f"/api/activities/{activity.slug}/register/",
            {"name": "Piet", "email": "not-an-email", "consent": True},
            format="json",
        )
        assert response.status_code == 400

    def test_honeypot_returns_fake_success_without_persisting(self, client, make_activity):
        activity = make_activity(capacity=5)
        response = client.post(
            f"/api/activities/{activity.slug}/register/",
            {
                "name": "Bot", "email": "bot@example.com", "consent": True,
                "website": "http://spam.example.com",
            },
            format="json",
        )
        assert response.status_code == 201
        assert not activity.registrations.filter(email="bot@example.com").exists()

    def test_unpublished_activity_register_is_404(self, client, make_activity):
        activity = make_activity(is_published=False)
        response = client.post(
            f"/api/activities/{activity.slug}/register/",
            {"name": "Piet", "email": "piet@example.com", "consent": True},
            format="json",
        )
        assert response.status_code == 404


@pytest.mark.django_db
def test_rate_limit_blocks_after_threshold(client, make_activity):
    activity = make_activity(capacity=100)
    last_response = None
    for i in range(6):
        last_response = client.post(
            f"/api/activities/{activity.slug}/register/",
            {"name": f"Persoon {i}", "email": f"p{i}@example.com", "consent": True},
            format="json",
            REMOTE_ADDR="203.0.113.5",
        )
    assert last_response.status_code == 429
