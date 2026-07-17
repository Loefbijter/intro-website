from django.test import RequestFactory

from activities.api import client_ip_key


def _request(xff=None, remote_addr="172.19.0.5"):
    kwargs = {"REMOTE_ADDR": remote_addr}
    if xff is not None:
        kwargs["HTTP_X_FORWARDED_FOR"] = xff
    return RequestFactory().get("/", **kwargs)


def test_resolves_real_client_through_cloudflare_chain():
    """Cloudflare (via CF-Connecting-IP + mod_remoteip) makes Apache append the
    real client IP to X-Forwarded-For; nginx then appends its loopback peer. The
    real client is therefore the second-from-last entry."""
    # Cloudflare appended the client, Apache re-appended it (mod_remoteip),
    # nginx appended 127.0.0.1.
    request = _request(xff="203.0.113.9, 203.0.113.9, 127.0.0.1")
    assert client_ip_key(None, request) == "203.0.113.9"


def test_reads_apache_appended_entry_not_leftmost():
    """The entry Apache appends (second-from-last) is authoritative even when
    the leftmost entries differ (e.g. Cloudflare-relayed values)."""
    request = _request(xff="198.51.100.7, 203.0.113.9, 127.0.0.1")
    assert client_ip_key(None, request) == "203.0.113.9"


def test_client_supplied_forged_header_cannot_spoof():
    """A visitor who sends their own X-Forwarded-For only prepends entries on
    the LEFT (Cloudflare appends the true IP after them, then Apache appends it
    again, then nginx its loopback). The forged value never reaches the
    second-from-last slot, so it can't become the rate-limit key."""
    request = _request(
        xff="6.6.6.6, 203.0.113.9, 203.0.113.9, 127.0.0.1"
    )
    result = client_ip_key(None, request)
    assert result == "203.0.113.9"
    assert result != "6.6.6.6"


def test_falls_back_to_remote_addr_without_usable_chain():
    """If the forwarded chain is missing/degenerate (a misconfiguration — the
    request didn't come through the proxy chain), fall back to REMOTE_ADDR
    rather than trusting a lone, possibly client-supplied value."""
    assert client_ip_key(None, _request(xff=None, remote_addr="10.0.0.9")) == "10.0.0.9"
    assert client_ip_key(None, _request(xff="9.9.9.9", remote_addr="10.0.0.9")) == "10.0.0.9"
