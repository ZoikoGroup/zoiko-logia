"""Snapshot caching and exact-name candidate lookup for official sanctions feeds."""
from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from app.core.config import get_settings
from app.domains.live_sources.connectors.feed_base import SanctionsFeedConnector
from app.domains.live_sources.connectors.sanctions_feeds import CSVSanctionsFeedConnector, OFACFeedConnector, UNSanctionsFeedConnector
from app.domains.live_sources.feed_schemas import SanctionsEntry, SanctionsMatch, SanctionsSnapshot
from app.domains.live_sources.http_client import get_shared_http_client

settings = get_settings()

_FEEDS: dict[str, SanctionsFeedConnector] = {
    "ofac": OFACFeedConnector(settings.OFAC_SDN_XML_URL, settings.OFAC_SDN_XML_FALLBACK_URLS),
    "un_sanctions": UNSanctionsFeedConnector(settings.UN_SANCTIONS_XML_URL, settings.UN_SANCTIONS_XML_FALLBACK_URLS),
    "uk_sanctions": CSVSanctionsFeedConnector("uk_sanctions", settings.UK_SANCTIONS_CSV_URL,
                                               "https://www.gov.uk/government/publications/the-uk-sanctions-list", "GB",
                                               settings.UK_SANCTIONS_CSV_FALLBACK_URLS),
    "eu_sanctions": CSVSanctionsFeedConnector("eu_sanctions", settings.EU_SANCTIONS_CSV_URL,
                                               "https://finance.ec.europa.eu/eu-and-world/sanctions-restrictive-measures_en", "EU",
                                               settings.EU_SANCTIONS_CSV_FALLBACK_URLS),
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


def _tokens(value: str) -> frozenset[str]:
    return frozenset(_normal(value).split())


@dataclass(frozen=True)
class _NameIndex:
    """Per-snapshot lookup structures, built once and reused for every
    screening query against that exact list version.

    Exact matching alone (the original implementation) misses every real
    listing whose stored form differs from what a user types by so much as a
    transliteration or a title, so a fuzzy tier is required. Fuzzy matching
    over tens of thousands of names is far too slow to run per request as a
    plain scan, so candidates are first narrowed by shared token — a name
    with no token in common with the query is not a near-miss under any
    similarity measure worth using here. That reduces the expensive
    comparison to a handful of entries instead of the whole list.
    """
    entries: tuple[SanctionsEntry, ...]
    # normalised name -> indices of entries carrying that exact name
    by_exact_name: dict[str, tuple[int, ...]]
    # normalised token -> indices of entries with that token in any name
    by_token: dict[str, tuple[int, ...]]


_indexes: dict[str, _NameIndex] = {}


def _build_index(snapshot: SanctionsSnapshot) -> _NameIndex:
    exact: dict[str, list[int]] = {}
    tokens: dict[str, list[int]] = {}
    for position, entry in enumerate(snapshot.entries):
        for name in entry.searchable_names:
            normalized = _normal(name)
            if not normalized:
                continue
            exact.setdefault(normalized, []).append(position)
            for token in normalized.split():
                tokens.setdefault(token, []).append(position)
    return _NameIndex(
        entries=tuple(snapshot.entries),
        by_exact_name={key: tuple(dict.fromkeys(value)) for key, value in exact.items()},
        by_token={key: tuple(dict.fromkeys(value)) for key, value in tokens.items()},
    )


def _get_index(snapshot: SanctionsSnapshot) -> _NameIndex:
    # Keyed by content hash, not provider: a refreshed list is a different
    # list, and reusing the previous index would screen against superseded
    # contents while reporting the new version.
    key = f"{snapshot.provider_key}:{snapshot.content_sha256}"
    index = _indexes.get(key)
    if index is None:
        index = _build_index(snapshot)
        # One index per provider at a time; the previous version's is dead
        # weight the moment a new snapshot lands.
        for stale in [k for k in _indexes if k.startswith(f"{snapshot.provider_key}:")]:
            del _indexes[stale]
        _indexes[key] = index
    return index


def _match_for_entry(entry: SanctionsEntry, target: str, target_tokens: frozenset[str],
                     threshold: float) -> SanctionsMatch | None:
    """Best candidate this entry can offer for the target name, or None."""
    best: SanctionsMatch | None = None
    for name in entry.searchable_names:
        normalized = _normal(name)
        if not normalized:
            continue
        if normalized == target:
            method = "exact_primary_name" if name == entry.primary_name else "exact_alias"
            return SanctionsMatch(entry=entry, method=method, score=1.0, matched_name=name)
        # Token containment first: "Vladimir Putin" against "Putin,
        # Vladimir Vladimirovich" is a strong candidate that a raw character
        # ratio scores poorly because of the extra patronymic.
        candidate_tokens = frozenset(normalized.split())
        overlap = len(target_tokens & candidate_tokens) / max(len(target_tokens), 1)
        ratio = SequenceMatcher(None, target, normalized).ratio()
        score = max(ratio, overlap if target_tokens <= candidate_tokens else 0.0)
        if score >= threshold and (best is None or score > best.score):
            best = SanctionsMatch(entry=entry, method="fuzzy_name", score=round(score, 4), matched_name=name)
    return best


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


async def find_candidates(
    provider_key: str, name: str, *, limit: int = 10,
) -> tuple[SanctionsSnapshot, list[SanctionsMatch]]:
    """Screening candidates for `name`, best first.

    Never a decision. Every result is a candidate for human review, and the
    caller is responsible for saying so — a returned match is not a finding
    of sanctions exposure, and an empty list is not clearance.
    """
    target = _normal(name)
    if len(target) < 3:
        raise ValueError("sanctions screening name is too short")
    snapshot = await get_snapshot(provider_key)
    index = _get_index(snapshot)
    threshold = settings.SANCTIONS_FUZZY_MATCH_THRESHOLD
    target_tokens = frozenset(target.split())

    considered = set(index.by_exact_name.get(target, ()))
    for token in target_tokens:
        considered.update(index.by_token.get(token, ()))

    matches = [
        match for match in (
            _match_for_entry(index.entries[position], target, target_tokens, threshold)
            for position in sorted(considered)
        ) if match is not None
    ]
    # Exact before fuzzy at equal score, then by record id so a repeat
    # screening of the same name against the same list version returns the
    # same order — an audit record that reshuffles is not reproducible.
    matches.sort(key=lambda item: (-item.score, item.method != "exact_primary_name", item.entry.record_id))
    return snapshot, matches[:limit]
