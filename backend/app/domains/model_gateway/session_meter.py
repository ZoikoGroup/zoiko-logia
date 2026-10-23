"""Process-wide token meter for the isolated manual-test server only.

Installed by scripts/run_manual_test_server.py; never by the application.
Every Groq chat completion in the process (adapter, agent, auxiliary and
classifier calls all end here) reserves against the session's allowance
before it is sent (app/core/manual_test_server.py SessionLimits) and is
settled with the provider's reported usage, or the reservation when none.
"""
from __future__ import annotations

import functools


def _total_tokens(response) -> int | None:
    total = getattr(getattr(response, "usage", None), "total_tokens", None)
    return total if isinstance(total, int) else None


def install_groq_meter(limits):
    """Meter every Groq chat completion. Returns an uninstall function."""
    from groq.resources.chat import completions as module

    sync_create, async_create = module.Completions.create, module.AsyncCompletions.create

    @functools.wraps(async_create)
    async def metered_async(self, *args, **kwargs):
        reservation = limits.reserve(kwargs)
        used = None
        try:
            response = await async_create(self, *args, **kwargs)
            used = _total_tokens(response)
            return response
        finally:
            limits.settle(reservation, used)

    @functools.wraps(sync_create)
    def metered_sync(self, *args, **kwargs):
        reservation = limits.reserve(kwargs)
        used = None
        try:
            response = sync_create(self, *args, **kwargs)
            used = _total_tokens(response)
            return response
        finally:
            limits.settle(reservation, used)

    module.Completions.create = metered_sync
    module.AsyncCompletions.create = metered_async

    def uninstall():
        module.Completions.create = sync_create
        module.AsyncCompletions.create = async_create
    return uninstall
