from django.test import RequestFactory

from activities.api import client_ip_key


def test_resolves_real_client_ip_through_apache_and_nginx_chain():
    """Apache's own X-Forwarded-For contribution *is* the real client IP (it's
    internet-facing with nothing spoofable in front of it); nginx appends one
    more entry (its peer, i.e. Apache's own address) on top of that."""
    request = RequestFactory().get(
        "/", HTTP_X_FORWARDED_FOR="203.0.113.9, 127.0.0.1", REMOTE_ADDR="172.19.0.5"
    )
    assert client_ip_key(None, request) == "203.0.113.9"


def test_does_not_trust_client_supplied_forged_header():
    """A client that sends its own X-Forwarded-For before hitting Apache ends
    up with 3 entries once Apache (real client) and nginx (Apache's address)
    both append theirs. That entry count doesn't match what proxy_count=1
    expects, so ipware refuses to resolve rather than trusting the attacker's
    prepended value — this must never resolve to the spoofed IP."""
    request = RequestFactory().get(
        "/",
        HTTP_X_FORWARDED_FOR="198.51.100.1, 203.0.113.9, 127.0.0.1",
        REMOTE_ADDR="172.19.0.5",
    )
    assert client_ip_key(None, request) != "198.51.100.1"
    assert client_ip_key(None, request) == "unknown"


def test_falls_back_to_unknown_without_forwarded_header():
    request = RequestFactory().get("/", REMOTE_ADDR="127.0.0.1")
    # No X-Forwarded-For at all means the header shape doesn't match
    # proxy_count=1's expectations either — falls back to "unknown" rather
    # than trusting REMOTE_ADDR (which, behind nginx, is never the real
    # client anyway).
    assert client_ip_key(None, request) == "unknown"
