"""Refresh official sanctions snapshots outside the user request path.

Run from ``backend`` with ``python scripts/sync_sanctions_sources.py``.
The command never prints record contents; it reports provider, count, hash,
and failure state only.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domains.live_sources.http_client import close_shared_http_client
from app.domains.live_sources.sanctions_service import refresh_snapshot


async def main() -> int:
    results = []
    try:
        for provider in ("ofac", "un_sanctions", "uk_sanctions", "eu_sanctions"):
            try:
                snapshot = await refresh_snapshot(provider)
                results.append({"provider": provider, "status": "live", "records": len(snapshot.entries),
                                "sha256": snapshot.content_sha256, "fetched_at": snapshot.fetched_at})
            except Exception as exc:
                results.append({"provider": provider, "status": "failed",
                                "error": f"{type(exc).__name__}: {str(exc)[:240]}"})
    finally:
        await close_shared_http_client()
    print(json.dumps(results, indent=2))
    return 1 if any(item["status"] == "failed" for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
