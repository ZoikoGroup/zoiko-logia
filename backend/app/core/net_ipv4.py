"""Work around DNS64/NAT64 resolvers on networks with no working NAT64 gateway.

Some resolvers (corporate VPNs, mobile tethering, certain ISPs) answer AAAA
queries with *synthesized* IPv6 addresses in the NAT64 well-known prefix
64:ff9b::/96 — the low 32 bits are just an IPv4 address re-encoded. On a host
that has no route to a NAT64 gateway, every connection to one of those
addresses hangs until it times out rather than failing fast.

RFC 6724's default address-selection policy makes this worse: 64:ff9b::/96
is not in the policy table, so it falls under ::/0 at precedence 40, which
outranks IPv4-mapped ::ffff:0:0/96 at precedence 35. The synthesized (dead)
IPv6 addresses are therefore tried *first*, and a client with an overall
connect deadline can burn the whole budget on them and never reach the IPv4
address that would have worked instantly.

Observed against the Supabase pooler: all three AAAA answers decoded to the
same three A-record addresses, each IPv6 attempt timed out, the IPv4 address
connected in ~0.2s, and asyncpg raised TimeoutError before ever trying it.

Installing this filter is OPT-IN (DB_PREFER_IPV4) and deliberately so: on a
genuinely IPv6-only host behind a *working* NAT64, the A records are present
in DNS but unroutable, and preferring them would break connectivity that
currently works. Enable it only on hosts that have real IPv4 connectivity.

Patching socket.getaddrinfo rather than any one client is intentional — the
same stall hits every outbound connection (asyncpg, psycopg2, httpx to live
sources, Supabase auth), and they do not share a resolver hook.
"""
from __future__ import annotations

import ipaddress
import socket

# The NAT64 well-known prefix (RFC 6052 §2.1).
_NAT64_PREFIX = ipaddress.ip_network("64:ff9b::/96")

_installed = False


def _is_nat64(sockaddr: tuple) -> bool:
    try:
        return ipaddress.ip_address(sockaddr[0]) in _NAT64_PREFIX
    except (ValueError, IndexError, TypeError):
        return False


def prefer_ipv4_addresses() -> bool:
    """Drop NAT64-synthesized answers when a real IPv4 answer is also present.

    Returns True if the filter was installed by this call, False if it was
    already installed. Idempotent, so repeated imports cannot stack wrappers.

    Only ever *removes* 64:ff9b::/96 entries, and only when the same lookup
    also produced at least one AF_INET result — so a host with genuine native
    IPv6 (2000::/3 etc.) is completely unaffected, and a lookup that returns
    nothing but NAT64 addresses is passed through untouched rather than
    turned into an empty result.
    """
    global _installed
    if _installed:
        return False

    original_getaddrinfo = socket.getaddrinfo

    def getaddrinfo_preferring_ipv4(*args, **kwargs):
        results = original_getaddrinfo(*args, **kwargs)
        if not any(family == socket.AF_INET for family, *_ in results):
            return results
        filtered = [entry for entry in results if not _is_nat64(entry[4])]
        # Never hand back an empty list: if filtering removed everything the
        # caller is better served by the original answer and a real error.
        return filtered or results

    socket.getaddrinfo = getaddrinfo_preferring_ipv4
    _installed = True
    return True
