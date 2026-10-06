"""Ingest official GOV.UK / HMRC guidance into the governed knowledge base.

    cd backend
    .venv/bin/python scripts/ingest_govuk.py              # every document below
    .venv/bin/python scripts/ingest_govuk.py --dry-run    # fetch and split only
    .venv/bin/python scripts/ingest_govuk.py --only /submit-vat-return

Reads each page from the GOV.UK Content API (structured, Open Government
Licence v3.0), splits it by its own section headings, tags each passage with
the tax procedure it covers, embeds it with the local model
(app/domains/source_library/embeddings.py) and stores it as an approved,
versioned, rights-recorded source in the shared GLOBAL_CONTROL tenant.

Re-running is safe: a page whose content is unchanged is skipped; a changed
page becomes a new version that supersedes the old one (approved passages are
immutable by design, so they are never edited in place).
"""
from __future__ import annotations

import argparse
import hashlib
import math
import os
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import httpx

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BACKEND / ".env")

from sqlalchemy import func, select, text  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.domains.identity.models import User  # noqa: E402
from app.domains.source_library.embeddings import LocalBgeEmbedder, vector_literal  # noqa: E402
from app.domains.source_library.models import Source, SourcePassage, SourceRight, SourceVersion  # noqa: E402
from app.orchestration.websearch import _html_to_text  # noqa: E402

CONTENT_API = "https://www.gov.uk/api/content"
TENANT = "GLOBAL_CONTROL"
LICENCE = "Open Government Licence v3.0 (https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/)"
# Everything the pipeline does with a passage. OGL permits all of it with
# attribution; "training" is deliberately not granted.
OPERATIONS = ("ingestion", "indexing", "retrieval", "model_transmission", "display", "summary", "export", "retention")
MAX_PASSAGE_CHARS = 1600
# Bumped whenever splitting or passage text changes. It is part of the
# version's content hash, so re-running after a change creates a new version
# superseding the old one (approved passages are never edited in place).
# 2: every passage starts with its document title — "You must leave the
#    scheme if…" never named the Flat Rate Scheme, so passages from the Cash
#    and Annual Accounting scheme guides outranked it.
# 3: refund passages tagged by claimant ("refund:non_uk",
#    "refund:unregistered_org") — app/orchestration/procedures.py.
CHUNKER_VERSION = "3"

# (GOV.UK path, procedure). The procedure is the tax procedure the whole
# document is about (app/orchestration/procedures.py); "general" documents
# answer any VAT question. Phase 1 corpus: UK VAT.
DOCUMENTS: list[tuple[str, str]] = [
    ("/guidance/vat-guide-notice-700", "general"),
    ("/how-vat-works", "general"),
    ("/vat-rates", "general"),
    ("/guidance/rates-of-vat-on-different-goods-and-services", "general"),
    # Carries the temporary zero rate on domestic electricity (1 Oct 2026 -
    # 31 Mar 2027) that the general rates pages do not yet show.
    ("/guidance/vat-on-fuel-and-power-notice-70119", "general"),
    # Specific notices outrank the general guide they are summarised in:
    # Notice 700 §29.3.14 still describes sanitary products as reduced-rated,
    # while this notice gives the zero rate in force since 1 January 2021.
    ("/guidance/vat-on-womens-sanitary-products-notice-70118", "general"),
    ("/submit-vat-return", "general"),
    ("/government/publications/vat-notice-70022-making-tax-digital-for-vat/vat-notice-70022-making-tax-digital-for-vat", "general"),
    ("/guidance/making-tax-digital-for-vat-as-an-agent-step-by-step", "general"),
    ("/guidance/authorise-an-agent-to-deal-with-certain-tax-services-for-you", "general"),
    ("/vat-record-keeping", "general"),
    ("/vat-flat-rate-scheme", "general"),
    ("/vat-cash-accounting-scheme", "general"),
    ("/vat-annual-accounting-scheme", "general"),
    ("/guidance/vat-domestic-reverse-charge-for-building-and-construction-services", "general"),
    # The "check when you must use" page above does not say who accounts for
    # the VAT (the customer); HMRC's technical guide does.
    ("/guidance/vat-reverse-charge-technical-guide", "general"),
    ("/vat-registration", "registration"),
    ("/guidance/refunds-of-uk-vat-for-non-uk-businesses-or-eu-vat-for-uk-businesses", "refund:non_uk"),
    ("/guidance/claim-a-vat-refund-as-an-organisation-not-registered-for-vat", "refund:unregistered_org"),
    ("/guidance/penalty-points-and-penalties-if-you-submit-your-vat-return-late", "penalty"),
    ("/guidance/how-late-payment-penalties-work-if-you-pay-vat-late", "penalty"),
]

_HEADING = re.compile(r"(?is)<h([23])\b([^>]*)>(.*?)</h\1\s*>")
_ID = re.compile(r'\bid="([^"]+)"')


@dataclass
class Passage:
    locator: str
    heading: str
    content: str


@dataclass
class Document:
    path: str
    title: str
    url: str
    updated: datetime
    body_hash: str
    passages: list[Passage]


def _plain(fragment: str) -> str:
    return re.sub(r"\s+", " ", _html_to_text(fragment)).strip()


def _split_long(text: str) -> list[str]:
    """Pieces of at most MAX_PASSAGE_CHARS, broken at line ends where possible."""
    pieces, current = [], ""
    for line in text.split("\n"):
        if len(line) > MAX_PASSAGE_CHARS and current.strip():
            pieces.append(current.strip())
            current = ""
        while len(line) > MAX_PASSAGE_CHARS:  # one huge line: break at a sentence
            cut = line.rfind(". ", 0, MAX_PASSAGE_CHARS) + 1 or MAX_PASSAGE_CHARS
            pieces.append((current + "\n" + line[:cut]).strip())
            current, line = "", line[cut:].strip()
        if len(current) + len(line) + 1 > MAX_PASSAGE_CHARS and current:
            pieces.append(current.strip())
            current = ""
        current += "\n" + line
    if current.strip():
        pieces.append(current.strip())
    return pieces


def _sections(html: str, base_locator: str, prefix: str, title: str) -> list[Passage]:
    """Split one HTML body at its h2/h3 headings; each passage carries its
    heading path ("Part — 4. Who can submit — 4.2 Agents")."""
    passages: list[Passage] = []
    matches = list(_HEADING.finditer(html))
    h2 = ""
    starts = [(0, "", "", "")] + [
        (m.end(), m.group(1), _plain(m.group(3)), (_ID.search(m.group(2)) or [None, ""])[1]) for m in matches
    ]
    for index, (start, level, heading, anchor) in enumerate(starts):
        end = matches[index].start() if index < len(matches) else len(html)
        if level == "2":
            h2 = heading
        path = " — ".join(part for part in (prefix, h2, heading if level == "3" else "") if part)
        body = _html_to_text(html[start:end])
        if len(body) < 40:  # a heading with no text of its own
            continue
        for piece_index, piece in enumerate(_split_long(body)):
            locator = f"{base_locator}#{anchor or f's{index}'}" + (f"/{piece_index + 1}" if piece_index else "")
            context = " — ".join(part for part in (title, path) if part)
            passages.append(Passage(locator=locator, heading=path, content=f"{context}\n{piece}"))
    return passages


def fetch(path: str) -> Document:
    response = httpx.get(f"{CONTENT_API}{path}", timeout=30, follow_redirects=True)
    response.raise_for_status()
    data = response.json()
    if data.get("schema_name") == "redirect" and data.get("redirects"):
        # A moved page (/vat-registration -> /register-for-vat) answers with a
        # redirect record, not the content; follow it once.
        destination = data["redirects"][0]["destination"].split("#")[0]
        response = httpx.get(f"{CONTENT_API}{destination}", timeout=30, follow_redirects=True)
        response.raise_for_status()
        data = response.json()
    details = data.get("details") or {}
    url = f"https://www.gov.uk{data.get('base_path') or path}"
    title = (data.get("title") or path).strip()
    passages: list[Passage] = []
    raw = ""
    if details.get("parts"):
        for part in details["parts"]:
            raw += part.get("body") or ""
            part_url = f"{url}/{part.get('slug', '')}".rstrip("/")
            passages += _sections(part.get("body") or "", part_url, part.get("title", ""), title)
    else:
        raw = details.get("body") or ""
        passages = _sections(raw, url, "", title)
    # Locators must be unique within a version.
    seen: dict[str, int] = {}
    for passage in passages:
        count = seen.get(passage.locator, 0)
        seen[passage.locator] = count + 1
        if count:
            passage.locator += f"~{count + 1}"
    return Document(
        path=path, title=title, url=url,
        updated=datetime.fromisoformat(data["public_updated_at"].replace("Z", "+00:00")),
        body_hash=hashlib.sha256(f"chunker:{CHUNKER_VERSION}\n{raw}".encode()).hexdigest(), passages=passages,
    )


@dataclass(frozen=True)
class Publisher:
    """Who issued a document, where it applies and on what licence — the
    values a governed source carries. GOV.UK guidance is HMRC under OGL v3;
    scripts/ingest_official.py passes other official publishers."""
    name: str
    jurisdiction_scope: str
    reason_code: str
    terms: str


HMRC = Publisher(
    name="HM Revenue & Customs", jurisdiction_scope="UK,GB,United Kingdom", reason_code="OGL_V3", terms=LICENCE,
)


def ingest(
    document: Document, procedure: str, user_id: str, embedder: LocalBgeEmbedder, publisher: Publisher = HMRC,
) -> str:
    if not document.passages:
        raise ValueError("Cannot approve a document with no passages")
    if not document.url.startswith("https://"):
        raise ValueError("Official evidence requires an HTTPS source URL")
    if len({p.locator for p in document.passages}) != len(document.passages):
        raise ValueError("Passage locators must be unique")
    with SessionLocal() as db:
        # Trimmed: GOV.UK titles can carry a trailing space ("VAT Flat Rate
        # Scheme "), which once created a second source for the same page; the
        # exact title wins when both exist.
        matches = db.execute(select(Source).where(
            Source.tenant_id == TENANT, func.trim(Source.title) == document.title,
            Source.publisher == publisher.name,
        )).scalars().all()
        source = next((m for m in matches if m.title == document.title), matches[0] if matches else None)
        if source is None:
            source = Source(
                tenant_id=TENANT, category="tax", title=document.title,
                publisher=publisher.name, owner=publisher.name,
                source_class="official_guidance", jurisdiction_scope=publisher.jurisdiction_scope,
                framework_scope="", licence_state="permitted", authority_level="primary",
                is_tenant_private=False,
            )
            db.add(source)
            db.flush()
        current = db.execute(
            select(SourceVersion).where(
                SourceVersion.source_id == source.id,
                SourceVersion.status.in_(("APPROVED", "ACTIVE")),
                SourceVersion.superseded_by_version_id.is_(None),
            )
        ).scalar_one_or_none()
        if current is not None and current.content_hash == document.body_hash:
            db.rollback()
            return "unchanged"

        version = SourceVersion(
            tenant_id=TENANT, source_id=source.id, version_label=document.updated.date().isoformat(),
            status="PROPOSED", effective_from=document.updated.date(), source_url=document.url,
            content_hash=document.body_hash, published_at=document.updated,
            submitted_by=user_id, note=f"Ingested from {publisher.name} on {date.today().isoformat()}.",
            quality_state="REVIEWED",
        )
        db.add(version)
        db.flush()
        rows = [
            SourcePassage(
                tenant_id=TENANT, source_version_id=version.id, locator=passage.locator, sequence=index,
                heading=passage.heading[:500], procedure=procedure, content=passage.content,
                content_hash=hashlib.sha256(passage.content.encode()).hexdigest(), language="en",
            )
            for index, passage in enumerate(document.passages, start=1)
        ]
        db.add_all(rows)
        db.flush()
        # Embedded while the version is still PROPOSED: approved passages are
        # immutable. Raw SQL — the ORM does not map the pgvector column.
        vectors = embedder.embed_passages([row.content for row in rows])
        if len(vectors) != len(rows) or any(len(v) != 384 or not all(math.isfinite(x) for x in v) for v in vectors):
            raise ValueError("Embedding results must contain one finite 384-dimensional vector per passage")
        if db.get_bind().dialect.name == "postgresql":
            for row, vector in zip(rows, vectors):
                db.execute(
                    text("UPDATE source_passages SET embedding = CAST(:vector AS vector) WHERE id = :id"),
                    {"vector": vector_literal(vector), "id": row.id},
                )
        for operation in OPERATIONS:
            db.add(SourceRight(
                tenant_id=TENANT, source_version_id=version.id, operation=operation, decision="allow",
                rights_version=1, reason_code=publisher.reason_code, terms_reference=publisher.terms, granted_by=user_id,
            ))
        version.status = "APPROVED"
        version.approved_by = user_id
        if current is not None:
            current.superseded_by_version_id = version.id
        db.commit()
        return "superseded previous version" if current is not None else "new"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="fetch and split only; write nothing")
    parser.add_argument("--only", nargs="*", help="ingest only these GOV.UK paths")
    parser.add_argument("--user-email", default="dashboard@zoikologia.com",
                        help="recorded as submitter/approver of the ingested versions")
    args = parser.parse_args()

    documents = [(p, proc) for p, proc in DOCUMENTS if not args.only or p in args.only]
    embedder = None
    user_id = ""
    if not args.dry_run:
        with SessionLocal() as db:
            user = db.execute(select(User).where(User.email == args.user_email)).scalar_one_or_none()
        if user is None:
            sys.exit(f"No user {args.user_email}; pass --user-email of an existing user.")
        user_id = user.id
        embedder = LocalBgeEmbedder(os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5"))

    total = 0
    failures = 0
    for path, procedure in documents:
        try:
            document = fetch(path)
        except Exception as exc:  # noqa: BLE001 — one bad page must not stop the rest
            print(f"FAIL  {path}: {type(exc).__name__}: {exc}")
            failures += 1
            continue
        if not document.passages:
            print(f"FAIL  {path}: no passages (unsupported page type {document.title!r})")
            failures += 1
            continue
        total += len(document.passages)
        if args.dry_run:
            longest = max((len(p.content) for p in document.passages), default=0)
            print(f"{len(document.passages):4d} passages (longest {longest}) [{procedure}] {document.title}")
            continue
        outcome = ingest(document, procedure, user_id, embedder)
        print(f"{outcome:28s} {len(document.passages):4d} passages [{procedure}] {document.title}")
    print(f"\n{total} passages across {len(documents)} documents; {failures} failed.")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
