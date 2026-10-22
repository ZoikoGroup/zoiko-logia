"""The per-process passage cache (orchestration/passage_cache.py): it saves
re-reading passage text, and never decides — or bypasses — whether a passage
may be used. Changes are made with raw SQL, as a migration or script would,
behind the ORM's immutability guard."""
import asyncio
import hashlib

import pytest
from sqlalchemy import text

from app.orchestration import passage_cache as cache_module
from app.orchestration import retrieve
from app.orchestration.passage_cache import PassageCache
from app.orchestration.retrieve import build_source_bundle
from tests.test_hybrid_retrieval import _source, retrieval_db  # noqa: F401 — SQLite retrieval fixture

TEXT = "Revenue from a contract with a customer is recognised when control of the goods transfers."
QUERY = "When is revenue from a contract recognised under IFRS 15?"


@pytest.fixture
def cache(monkeypatch):
    fresh = PassageCache(max_bytes=1_000_000, ttl_seconds=600)
    monkeypatch.setattr(retrieve, "passage_cache", fresh)
    loads = []
    real = cache_module._load_rows

    async def counting(db, version_ids, **kwargs):
        loads.append(sorted(version_ids))
        return await real(db, version_ids, **kwargs)
    monkeypatch.setattr(cache_module, "_load_rows", counting)
    fresh.loads_seen = loads
    return fresh


async def bundle(db, tenant="tenant-a"):
    return await build_source_bundle(db, query=QUERY, jurisdiction="GB", tenant_id=tenant, framework="IFRS")


# 1–2. The first retrieval fills the cache; the next one does not re-read the text.
async def test_the_first_retrieval_populates_and_the_next_avoids_the_text_read(retrieval_db, cache):
    _, _, passage = await _source(retrieval_db, title="IFRS 15 Revenue", text=TEXT)
    first = await bundle(retrieval_db)
    assert [p.passage_id for p in first.passages] == [passage.id]
    assert len(cache.loads_seen) == 1 and cache.stats()["entries"] == 1
    second = await bundle(retrieval_db)
    assert [p.passage_id for p in second.passages] == [passage.id]
    assert len(cache.loads_seen) == 1 and cache.hits >= 1          # served from cache, same result


# 3. Changed content creates a distinct entry and is served fresh.
async def test_changed_passage_text_is_reloaded_not_served_stale(retrieval_db, cache):
    _, _, passage = await _source(retrieval_db, title="IFRS 15 Revenue", text=TEXT)
    await bundle(retrieval_db)
    new = TEXT + " Revenue from a contract is recognised over time for services."
    await retrieval_db.execute(text("UPDATE source_passages SET content = :c, content_hash = :h WHERE id = :id"),
                               {"c": new, "h": hashlib.sha256(new.encode()).hexdigest(), "id": passage.id})
    again = await bundle(retrieval_db)
    assert len(cache.loads_seen) == 2
    assert again.passages[0].content_hash == hashlib.sha256(new.encode()).hexdigest()
    assert cache.stats()["entries"] == 1                            # the obsolete entry was replaced


async def test_a_changed_heading_or_procedure_also_refreshes(retrieval_db, cache):
    _, _, passage = await _source(retrieval_db, title="IFRS 15 Revenue", text=TEXT)
    await bundle(retrieval_db)
    await retrieval_db.execute(text("UPDATE source_passages SET heading = 'Recognition' WHERE id = :id"), {"id": passage.id})
    await bundle(retrieval_db)
    assert len(cache.loads_seen) == 2


# 4. Withdrawn or unapproved versions are never returned, cached or not.
@pytest.mark.parametrize("status", ["WITHDRAWN", "DRAFT", "SUPERSEDED"])
async def test_a_withdrawn_or_unapproved_version_is_not_returned_from_cache(retrieval_db, cache, status):
    _, version, _ = await _source(retrieval_db, title="IFRS 15 Revenue", text=TEXT)
    assert (await bundle(retrieval_db)).passages                    # cached now
    await retrieval_db.execute(text("UPDATE source_versions SET status = :s WHERE id = :id"),
                               {"s": status, "id": version.id})
    assert (await bundle(retrieval_db)).passages == []


# 5. Tenant and permission boundaries.
async def test_a_revoked_right_removes_a_cached_passage(retrieval_db, cache):
    _, version, _ = await _source(retrieval_db, title="IFRS 15 Revenue", text=TEXT)
    assert (await bundle(retrieval_db)).passages
    await retrieval_db.execute(text("UPDATE source_rights SET decision = 'deny', reason_code = 'REVOKED' "
                                    "WHERE source_version_id = :id AND operation = 'retrieval'"), {"id": version.id})
    after = await bundle(retrieval_db)
    assert after.passages == [] and any("REVOKED" in reason for reason in after.exclusion_reasons)


async def test_another_tenant_never_receives_a_private_cached_passage(retrieval_db, cache):
    source, _, _ = await _source(retrieval_db, title="IFRS 15 Revenue", text=TEXT, tenant_id="tenant-a")
    await retrieval_db.execute(text("UPDATE sources SET is_tenant_private = 1 WHERE id = :id"), {"id": source.id})
    assert (await bundle(retrieval_db, "tenant-a")).passages        # tenant A has it cached
    assert (await bundle(retrieval_db, "tenant-b")).passages == []


async def test_cache_entries_are_never_shared_between_tenants(retrieval_db, cache):
    _, version, _ = await _source(retrieval_db, title="IFRS 15 Revenue", text=TEXT)
    await cache.load(retrieval_db, tenant_id="tenant-a", version_ids=[version.id])
    await cache.load(retrieval_db, tenant_id="tenant-b", version_ids=[version.id])
    assert len(cache.loads_seen) == 2                               # B's request read its own rows


async def test_only_the_requested_versions_are_returned(retrieval_db, cache):
    _, first, _ = await _source(retrieval_db, title="IFRS 15 Revenue", text=TEXT)
    _, second, _ = await _source(retrieval_db, title="IFRS 16 Leases", text="A lessee recognises a right-of-use asset.")
    await cache.load(retrieval_db, tenant_id="tenant-a", version_ids=[first.id, second.id])
    only = await cache.load(retrieval_db, tenant_id="tenant-a", version_ids=[second.id])
    assert {p.source_version_id for p in only} == {second.id}


# 6. Expired entries are refreshed.
async def test_an_expired_entry_is_reloaded(retrieval_db, cache):
    _, version, _ = await _source(retrieval_db, title="IFRS 15 Revenue", text=TEXT)
    cache.ttl_seconds = 0.01
    await cache.load(retrieval_db, tenant_id="tenant-a", version_ids=[version.id])
    await asyncio.sleep(0.03)
    await cache.load(retrieval_db, tenant_id="tenant-a", version_ids=[version.id])
    assert len(cache.loads_seen) == 2


# 7. Concurrent misses load once.
async def test_concurrent_misses_do_not_repeat_the_load(retrieval_db, cache, monkeypatch):
    _, version, _ = await _source(retrieval_db, title="IFRS 15 Revenue", text=TEXT)
    counting = cache_module._load_rows

    async def slow(db, version_ids, **kwargs):
        await asyncio.sleep(0.05)
        return await counting(db, version_ids, **kwargs)
    monkeypatch.setattr(cache_module, "_load_rows", slow)
    results = await asyncio.gather(*(cache.load(retrieval_db, tenant_id="tenant-a", version_ids=[version.id])
                                     for _ in range(5)))
    assert len(cache.loads_seen) == 1 and all(len(r) == 1 for r in results)


# 8. Capacity is bounded and eviction works.
async def test_capacity_is_bounded_with_least_recently_used_eviction(retrieval_db, cache):
    versions = []
    for n in range(4):
        _, version, _ = await _source(retrieval_db, title=f"Standard {n}", text=f"Paragraph {n} " + "x" * 2000)
        versions.append(version.id)
    await cache.load(retrieval_db, tenant_id="tenant-a", version_ids=[versions[0]])
    one_entry = cache.bytes
    cache.clear()
    cache.max_bytes = int(one_entry * 2.5)                          # about two entries
    for version_id in versions:
        await cache.load(retrieval_db, tenant_id="tenant-a", version_ids=[version_id])
    stats = cache.stats()
    assert stats["bytes"] <= cache.max_bytes and stats["evictions"] >= 2 and stats["entries"] <= 2
    await cache.load(retrieval_db, tenant_id="tenant-a", version_ids=[versions[0]])   # evicted: read again
    assert cache.loads_seen[-1] == [versions[0]]


async def test_a_disabled_cache_reads_every_time(retrieval_db, cache):
    _, version, _ = await _source(retrieval_db, title="IFRS 15 Revenue", text=TEXT)
    cache.max_bytes = 0
    for _ in range(2):
        await cache.load(retrieval_db, tenant_id="tenant-a", version_ids=[version.id])
    assert len(cache.loads_seen) == 2 and cache.stats()["entries"] == 0


# 9. A database failure is not answered from cache.
async def test_a_database_failure_is_raised_not_served_from_cache(retrieval_db, cache, monkeypatch):
    _, version, _ = await _source(retrieval_db, title="IFRS 15 Revenue", text=TEXT)
    await cache.load(retrieval_db, tenant_id="tenant-a", version_ids=[version.id])

    async def broken(*args, **kwargs):
        raise ConnectionResetError("database unreachable")
    monkeypatch.setattr(retrieval_db, "execute", broken)
    with pytest.raises(ConnectionResetError):
        await cache.load(retrieval_db, tenant_id="tenant-a", version_ids=[version.id])


def test_the_cached_record_is_immutable_and_holds_no_session_state():
    snapshot = cache_module.PassageSnapshot(id="p", source_version_id="v", locator="l", sequence=1, heading="",
                                            procedure="general", content="c", content_hash="h", text_digest="1")
    with pytest.raises(AttributeError):
        snapshot.content = "changed"


# Fingerprint completeness (verification gate, 2026-10-17).
async def test_text_changed_without_its_content_hash_is_still_reloaded(retrieval_db, cache):
    # A raw-SQL edit of the text that leaves content_hash as it was: the
    # fingerprint uses a digest the database computes from the text itself.
    _, _, passage = await _source(retrieval_db, title="IFRS 15 Revenue", text=TEXT)
    await bundle(retrieval_db)
    await retrieval_db.execute(text("UPDATE source_passages SET content = :c WHERE id = :id"),
                               {"c": TEXT + " Amended without a new hash.", "id": passage.id})
    loaded = await cache.load(retrieval_db, tenant_id="tenant-a", version_ids=[passage.source_version_id])
    assert len(cache.loads_seen) == 2 and loaded[0].content.endswith("Amended without a new hash.")


# Memory accounting and tenant fairness (engineering tasks, 2026-10-17).
def _snapshot(version_id, n, chars=600, wide=True):
    body = ("revenue contract " * (chars // 17 + 1))[:chars]
    if wide:
        body = body[: chars // 2] + "–" + body[chars // 2 + 1:]        # one en dash: 2 bytes a character
    return tuple(cache_module.PassageSnapshot(
        id=f"{version_id}-p{i}", source_version_id=version_id, locator=f"para {i}", sequence=i, heading="",
        procedure="general", content=(body + str(i))[:chars], content_hash="h" * 64, text_digest="d" * 32)
        for i in range(n))


def test_size_counts_the_text_as_python_stores_it():
    narrow, wide = _snapshot("v", 1, wide=False)[0], _snapshot("v", 1, wide=True)[0]
    # The same number of characters; one non-Latin-1 character doubles the text's storage.
    assert len(narrow.content) == len(wide.content) == 600
    assert wide.size - narrow.size >= 550
    assert narrow.size > len(narrow.content.encode())                 # headers, other fields, the object


def test_accounted_bytes_match_measured_allocations_within_ten_percent():
    import gc
    import tracemalloc
    cache = PassageCache(max_bytes=10 ** 10, ttl_seconds=600)
    gc.collect()
    tracemalloc.start()
    before = tracemalloc.take_snapshot()
    for tenant in range(3):
        for v in range(20):
            snapshot = _snapshot(f"t{tenant}-v{v}", 40)
            cache._put((f"tenant-{tenant}", f"v{v}", cache_module._fingerprint(snapshot)), snapshot)
            del snapshot
    gc.collect()
    measured = sum(stat.size_diff for stat in tracemalloc.take_snapshot().compare_to(before, "filename"))
    tracemalloc.stop()
    assert 0.9 <= measured / cache.bytes <= 1.1, (measured, cache.bytes)


def _fill(cache, tenant, versions, n=20):
    for v in range(versions):
        snapshot = _snapshot(f"{tenant}-v{v}", n)
        cache._put((tenant, f"v{v}", "fp"), snapshot)


def test_one_tenant_alone_may_use_the_whole_cache():
    entry = cache_module.entry_size(("tenant-a", "v0", "fp"), _snapshot("tenant-a-v0", 20))
    cache = PassageCache(max_bytes=entry * 10, ttl_seconds=600)
    _fill(cache, "tenant-a", 10)
    assert cache.stats()["entries"] == 10 and cache.evictions == 0


def test_a_tenant_over_its_share_cannot_push_another_below_its_share():
    entry = cache_module.entry_size(("tenant-a", "v0", "fp"), _snapshot("tenant-a-v0", 20))
    cache = PassageCache(max_bytes=entry * 10, ttl_seconds=600)
    _fill(cache, "tenant-b", 3)                                         # small tenant, used first (least recent)
    _fill(cache, "tenant-a", 30)                                        # large tenant floods the cache afterwards
    assert all(cache._get(("tenant-b", f"v{v}", "fp")) is not None for v in range(3))
    assert cache.bytes <= cache.max_bytes and cache.evictions > 0
    # Plain global LRU would have evicted tenant-b's three (oldest) entries first.


def test_within_a_tenant_eviction_is_least_recently_used():
    entry = cache_module.entry_size(("tenant-a", "v0", "fp"), _snapshot("tenant-a-v0", 20))
    cache = PassageCache(max_bytes=int(entry * 3.5), ttl_seconds=600)
    _fill(cache, "tenant-a", 3)
    assert cache._get(("tenant-a", "v0", "fp")) is not None            # v0 becomes the most recent
    cache._put(("tenant-a", "v3", "fp"), _snapshot("tenant-a-v3", 20))
    cache._get(("tenant-a", "v0", "fp"))
    cache._put(("tenant-a", "v9", "fp"), _snapshot("tenant-a-v9", 20))
    assert cache._get(("tenant-a", "v0", "fp")) is not None and cache._get(("tenant-a", "v1", "fp")) is None


def test_an_expired_entry_is_evicted_before_a_live_one():
    entry = cache_module.entry_size(("tenant-a", "v0", "fp"), _snapshot("tenant-a-v0", 20))
    cache = PassageCache(max_bytes=int(entry * 2.5), ttl_seconds=600)
    _fill(cache, "tenant-a", 1)
    _fill(cache, "tenant-b", 1)
    stored, passages, size = cache._entries[("tenant-b", "v0", "fp")]
    cache._entries[("tenant-b", "v0", "fp")] = (stored - 601, passages, size)   # tenant-b's entry has expired
    cache._get(("tenant-a", "v0", "fp"))
    cache._put(("tenant-c", "v0", "fp"), _snapshot("tenant-c-v0", 20))
    assert ("tenant-b", "v0", "fp") not in cache._entries and ("tenant-a", "v0", "fp") in cache._entries


def test_bookkeeping_is_released_with_the_entries():
    cache = PassageCache(max_bytes=10 ** 9, ttl_seconds=600)
    _fill(cache, "tenant-a", 3)
    cache._locks[("tenant-a", "v0")] = asyncio.Lock()
    for key in list(cache._entries):
        cache._drop(key)
    assert cache.bytes == 0 and not cache._tenant_bytes and not cache._by_tenant and not cache._locks
