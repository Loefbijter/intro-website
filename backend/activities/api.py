from django_ratelimit.decorators import ratelimit
from django.utils.decorators import method_decorator
from ipware import get_client_ip
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .exceptions import (
    DuplicateRegistration,
    HoneypotTriggered,
    RegistrationClosed,
    RegistrationNotAvailable,
    RegistrationValidationError,
)
from .models import Activity
from .serializers import ActivitySerializer, RegisterSerializer


def client_ip_key(group, request):
    # proxy_count=1, not 2, despite there being two proxies (Apache, nginx) in
    # front of gunicorn. Apache is internet-facing with nothing in front of it,
    # so the entry *it* contributes to X-Forwarded-For is already the real
    # client IP (captured from the raw TCP peer, not merely relayed from a
    # spoofable header) — there's nothing to "skip past" for that hop. Only
    # nginx's hop appends a proxy's own address (Apache's) that needs
    # discarding. Verified empirically: proxy_count=2 returns None for every
    # legitimate request (breaking rate limiting outright) and, worse, returns
    # the attacker-supplied IP when a client sends a forged X-Forwarded-For.
    ip, _ = get_client_ip(request, proxy_count=1)
    return ip or "unknown"


class ActivityListView(generics.ListAPIView):
    queryset = Activity.objects.filter(is_published=True)
    serializer_class = ActivitySerializer


class ActivityDetailView(generics.RetrieveAPIView):
    queryset = Activity.objects.filter(is_published=True)
    serializer_class = ActivitySerializer
    lookup_field = "slug"


@method_decorator(
    ratelimit(key=client_ip_key, rate="5/m", method="POST", block=False), name="post"
)
class RegisterView(APIView):
    def post(self, request, slug):
        if getattr(request, "limited", False):
            return Response(
                {"detail": "Te veel pogingen. Probeer het later opnieuw."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        try:
            activity = Activity.objects.get(slug=slug, is_published=True)
        except Activity.DoesNotExist:
            return Response(
                {"detail": "Activiteit niet gevonden."}, status=status.HTTP_404_NOT_FOUND
            )

        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            registration = services.register(activity.pk, serializer.validated_data)
        except HoneypotTriggered:
            return Response({"status": "confirmed"}, status=status.HTTP_201_CREATED)
        except DuplicateRegistration as exc:
            return Response({"detail": exc.message}, status=status.HTTP_409_CONFLICT)
        except RegistrationClosed as exc:
            return Response({"detail": exc.message}, status=status.HTTP_403_FORBIDDEN)
        except RegistrationNotAvailable as exc:
            return Response({"detail": exc.message}, status=status.HTTP_403_FORBIDDEN)
        except RegistrationValidationError as exc:
            return Response({"errors": exc.errors}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"status": registration.status}, status=status.HTTP_201_CREATED)
