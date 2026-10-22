"""A bounded per-process cache of source passage text for governed retrieval.

What it saves: the keyword half of retrieval reads every passage of every
eligible source version (~2,300 rows, 1.9 MB of text, 0.5–0.6 s warm and
seconds on a slow link) on every pass of every question. Only the text is
cached; every decision about whether a passage may be used is not.

What it never caches: which source versions are eligible. Approval and
withdrawal status, tenant visibility, jurisdiction, effective dates and
retrieval/model-transmission rights are decided by build_source_bundle's own
queries on every request, before this cache is asked for anything, and the
cache only ever returns passages of the version ids it is given.

Freshness, across processes, without invalidation messages: each request
first reads a small manifest of the visible passages of those versions —
id, content hash, heading, procedure, locator, sequence — under the
request's own row-level security. A version's cached passages are used only
when the manifest's fingerprint matches exactly; otherwise they are loaded
again. A changed passage (even one changed by raw SQL or another backend
process) changes the fingerprint, so it is never served stale. Entries also
expire after a TTL, as a backstop.

Isolation: the key is (tenant, source version, fingerprint). Rows visible to
a tenant are decided by RLS in the manifest query itself, and one tenant's
entries are never returned for another tenant's request.

Memory: the limit is in bytes actually held (strings as CPython stores them,
objects, keys and bookkeeping), and eviction is fair between tenants (see
PassageCache).

A database failure in the manifest or the load is raised as before: nothing
is answered from cache when the authoritative check cannot run.
"""
from __future__ import annotations

import asyncio
import hashlib
import sys
import time
from collections import OrderedDict
from dataclasses import dataclass

from sqlalchemy import String, func, select


@dataclass(frozen=True)
class PassageSnapshot:
    """The fields retrieval reads from a SourcePassage, immutable."""
    id: str
    source_version_id: str
    locator: str
    sequence: int
    heading: str
    procedure: str
    content: str
    content_hash: str
    # The digest of `content` as the manifest computes it (_text_digest).
    text_digest: str = ""

    @property
    def size(self) -> int:
        """Bytes this record holds in memory: the instance, its attribute
        dict and every value. A str costs 1, 2 or 4 bytes a character by its
        widest character, plus its header; one en dash makes a passage 2 bytes
        a character, which is why UTF-8 length undercounted about 2x."""
        return (sys.getsizeof(self) + sys.getsizeof(self.__dict__)
                + sum(sys.getsizeof(value) for value in self.__dict__.values()))


def _text_digest(content: str, postgres: bool) -> str:
    """What the manifest computes in the database from the text itself:
    md5(content) on PostgreSQL, length(content) elsewhere (SQLite has no md5)."""
    return hashlib.md5((content or "").encode()).hexdigest() if postgres else str(len(content or ""))


def _fingerprint(rows) -> str:
    """Of a version's visible passages, in order: every field retrieval reads,
    with the text represented by a digest the DATABASE computes from it — not
    by the stored content_hash column, which a raw-SQL edit of the text could
    leave unchanged (and stale text would then match)."""
    digest = hashlib.sha256()
    for row in sorted(rows, key=lambda r: (r.sequence, r.id)):
        digest.update("\x1f".join(str(part) for part in (
            row.id, row.content_hash, row.text_digest, row.heading or "", row.procedure or "general",
            row.locator, row.sequence,
        )).encode())
        digest.update(b"\x1e")
    return digest.hexdigest()


# Per entry, besides its passages: the stored (time, passages, size) tuple
# and its float and int, the two ordered-dict slots that index it (global
# and per-tenant) and its load lock. Measured with tracemalloc on CPython 3.12
# (tests/test_passage_cache.py checks the total stays within 10%).
_ENTRY_OVERHEAD = 480


def entry_size(key: tuple[str, str, str], passages: tuple[PassageSnapshot, ...]) -> int:
    """Bytes held by an entry, counting shared field values once per entry."""
    seen: set[int] = set()

    def size(value) -> int:
        if id(value) in seen:
            return 0
        seen.add(id(value))
        total = sys.getsizeof(value)
        if isinstance(value, tuple):
            total += sum(size(part) for part in value)
        elif isinstance(value, PassageSnapshot):
            total += sys.getsizeof(value.__dict__) + sum(size(part) for part in value.__dict__.values())
        return total

    return size(key) + size(passages) + _ENTRY_OVERHEAD


class PassageCache:
    """Bounded by bytes of memory; least-recently-used, with a fair-share
    floor per tenant: while any tenant holds more than an equal split of the
    limit, eviction takes the least recently used entry of a tenant over it.
    A tenant alone may use the whole cache, idle space is not reserved, and a
    tenant with a large library or heavy traffic cannot push the others below
    their share."""

    # The protected floor, as a fraction of an equal split of the limit.
    fair_share = 1.0

    def __init__(self, *, max_bytes: int, ttl_seconds: float):
        self.max_bytes, self.ttl_seconds = max_bytes, ttl_seconds
        self._entries: OrderedDict[tuple[str, str, str], tuple[float, tuple[PassageSnapshot, ...], int]] = OrderedDict()
        self._by_tenant: dict[str, OrderedDict[tuple[str, str, str], None]] = {}
        self._tenant_bytes: dict[str, int] = {}
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}
        self.bytes = 0
        self.hits = self.misses = self.evictions = self.loads = 0

    @property
    def enabled(self) -> bool:
        return self.max_bytes > 0 and self.ttl_seconds > 0

    def clear(self) -> None:
        self._entries.clear()
        self._by_tenant.clear()
        self._tenant_bytes.clear()
        self.bytes = 0

    def stats(self) -> dict:
        lookups = self.hits + self.misses
        return {"entries": len(self._entries), "bytes": self.bytes, "max_bytes": self.max_bytes,
                "tenants": len(self._tenant_bytes), "largest_tenant_bytes": max(self._tenant_bytes.values(), default=0),
                "hits": self.hits, "misses": self.misses, "loads": self.loads, "evictions": self.evictions,
                "hit_rate": round(self.hits / lookups, 3) if lookups else None}

    def _get(self, key) -> tuple[PassageSnapshot, ...] | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        stored, passages, _ = entry
        if time.monotonic() - stored > self.ttl_seconds:
            self._drop(key)
            return None
        self._entries.move_to_end(key)
        self._by_tenant[key[0]].move_to_end(key)
        return passages

    def _drop(self, key) -> None:
        _, _, size = self._entries.pop(key)
        self.bytes -= size
        tenant = key[0]
        self._tenant_bytes[tenant] -= size
        del self._by_tenant[tenant][key]
        if not self._by_tenant[tenant]:
            del self._by_tenant[tenant], self._tenant_bytes[tenant]
        lock = self._locks.get(key[:2])
        if lock is not None and not lock.locked():
            del self._locks[key[:2]]

    def _evict_one(self) -> None:
        # Least recently used first, skipping tenants within their fair share
        # (an equal split among the tenants holding entries) while any tenant
        # is over it. An expired entry is always taken.
        share = self.fair_share * self.max_bytes / len(self._tenant_bytes)
        now = time.monotonic()
        victim = next(iter(self._entries))
        for key, (stored, _, _) in self._entries.items():
            if now - stored > self.ttl_seconds or self._tenant_bytes[key[0]] > share:
                victim = key
                break
        self._drop(victim)
        self.evictions += 1

    def _put(self, key, passages: tuple[PassageSnapshot, ...]) -> None:
        size = entry_size(key, passages)
        if size > self.max_bytes:
            return                                          # larger than the whole cache: not kept
        tenant = key[0]
        # One entry per (tenant, version): an older fingerprint is obsolete.
        for stale in [k for k in self._by_tenant.get(tenant, ()) if k[1] == key[1]]:
            self._drop(stale)
        self._entries[key] = (time.monotonic(), passages, size)
        self._by_tenant.setdefault(tenant, OrderedDict())[key] = None
        self._tenant_bytes[tenant] = self._tenant_bytes.get(tenant, 0) + size
        self.bytes += size
        while self.bytes > self.max_bytes and self._entries:
            self._evict_one()

    async def load(self, db, *, tenant_id: str, version_ids: list[str]) -> list[PassageSnapshot]:
        """The passages of `version_ids` visible to this request, ordered by
        (source version, sequence) as the uncached query returned them."""
        from app.domains.source_library.models import SourcePassage
        if not version_ids:
            return []
        if not self.enabled:
            return await _load_rows(db, version_ids, postgres=False)
        postgres = db.get_bind().dialect.name == "postgresql"
        text_digest = (func.md5(SourcePassage.content) if postgres
                       else func.cast(func.length(SourcePassage.content), String))
        manifest_rows = (await db.execute(
            select(SourcePassage.id, SourcePassage.source_version_id, SourcePassage.content_hash,
                   text_digest.label("text_digest"), SourcePassage.heading, SourcePassage.procedure,
                   SourcePassage.locator, SourcePassage.sequence)
            .where(SourcePassage.source_version_id.in_(version_ids))
        )).all()
        manifest: dict[str, list] = {}
        for row in manifest_rows:
            manifest.setdefault(row.source_version_id, []).append(row)
        result: dict[str, tuple[PassageSnapshot, ...]] = {}
        missing: list[str] = []
        for version_id in manifest:
            cached = self._get((tenant_id, version_id, _fingerprint(manifest[version_id])))
            if cached is None:
                missing.append(version_id)
            else:
                result[version_id] = cached
                self.hits += 1
        if missing:
            self.misses += len(missing)
            # One load at a time per (tenant, version): concurrent requests
            # missing the same versions wait for that load, not repeat it.
            locks = [self._locks.setdefault((tenant_id, version_id), asyncio.Lock()) for version_id in sorted(missing)]
            for lock in locks:
                await lock.acquire()
            try:
                # Another request may have loaded them while this one waited.
                still = []
                for version_id in missing:
                    cached = self._get((tenant_id, version_id, _fingerprint(manifest[version_id])))
                    if cached is None:
                        still.append(version_id)
                    else:
                        result[version_id] = cached
                if still:
                    self.loads += 1
                    loaded: dict[str, list[PassageSnapshot]] = {}
                    for passage in await _load_rows(db, still, postgres=postgres):
                        loaded.setdefault(passage.source_version_id, []).append(passage)
                    for version_id, passages in loaded.items():
                        snapshot = tuple(passages)
                        result[version_id] = snapshot
                        # Keyed by what was actually loaded: if a passage changed
                        # between the manifest and the load, the entry is for the
                        # new content, and the next manifest will match it.
                        self._put((tenant_id, version_id, _fingerprint(snapshot)), snapshot)
            finally:
                for lock in locks:
                    lock.release()
        ordered = [passage for version_id in sorted(result) for passage in result[version_id]]
        return sorted(ordered, key=lambda p: (p.source_version_id, p.sequence))


async def _load_rows(db, version_ids: list[str], *, postgres: bool = False) -> list[PassageSnapshot]:
    from app.domains.source_library.models import SourcePassage
    rows = (await db.execute(
        select(SourcePassage)
        .where(SourcePassage.source_version_id.in_(version_ids))
        .order_by(SourcePassage.source_version_id, SourcePassage.sequence)
        # Fresh values, never the session's in-memory copy: a passage changed
        # behind the ORM (raw SQL) was otherwise returned as it was before.
        .execution_options(populate_existing=True)
    )).scalars().all()
    return [PassageSnapshot(id=row.id, source_version_id=row.source_version_id, locator=row.locator,
                            sequence=row.sequence, heading=row.heading or "", procedure=row.procedure or "general",
                            content=row.content or "", content_hash=row.content_hash,
                            text_digest=_text_digest(row.content, postgres)) for row in rows]


def _settings_cache() -> PassageCache:
    from app.core.config import get_settings
    settings = get_settings()
    return PassageCache(max_bytes=settings.PASSAGE_CACHE_MAX_BYTES, ttl_seconds=settings.PASSAGE_CACHE_TTL_SECONDS)


passage_cache = _settings_cache()
