from django_ratelimit.decorators import ratelimit
from django.utils.decorators import method_decorator
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
    """Rate-limit bucket key: the real client IP.

    Production chain: Cloudflare -> Apache -> nginx -> gunicorn. Apache runs
    mod_remoteip with `RemoteIPHeader CF-Connecting-IP`, trusting only
    Cloudflare's IP ranges, which restores the true visitor IP; mod_proxy_http
    then appends that authoritative IP to X-Forwarded-For, and nginx appends
    its own upstream peer (Apache, on 127.0.0.1). So the header always ends
    with "<real client>, <nginx loopback>" and the real client is the
    second-from-last entry.

    Reading that fixed position — rather than counting a variable number of
    proxies — is why a client-forged X-Forwarded-For cannot influence the
    result: anything a client sends lands to the LEFT of Apache's authoritative
    entry, which is never at the second-from-last slot.
    """
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    chain = [part.strip() for part in forwarded.split(",") if part.strip()]
    if len(chain) >= 2:
        return chain[-2]
    return request.META.get("REMOTE_ADDR", "unknown")


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
