import datetime

import pytest
from django.utils import timezone

from activities.models import Activity


@pytest.fixture
def make_activity(db):
    counter = {"n": 0}

    def _make(**overrides):
        counter["n"] += 1
        defaults = {
            "title": f"Testactiviteit {counter['n']}",
            "slug": f"testactiviteit-{counter['n']}",
            "date": timezone.now().date() + datetime.timedelta(days=30),
            "is_published": True,
            "requires_registration": True,
            "capacity": None,
            "registration_opens_at": None,
            "registration_closes_at": None,
            "custom_fields": [],
        }
        defaults.update(overrides)
        return Activity.objects.create(**defaults)

    return _make


@pytest.fixture
def valid_payload():
    return {
        "name": "Piet Jansen",
        "email": "piet@example.com",
        "consent": True,
        "answers": {},
    }
