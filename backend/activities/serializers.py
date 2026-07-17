from rest_framework import serializers

from . import services
from .models import Activity


class ActivitySerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()
    spots_remaining = serializers.SerializerMethodField()
    is_full = serializers.SerializerMethodField()
    registration_open = serializers.SerializerMethodField()

    class Meta:
        model = Activity
        fields = [
            "title", "slug", "date", "time_text", "theme", "location_text",
            "description", "image", "video_url", "cost_note",
            "requires_registration", "external_registration_url",
            "capacity", "registration_opens_at", "registration_closes_at",
            "collect_phone", "collect_study", "collect_dietary",
            "custom_fields",
            "spots_remaining", "is_full", "registration_open",
        ]

    def get_image(self, obj):
        # Return a relative /media/... URL (not absolute): the API is always
        # called with relative URLs and sits behind the Apache→nginx→gunicorn
        # chain, so building an absolute URL from the request host would be
        # wrong. nginx serves /media/ in prod; the Astro dev proxy forwards it
        # to Django in dev.
        return obj.image.url if obj.image else None

    def get_spots_remaining(self, obj):
        return services.spots_remaining(obj)

    def get_is_full(self, obj):
        return services.is_full(obj)

    def get_registration_open(self, obj):
        return services.registration_window_open(obj)


class RegisterSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=140)
    email = serializers.EmailField()
    phone = serializers.CharField(max_length=40, required=False, allow_blank=True)
    study = serializers.CharField(max_length=140, required=False, allow_blank=True)
    dietary = serializers.CharField(max_length=255, required=False, allow_blank=True)
    consent = serializers.BooleanField(required=False, default=False)
    website = serializers.CharField(required=False, allow_blank=True)
    answers = serializers.DictField(required=False, default=dict)
