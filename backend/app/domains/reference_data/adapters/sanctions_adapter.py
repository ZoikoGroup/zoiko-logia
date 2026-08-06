"""
UN and UK consolidated sanctions list adapter — read-only wrapper around two
public, no-auth, single-file list downloads (not per-query search APIs):
  - UN Security Council Consolidated List (XML, individuals + entities)
  - UK Sanctions List (FCDO, CSV, individuals + entities)

Both lists are large (UN ~2MB, UK ~50MB) and slow-moving (updated at most
daily), so this module downloads and parses each into an in-process name
index ONCE per SANCTIONS_SNAPSHOT_TTL_SECONDS window, then serves every
screening query against that cached snapshot rather than re-downloading
per query. SANCTIONS_MAX_DOWNLOAD_BYTES is a hard ceiling on each download
(via a streaming byte-count check) — a public list growing unexpectedly
large must never silently balloon memory/bandwidth per request.

Screening is deliberately conservative: a name "matches" only when every
significant word in the query name (2+ characters, punctuation stripped)
appears somewhere in a listed name or one of its aliases — never a fuzzy/
probabilistic match that could manufacture false confidence in either
direction for a compliance-sensitive lookup.

Nothing outside app/domains/reference_data/ should import this module
directly — see service.py for the audit-logged, cached entry point.
"""
from __future__ import annotations

import csv
import io
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import httpx

from app.core.config import get_settings

_REQUEST_TIMEOUT_SECONDS = 60.0
_WORD_PATTERN = re.compile(r"[A-Za-z0-9]+")


class SanctionsAPIError(Exception):
    """Safe wrapper for configuration, transport, parsing, and size-limit failures."""


@dataclass(frozen=True)
class SanctionsEntry:
    list_source: str  # "UN" or "UK"
    reference_id: str
    name: str
    entry_type: str  # "Individual" or "Entity"
    aliases: tuple[str, ...] = ()

    def searchable_names(self) -> tuple[str, ...]:
        return (self.name,) + self.aliases


async def _download(url: str) -> bytes:
    max_bytes = get_settings().SANCTIONS_MAX_DOWNLOAD_BYTES
    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
            async with client.stream("GET", url, follow_redirects=True) as response:
                if response.status_code != 200:
                    raise SanctionsAPIError(f"Sanctions list download returned status {response.status_code}: {url}")
                chunks = []
                total = 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise SanctionsAPIError(f"Sanctions list at {url} exceeded the {max_bytes}-byte download limit")
                    chunks.append(chunk)
                return b"".join(chunks)
    except httpx.TimeoutException as exc:
        raise SanctionsAPIError(f"Sanctions list download timed out after {_REQUEST_TIMEOUT_SECONDS}s: {url}") from exc
    except httpx.HTTPError as exc:
        raise SanctionsAPIError(f"Sanctions list download failed: {exc}") from exc


def _parse_un_xml(raw: bytes) -> list[SanctionsEntry]:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise SanctionsAPIError(f"UN sanctions list returned unparseable XML: {exc}") from exc

    entries: list[SanctionsEntry] = []
    for individual in root.findall(".//INDIVIDUALS/INDIVIDUAL"):
        name_parts = [
            (individual.findtext(tag) or "").strip()
            for tag in ("FIRST_NAME", "SECOND_NAME", "THIRD_NAME", "FOURTH_NAME")
        ]
        full_name = " ".join(part for part in name_parts if part)
        if not full_name:
            continue
        aliases = tuple(
            (alias.findtext("ALIAS_NAME") or "").strip()
            for alias in individual.findall("INDIVIDUAL_ALIAS")
            if (alias.findtext("ALIAS_NAME") or "").strip()
        )
        entries.append(SanctionsEntry(
            list_source="UN", reference_id=individual.findtext("REFERENCE_NUMBER") or "",
            name=full_name, entry_type="Individual", aliases=aliases,
        ))
    for entity in root.findall(".//ENTITIES/ENTITY"):
        full_name = (entity.findtext("FIRST_NAME") or "").strip()
        if not full_name:
            continue
        aliases = tuple(
            (alias.findtext("ALIAS_NAME") or "").strip()
            for alias in entity.findall("ENTITY_ALIAS")
            if (alias.findtext("ALIAS_NAME") or "").strip()
        )
        entries.append(SanctionsEntry(
            list_source="UN", reference_id=entity.findtext("REFERENCE_NUMBER") or "",
            name=full_name, entry_type="Entity", aliases=aliases,
        ))
    return entries


def _parse_uk_csv(raw: bytes) -> list[SanctionsEntry]:
    # The real UK-Sanctions-List.csv has one preamble line ("Report Date:
    # ...") before the real CSV header row — skipped explicitly rather than
    # assumed away by DictReader, which would otherwise treat that line as
    # the header and silently misread every column.
    text = raw.decode("utf-8-sig", errors="replace")
    lines = text.splitlines()
    if lines and lines[0].lower().startswith("report date"):
        lines = lines[1:]
    reader = csv.DictReader(io.StringIO("\n".join(lines)))

    entries: list[SanctionsEntry] = []
    for row in reader:
        primary = (row.get("Name 6") or "").strip()
        if not primary:
            continue
        aliases = tuple(
            (row.get(f"Name {n}") or "").strip()
            for n in (1, 2, 3, 4, 5)
            if (row.get(f"Name {n}") or "").strip()
        )
        entry_type = "Individual" if (row.get("D.O.B") or "").strip() else "Entity"
        entries.append(SanctionsEntry(
            list_source="UK", reference_id=row.get("Unique ID") or "",
            name=primary, entry_type=entry_type, aliases=aliases,
        ))
    return entries


_snapshot: tuple[list[SanctionsEntry], float] | None = None


async def _get_snapshot() -> list[SanctionsEntry]:
    global _snapshot
    now = time.monotonic()
    if _snapshot is not None and _snapshot[1] > now:
        return _snapshot[0]

    settings = get_settings()
    un_raw = await _download(settings.UN_SANCTIONS_XML_URL)
    uk_raw = await _download(settings.UK_SANCTIONS_CSV_URL)
    entries = _parse_un_xml(un_raw) + _parse_uk_csv(uk_raw)
    _snapshot = (entries, now + settings.SANCTIONS_SNAPSHOT_TTL_SECONDS)
    return entries


def _significant_words(name: str) -> set[str]:
    return {w.lower() for w in _WORD_PATTERN.findall(name) if len(w) >= 2}


async def screen_name(query_name: str, *, limit: int = 5) -> list[SanctionsEntry]:
    """Every significant word in query_name must appear in a listed name or
    alias for that entry to count as a match — conservative by design, see
    module docstring. Returns [] (not an exception) when nothing matches;
    a clean list is itself the correct, common result of a real screening
    check, not a failure."""
    query_words = _significant_words(query_name)
    if not query_words:
        return []

    entries = await _get_snapshot()
    matches = []
    for entry in entries:
        for candidate_name in entry.searchable_names():
            candidate_words = _significant_words(candidate_name)
            if query_words <= candidate_words:
                matches.append(entry)
                break
        if len(matches) >= limit:
            break
    return matches
