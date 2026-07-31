"""Snapshot caching and exact-name candidate lookup for official sanctions feeds."""
from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path

from app.core.config import get_settings
from app.domains.live_sources.connectors.feed_base import SanctionsFeedConnector
from app.domains.live_sources.connectors.sanctions_feeds import CSVSanctionsFeedConnector, OFACFeedConnector, UNSanctionsFeedConnector
from app.domains.live_sources.feed_schemas import SanctionsEntry, SanctionsSnapshot
from app.domains.live_sources.http_client import get_shared_http_client

settings = get_settings()

_FEEDS: dict[str, SanctionsFeedConnector] = {
    "ofac": OFACFeedConnector(settings.OFAC_SDN_XML_URL),
    "un_sanctions": UNSanctionsFeedConnector(settings.UN_SANCTIONS_XML_URL),
    "uk_sanctions": CSVSanctionsFeedConnector("uk_sanctions", settings.UK_SANCTIONS_CSV_URL,
                                               "https://www.gov.uk/government/publications/the-uk-sanctions-list", "GB"),
    "eu_sanctions": CSVSanctionsFeedConnector("eu_sanctions", settings.EU_SANCTIONS_CSV_URL,
                                               "https://finance.ec.europa.eu/eu-and-world/sanctions-restrictive-measures_en", "EU"),
}
_cache: dict[str, tuple[SanctionsSnapshot, float]] = {}
_locks: dict[str, asyncio.Lock] = {}


def _snapshot_path(provider_key: str) -> Path:
    configured = Path(settings.SANCTIONS_SNAPSHOT_DIR)
    if not configured.is_absolute():
        configured = Path(__file__).resolve().parents[3] / configured
    return configured / f"{provider_key}.json"


def _load_disk_snapshot(provider_key: str) -> SanctionsSnapshot | None:
    path = _snapshot_path(provider_key)
    if not path.is_file() or time.time() - path.stat().st_mtime > settings.SANCTIONS_SNAPSHOT_TTL_SECONDS:
        return None
    try:
        return SanctionsSnapshot.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _save_disk_snapshot(snapshot: SanctionsSnapshot) -> None:
    path = _snapshot_path(snapshot.provider_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(snapshot.model_dump_json(), encoding="utf-8")
    temporary.replace(path)


def _normal(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


async def get_snapshot(provider_key: str) -> SanctionsSnapshot:
    cached = _cache.get(provider_key)
    now = time.monotonic()
    if cached and cached[1] > now:
        return cached[0]
    disk = _load_disk_snapshot(provider_key)
    if disk is not None:
        _cache[provider_key] = (disk, now + settings.SANCTIONS_SNAPSHOT_TTL_SECONDS)
        return disk
    if not settings.SANCTIONS_ALLOW_INLINE_REFRESH:
        raise ValueError(f"{provider_key} snapshot is not warmed; run the scheduled sanctions sync")
    return await refresh_snapshot(provider_key)


async def refresh_snapshot(provider_key: str) -> SanctionsSnapshot:
    lock = _locks.setdefault(provider_key, asyncio.Lock())
    async with lock:
        cached = _cache.get(provider_key)
        if cached and cached[1] > time.monotonic():
            return cached[0]
        connector = _FEEDS.get(provider_key)
        if connector is None:
            raise ValueError(f"No sanctions feed connector for {provider_key}")
        snapshot = await connector.fetch_snapshot(timeout=max(90.0, settings.LIVE_SOURCE_HTTP_TIMEOUT_SECONDS),
                                                  max_bytes=settings.SANCTIONS_MAX_DOWNLOAD_BYTES,
                                                  client=get_shared_http_client())
        _cache[provider_key] = (snapshot, time.monotonic() + settings.SANCTIONS_SNAPSHOT_TTL_SECONDS)
        _save_disk_snapshot(snapshot)
        return snapshot


async def find_exact_candidates(provider_key: str, name: str) -> tuple[SanctionsSnapshot, list[SanctionsEntry]]:
    target = _normal(name)
    if len(target) < 3:
        raise ValueError("sanctions screening name is too short")
    snapshot = await get_snapshot(provider_key)
    matches = [entry for entry in snapshot.entries if target in {_normal(item) for item in entry.searchable_names}]
    return snapshot, matches
