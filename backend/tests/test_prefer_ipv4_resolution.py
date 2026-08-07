"""Tests for the DNS64/NAT64 resolver workaround (app/core/net_ipv4.py).

Reproduces the shape of the outage without touching the network: a resolver
that answers with both real A records and synthesized 64:ff9b::/96 AAAA
records, on a host with no route to a NAT64 gateway. Every connection
attempt to the synthesized addresses hung, and because RFC 6724 ranks
64:ff9b::/96 (under ::/0, precedence 40) above IPv4-mapped ::ffff:0:0/96
(precedence 35), they were tried first — asyncpg burned its whole connect
deadline on them and raised TimeoutError without ever reaching the IPv4
address that connects in ~0.2s.
"""
import os
import socket
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app.core.net_ipv4 as net_ipv4


V4 = [
    (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("54.64.190.72", 5432)),
    (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("35.79.125.133", 5432)),
]
# 64:ff9b::3640:be48 is literally 54.64.190.72 re-encoded (0x36=54, 0x40=64,
# 0xbe=190, 0x48=72) — the giveaway that these are DNS64 synthesis, not real
# native IPv6 endpoints.
NAT64 = [
    (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("64:ff9b::3640:be48", 5432, 0, 0)),
    (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("64:ff9b::234f:7d85", 5432, 0, 0)),
]
NATIVE_V6 = [
    (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2600:1f18::1", 5432, 0, 0)),
]


def _with_stub_resolver(answers, run):
    """Install the filter over a stub resolver, run, then restore both."""
    original = socket.getaddrinfo
    net_ipv4._installed = False
    socket.getaddrinfo = lambda *a, **k: list(answers)
    try:
        assert net_ipv4.prefer_ipv4_addresses() is True
        return run()
    finally:
        socket.getaddrinfo = original
        net_ipv4._installed = False


def test_nat64_answers_are_dropped_when_a_real_ipv4_answer_exists():
    """The outage case: without this the dead synthesized addresses are
    tried first and consume the entire connect timeout."""
    result = _with_stub_resolver(NAT64 + V4, lambda: socket.getaddrinfo("db", 5432))
    addresses = [entry[4][0] for entry in result]
    assert addresses == ["54.64.190.72", "35.79.125.133"]
    assert not any(addr.startswith("64:ff9b:") for addr in addresses)


def test_native_ipv6_is_never_touched():
    """Only 64:ff9b::/96 is filtered. A host with genuine native IPv6 must
    keep it — this workaround is about unreachable synthesis, not about
    disliking IPv6."""
    result = _with_stub_resolver(NATIVE_V6 + V4, lambda: socket.getaddrinfo("db", 5432))
    assert [entry[4][0] for entry in result] == ["2600:1f18::1", "54.64.190.72", "35.79.125.133"]


def test_nat64_only_answers_are_passed_through_untouched():
    """On a real IPv6-only host behind a working NAT64 there is no IPv4 to
    fall back to. Filtering to an empty list would turn a working lookup
    into a resolution failure, so the original answer is returned."""
    result = _with_stub_resolver(NAT64, lambda: socket.getaddrinfo("db", 5432))
    assert [entry[4][0] for entry in result] == ["64:ff9b::3640:be48", "64:ff9b::234f:7d85"]


def test_installation_is_idempotent():
    """database.py installs this at import time; repeated imports or an
    explicit second call must not stack wrappers on top of each other."""
    def _run():
        assert net_ipv4.prefer_ipv4_addresses() is False  # already installed
        assert [e[4][0] for e in socket.getaddrinfo("db", 5432)] == ["54.64.190.72", "35.79.125.133"]
        return True

    assert _with_stub_resolver(NAT64 + V4, _run) is True


def test_unparseable_addresses_do_not_break_resolution():
    """AF_UNIX / oddly-shaped sockaddrs must pass through rather than raise
    out of a patched getaddrinfo."""
    odd = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ())]
    result = _with_stub_resolver(odd + V4, lambda: socket.getaddrinfo("db", 5432))
    assert len(result) == 3


if __name__ == "__main__":
    test_nat64_answers_are_dropped_when_a_real_ipv4_answer_exists()
    test_native_ipv6_is_never_touched()
    test_nat64_only_answers_are_passed_through_untouched()
    test_installation_is_idempotent()
    test_unparseable_addresses_do_not_break_resolution()
    print("All tests passed successfully!")
