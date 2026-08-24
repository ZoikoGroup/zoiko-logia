"""
Ingestion and retrieval for uploaded documents.

Retrieval is keyword ranking over the uploader's OWN chunks only. It is not
labelled RAG and must not be: per ZL-ENG-02 §7 that word is reserved until
embeddings, semantic retrieval, reranking, citation binding, retrieval
evaluation, hallucination checks and freshness handling are all in place. What
this is, precisely, is Postgres full-text ranking (ts_rank_cd) over a corpus of
a few hundred chunks — which at that corpus size retrieves about as well as
anything more elaborate would, and is honest about what it does.

Why keyword ranking is enough here: the scope of a search is one user's
uploads. Twenty documents is on the order of 500 chunks. Dense retrieval and
cross-encoder reranking earn their latency when the right chunk is buried among
tens of thousands of plausible ones; they earn nothing against 500. The upgrade
path is a `document_chunks.embedding` column and a second ranked list fused
into this one, and nothing above this function needs to change when it happens.

SQLite has no tsvector, and the test suite runs on SQLite (see
settings.is_sqlite, used the same way throughout app/main.py). The fallback is
a LIKE-based scorer — good enough to prove the plumbing in tests, and never the
path a real deployment takes.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from sqlalchemy import delete as sa_delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.domains.documents import storage
from app.domains.documents.chunker import chunk_segments
from app.domains.documents.extract import ExtractionError, extract
from app.domains.documents.models import (
    STATUS_FAILED,
    STATUS_READY,
    DocumentChunk,
    UserDocument,
)

# How many chunks a single answer may be grounded in. Six to eight is the band
# where added context stops improving the answer and starts diluting the
# question; eight of 2,000 characters is ~4k tokens of evidence, which leaves
# the model ample room alongside the answering instructions.
MAX_CHUNKS_PER_ANSWER = 8

# Refuse to index a document that produced an implausible number of chunks —
# a 20MB CSV of one-column rows can otherwise generate tens of thousands.
MAX_CHUNKS_PER_DOCUMENT = 2_000

# Character ceiling on the evidence injected into one answer, across ALL
# attached documents. ~9,000 characters is ~2,250 tokens, which leaves room
# for the answering instructions, the web snippets and the reply itself
# inside a modest provider token-per-minute allowance.
#
# Learned the hard way: eight 2,000-character chunks is ~4,000 tokens, and
# five attached files took one request to 8,715 tokens against an 8,000 TPM
# limit. The provider rejected it, and the rejection was rendered to the
# reader where the answer should have been. A chunk count alone does not
# bound a request; a character budget does.
MAX_CHARS_PER_ANSWER = 9_000

_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'.-]*")

# Question scaffolding carries no signal about which chunk to retrieve, and
# left in place it matches everything. Deliberately short: over-filtering a
# short question ("what is vat") leaves nothing to search on.
_STOPWORDS = {
    "the", "and", "for", "with", "what", "which", "when", "where", "how", "why",
    "who", "was", "were", "are", "is", "does", "did", "do", "can", "could",
    "should", "would", "will", "from", "that", "this", "these", "those", "into",
    "about", "there", "their", "then", "than", "have", "has", "had", "been",
    "being", "our", "out", "any", "all", "you", "your", "please", "tell", "give",
    "show", "explain", "based", "document", "documents", "file", "files",
    "uploaded", "upload", "attachment", "attached",
}


@dataclass
class DocumentPassage:
    """One retrieved chunk, ready to be presented as evidence."""
    document_id: str
    filename: str
    locator: str
    content: str
    score: float


@dataclass
class RetrievedContext:
    """Passages plus whether they are the WHOLE of what was attached.

    `complete` is False when the budget or the chunk cap kept some of the
    attached documents out. The distinction has to travel with the evidence:
    asked to summarise five files, the model saw six of thirty sections and
    reported a total fixed-asset cost of 1,265,000 against a real 627,000, and
    28 ledger transactions against a real 600. It was not hallucinating so much
    as summing what it could see and presenting it as the whole.
    """
    passages: list["DocumentPassage"]
    complete: bool
    total_chunks: int


@dataclass
class IngestResult:
    document_id: str
    filename: str
    status: str
    chunk_count: int
    char_count: int
    failure_reason: str | None = None


def _query_terms(query: str) -> list[str]:
    """Search terms from a question, longest first so the most distinctive term
    is the one a truncated query keeps."""
    seen: set[str] = set()
    terms: list[str] = []
    for word in _WORD.findall(query or ""):
        lowered = word.lower().strip(".'-")
        if len(lowered) < 3 or lowered in _STOPWORDS or lowered in seen:
            continue
        seen.add(lowered)
        terms.append(lowered)
    terms.sort(key=len, reverse=True)
    # A long question yields dozens of terms, most of them noise. Twelve is
    # comfortably more than any real question needs to be answered.
    return terms[:12]


async def ingest_document(
    db: AsyncSession,
    *,
    tenant_id: str,
    user_id: str,
    filename: str,
    extension: str,
    data: bytes,
) -> IngestResult:
    """Extract, chunk and store one uploaded file.

    A file that cannot be read is recorded with status "failed" and its reason
    rather than being dropped — the uploader needs to know that their scanned
    PDF yielded no text, because the alternative is an answer that quietly
    ignores the document they just attached.
    """
    document = UserDocument(
        tenant_id=tenant_id,
        user_id=user_id,
        filename=filename,
        extension=extension,
        size_bytes=len(data),
        content_sha256=hashlib.sha256(data).hexdigest(),
    )
    db.add(document)
    await db.flush()          # assigns document.id before it is used below

    try:
        segments = extract(data, extension)
        chunks = chunk_segments(segments)
    except ExtractionError as exc:
        document.status = STATUS_FAILED
        document.failure_reason = str(exc)
        await db.commit()
        return IngestResult(
            document_id=document.id, filename=filename, status=STATUS_FAILED,
            chunk_count=0, char_count=0, failure_reason=str(exc),
        )
    except Exception as exc:
        # An unexpected parser crash is still the user's problem to see, but the
        # message must not leak a stack trace or a library internal.
        document.status = STATUS_FAILED
        document.failure_reason = f"This file could not be processed ({type(exc).__name__})."
        await db.commit()
        return IngestResult(
            document_id=document.id, filename=filename, status=STATUS_FAILED,
            chunk_count=0, char_count=0, failure_reason=document.failure_reason,
        )

    if not chunks:
        document.status = STATUS_FAILED
        document.failure_reason = "No readable text was found in this file."
        await db.commit()
        return IngestResult(
            document_id=document.id, filename=filename, status=STATUS_FAILED,
            chunk_count=0, char_count=0, failure_reason=document.failure_reason,
        )

    truncated = len(chunks) > MAX_CHUNKS_PER_DOCUMENT
    if truncated:
        chunks = chunks[:MAX_CHUNKS_PER_DOCUMENT]

    for chunk in chunks:
        db.add(DocumentChunk(
            document_id=document.id,
            tenant_id=tenant_id,
            user_id=user_id,
            ordinal=chunk.ordinal,
            content=chunk.content,
            locator=chunk.locator,
        ))

    document.status = STATUS_READY
    document.chunk_count = len(chunks)
    document.char_count = sum(len(c.content) for c in chunks)
    if truncated:
        # Not a failure — the document is answerable — but silently indexing
        # only part of a file would read as full coverage, so it is on the row.
        document.failure_reason = (
            f"Only the first {MAX_CHUNKS_PER_DOCUMENT} sections of this file were indexed."
        )

    # Object storage is best-effort and deliberately last: chunks are what
    # answers questions, so a storage outage must not lose the ingest.
    document.storage_path = await storage.upload(tenant_id, document.id, extension, data)

    await db.commit()
    return IngestResult(
        document_id=document.id, filename=filename, status=STATUS_READY,
        chunk_count=document.chunk_count, char_count=document.char_count,
        failure_reason=document.failure_reason,
    )


#: The materialised tsvector added by app/main.py's
#: _migrate_document_search_vector — parsed once at write time and covered by a
#: GIN index, so ranking reads it instead of rebuilding it per row per query.
STORED_VECTOR = "c.search_vector"
#: The original expression, rebuilt for every chunk on every question. Still the
#: path taken on a database where the migration has not run yet.
INLINE_VECTOR = "to_tsvector('english', c.content)"

_SEARCH_VECTOR_READY: bool | None = None
"""Whether document_chunks.search_vector exists, decided once per process.

None until the first search asks. The lifespan in app/main.py deliberately lets
a startup migration be skipped with a warning when it cannot take the table lock
in time (overlapping deploys), retrying on the next boot. Without this check
every question for the rest of that boot would fail with UndefinedColumn, and a
slower search is a far better outcome than a broken one.
"""


async def _search_vector_available(db: AsyncSession) -> bool:
    global _SEARCH_VECTOR_READY
    if _SEARCH_VECTOR_READY is None:
        row = await db.execute(text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'document_chunks' AND column_name = 'search_vector'"
        ))
        _SEARCH_VECTOR_READY = row.first() is not None
    return _SEARCH_VECTOR_READY


def _search_sql(vector: str) -> str:
    """The ranking query, over either the stored tsvector or the inline one.

    `vector` is interpolated rather than bound because a bound parameter is a
    value and this is a SQL expression. It is never user input — the only two
    values passed are the module constants above.
    """
    return f"""
        SELECT c.document_id,
               d.filename,
               c.locator,
               c.content,
               ts_rank_cd(
                   {vector},
                   websearch_to_tsquery('english', :search_text)
               ) AS score
          FROM document_chunks c
          JOIN user_documents d ON d.id = c.document_id
         WHERE c.tenant_id = :tenant_id
           AND c.user_id = :user_id
           AND c.document_id = ANY(:document_ids)
           AND {vector}
               @@ websearch_to_tsquery('english', :search_text)
         ORDER BY score DESC, c.ordinal ASC
         LIMIT :limit
        """


async def _search_postgres(
    db: AsyncSession, *, query: str, document_ids: list[str], tenant_id: str,
    user_id: str, limit: int,
) -> list[DocumentPassage]:
    """ts_rank_cd over the document chunks.

    websearch_to_tsquery (not to_tsquery) because it takes raw user text and
    never raises on punctuation — to_tsquery would reject "what's the VAT rate?"
    outright. ts_rank_cd rather than ts_rank because cover density rewards
    chunks where the query terms appear NEAR each other, which is what
    distinguishes a chunk that discusses the topic from one that merely mentions
    the words in unrelated places.

    tenant_id and user_id are filtered here as well as being enforced by RLS.
    That is deliberate belt-and-braces: the RLS policy is the guarantee, this
    filter is what keeps the query correct if it is ever run on a connection
    that has the superuser role (which Postgres exempts from RLS entirely).
    """
    terms = _query_terms(query)
    if not terms:
        return []
    search_text = " or ".join(terms)

    vector = STORED_VECTOR if await _search_vector_available(db) else INLINE_VECTOR
    rows = await db.execute(text(_search_sql(vector)), {
        "search_text": search_text,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "document_ids": document_ids,
        "limit": limit,
    })
    return [
        DocumentPassage(
            document_id=r.document_id, filename=r.filename,
            locator=r.locator, content=r.content, score=float(r.score),
        )
        for r in rows
    ]


async def _search_fallback(
    db: AsyncSession, *, query: str, document_ids: list[str], tenant_id: str,
    user_id: str, limit: int,
) -> list[DocumentPassage]:
    """Substring scorer for SQLite, where tsvector does not exist.

    Scores a chunk by how many distinct query terms it contains, weighted by
    term length so a match on "depreciation" counts for more than one on "and".
    Crude by design — this path exists so the test suite can exercise the
    pipeline, not to serve production traffic.
    """
    terms = _query_terms(query)
    if not terms:
        return []

    result = await db.execute(
        select(DocumentChunk, UserDocument.filename)
        .join(UserDocument, UserDocument.id == DocumentChunk.document_id)
        .where(
            DocumentChunk.tenant_id == tenant_id,
            DocumentChunk.user_id == user_id,
            DocumentChunk.document_id.in_(document_ids),
        )
        .order_by(DocumentChunk.ordinal.asc())
    )

    scored: list[DocumentPassage] = []
    for chunk, filename in result.all():
        lowered = chunk.content.lower()
        score = sum(len(t) for t in terms if t in lowered)
        if score:
            scored.append(DocumentPassage(
                document_id=chunk.document_id, filename=filename,
                locator=chunk.locator, content=chunk.content, score=float(score),
            ))
    scored.sort(key=lambda p: -p.score)
    return scored[:limit]


async def _count_chunks(db: AsyncSession, document_ids: list[str]) -> int:
    result = await db.execute(
        select(func.count(DocumentChunk.id)).where(
            DocumentChunk.document_id.in_(document_ids)
        )
    )
    return int(result.scalar() or 0)


async def _all_chunks(
    db: AsyncSession, document_ids: list[str], limit: int
) -> list[DocumentPassage]:
    """Up to `limit` chunks from the attached documents, taking a turn from each
    document in rotation rather than filling the budget from the first one.

    Ordering by filename and truncating gave every slot to whichever document
    sorted first: five files attached and asked to summarise, and the answer saw
    eight sections of the alphabetically-first file and nothing at all from the
    other four.
    """
    result = await db.execute(
        select(DocumentChunk, UserDocument.filename)
        .join(UserDocument, UserDocument.id == DocumentChunk.document_id)
        .where(DocumentChunk.document_id.in_(document_ids))
        .order_by(UserDocument.filename.asc(), DocumentChunk.ordinal.asc())
        # A cap on rows READ, not on rows returned — enough to fill the rotation
        # below for any realistic attachment set without loading a whole ledger.
        .limit(max(limit * 8, 64))
    )

    buckets: dict[str, list[DocumentPassage]] = {}
    order: list[str] = []
    for chunk, filename in result.all():
        if chunk.document_id not in buckets:
            buckets[chunk.document_id] = []
            order.append(chunk.document_id)
        buckets[chunk.document_id].append(
            DocumentPassage(
                document_id=chunk.document_id, filename=filename,
                locator=chunk.locator, content=chunk.content, score=1.0,
            )
        )

    picked: list[DocumentPassage] = []
    for rank in range(limit):
        for document_id in order:
            if len(picked) >= limit:
                return picked
            bucket = buckets[document_id]
            if len(bucket) > rank:
                picked.append(bucket[rank])
    return picked


def _trim_to_budget(passages: list[DocumentPassage]) -> list[DocumentPassage]:
    """Drop passages once the character budget is spent.

    The chunk count alone is not a safe budget: eight chunks of 2,000 characters
    is ~4,000 tokens of evidence, and on a small provider tier that is enough to
    push the whole request over the limit and get it rejected outright — the
    answer then comes back as a provider error rather than an answer. Bounding
    the characters bounds the request.

    Whole passages are dropped rather than all of them shortened, so every
    excerpt the model does see is complete and citable. The first passage is
    truncated only if it alone exceeds the budget, which would otherwise leave
    the model with nothing.
    """
    kept: list[DocumentPassage] = []
    spent = 0
    for passage in passages:
        cost = len(passage.content)
        if spent + cost > MAX_CHARS_PER_ANSWER:
            if kept:
                break
            room = MAX_CHARS_PER_ANSWER
            passage = DocumentPassage(
                document_id=passage.document_id, filename=passage.filename,
                locator=passage.locator, score=passage.score,
                content=passage.content[:room] + "\n[section truncated]",
            )
            cost = len(passage.content)
        kept.append(passage)
        spent += cost

    if len(kept) < len(passages):
        # Never silent: an answer built on part of the evidence must be
        # traceable to that fact in the logs.
        print(
            f"NOTE: injected {len(kept)} of {len(passages)} document section(s) "
            f"({spent:,} chars); the rest did not fit the context budget."
        )
    return kept


def _speaks_sqlite(db: AsyncSession) -> bool:
    """Whether THIS session speaks SQLite.

    Keyed off the session's own dialect rather than the global DATABASE_URL.
    The two agree in the running application, but they are not the same fact:
    a caller that opened its own SQLite engine while DATABASE_URL points at
    Postgres would otherwise be dispatched to the tsvector query and fail on
    syntax SQLite has never had. The dialect of the connection actually being
    used is what determines which SQL is valid, so that is what decides.

    Falls back to the global setting if the bind cannot be inspected, which
    keeps behaviour identical to before for any session shape not anticipated
    here.
    """
    try:
        return db.get_bind().dialect.name == "sqlite"
    except Exception:
        return get_settings().is_sqlite


async def retrieve_passages(
    db: AsyncSession,
    *,
    query: str,
    document_ids: list[str],
    tenant_id: str,
    user_id: str,
    limit: int = MAX_CHUNKS_PER_ANSWER,
) -> list[DocumentPassage]:
    """Passages only. Callers that must know whether the evidence is complete
    should use retrieve_context instead."""
    return (await retrieve_context(
        db, query=query, document_ids=document_ids,
        tenant_id=tenant_id, user_id=user_id, limit=limit,
    )).passages


async def retrieve_context(
    db: AsyncSession,
    *,
    query: str,
    document_ids: list[str],
    tenant_id: str,
    user_id: str,
    limit: int = MAX_CHUNKS_PER_ANSWER,
) -> RetrievedContext:
    """The best chunks from the named documents for this question.

    Returns [] — never raises — when there is nothing to search, nothing
    matches, or the search itself fails. A document the user attached but which
    happens not to contain the answer must leave the rest of the pipeline
    working exactly as it does with no attachment at all.
    """
    if not document_ids or not (query or "").strip():
        return RetrievedContext(passages=[], complete=True, total_chunks=0)

    # Only documents this caller owns, and only ones that actually indexed.
    # Done as its own query rather than trusted from the request body: the
    # client sends document ids, and a client is not an authority on ownership.
    owned = await db.execute(
        select(UserDocument.id).where(
            UserDocument.id.in_(document_ids),
            UserDocument.tenant_id == tenant_id,
            UserDocument.user_id == user_id,
            UserDocument.status == STATUS_READY,
        )
    )
    allowed = [row[0] for row in owned.all()]
    if not allowed:
        return RetrievedContext(passages=[], complete=True, total_chunks=0)

    try:
        # Attaching a file IS the intent signal. When everything the user
        # attached fits inside the answer budget, all of it goes in and keyword
        # ranking is skipped entirely — there is nothing to rank, and filtering
        # can only lose content that was already going to fit.
        #
        # This is not an optimisation, it is a correctness fix. A question can
        # be unmistakably about the attached file while sharing no vocabulary
        # with it: "is there anything here an auditor should question?" asked of
        # a trial balance whose columns are account_code / debit / credit
        # matches on none of "trial", "balance", "auditor" or "question",
        # because those words live in the FILENAME, not in the rows. Keyword
        # ranking returned nothing and the answer silently ignored the file.
        total = await _count_chunks(db, allowed)
        if total <= limit:
            kept = _trim_to_budget(await _all_chunks(db, allowed, limit))
            return RetrievedContext(
                passages=kept, complete=len(kept) >= total, total_chunks=total,
            )

        search = _search_fallback if _speaks_sqlite(db) else _search_postgres
        passages = await search(
            db, query=query, document_ids=allowed,
            tenant_id=tenant_id, user_id=user_id, limit=limit,
        )
        # A larger document whose text shares no words with the question hits
        # the same problem. Falling back to its opening chunks is imperfect —
        # they are where titles, headers and summaries live, not necessarily the
        # answer — but it beats ignoring a file the user explicitly attached,
        # and the answer will say plainly if what was asked is not in them.
        if not passages:
            print(
                f"NOTE: no keyword match in {len(allowed)} attached document(s) "
                f"({total} chunks); falling back to their opening sections."
            )
            kept = _trim_to_budget(await _all_chunks(db, allowed, limit))
            return RetrievedContext(
                passages=kept, complete=len(kept) >= total, total_chunks=total,
            )
    except Exception as exc:
        print(f"WARNING: document retrieval failed, answering without attachments: {exc}")
        return RetrievedContext(passages=[], complete=True, total_chunks=0)

    # Presented in document order, not score order: the model reads the
    # evidence block top to bottom, and out-of-order excerpts from the same
    # file read as contradictory when they are merely non-sequential.
    passages.sort(key=lambda p: (p.filename, p.locator))
    kept = _trim_to_budget(passages)
    return RetrievedContext(
        passages=kept, complete=len(kept) >= total, total_chunks=total,
    )


async def list_documents(
    db: AsyncSession, *, tenant_id: str, user_id: str, limit: int = 50
) -> list[UserDocument]:
    result = await db.execute(
        select(UserDocument)
        .where(UserDocument.tenant_id == tenant_id, UserDocument.user_id == user_id)
        .order_by(UserDocument.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def count_documents(db: AsyncSession, *, tenant_id: str, user_id: str) -> int:
    result = await db.execute(
        select(func.count(UserDocument.id)).where(
            UserDocument.tenant_id == tenant_id, UserDocument.user_id == user_id
        )
    )
    return int(result.scalar() or 0)


async def delete_document(
    db: AsyncSession, *, document_id: str, tenant_id: str, user_id: str
) -> bool:
    """Remove a document, its chunks and its stored original. Ownership is
    re-checked here rather than assumed from the caller's route."""
    result = await db.execute(
        select(UserDocument).where(
            UserDocument.id == document_id,
            UserDocument.tenant_id == tenant_id,
            UserDocument.user_id == user_id,
        )
    )
    document = result.scalars().first()
    if document is None:
        return False

    stored_path = document.storage_path
    await db.execute(sa_delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
    await db.delete(document)
    await db.commit()
    # After the DB row is gone: an orphaned object costs storage, an orphaned
    # row would be a document the user cannot delete.
    await storage.delete(stored_path)
    return True
