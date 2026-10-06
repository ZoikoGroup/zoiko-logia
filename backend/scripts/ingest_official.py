"""Ingest official documents published as PDF (outside GOV.UK) into the
governed knowledge base.

    cd backend
    .venv/bin/python scripts/ingest_official.py --dry-run
    .venv/bin/python scripts/ingest_official.py

Each document is fetched over verified TLS only, split by its own structure
(numbered questions for an FAQ), and stored exactly as scripts/ingest_govuk.py
stores GOV.UK pages: an approved, versioned, rights-recorded source whose
changed content supersedes the old version.

Phase 1 India GST corpus. Deliberately NOT included:
  * CBIC's taxinformation.cbic.gov.in (rate notifications as amended): its
    server sends an incomplete certificate chain, and fetching governed
    evidence with certificate checks disabled would let a tampered connection
    plant false rates. Pin CBIC's intermediate certificate first.
  * CBIC's 2017 rate schedules: superseded by the September 2025 rates.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import os
import ssl
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx

BACKEND = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("ingest_govuk", BACKEND / "scripts" / "ingest_govuk.py")
govuk = importlib.util.module_from_spec(_spec)
sys.modules["ingest_govuk"] = govuk
_spec.loader.exec_module(govuk)

from pypdf import PdfReader  # noqa: E402
from sqlalchemy import select  # noqa: E402

GST_COUNCIL = govuk.Publisher(
    name="GST Council Secretariat",
    jurisdiction_scope="India,IN",
    reason_code="IN_GOV_PUBLICATION",
    terms=(
        "Government of India publication. Reproduction of official government publications relied on under "
        "the Copyright Act 1957, s.52(1)(q). Confirm with legal before production use."
    ),
)


@dataclass(frozen=True)
class OfficialDocument:
    url: str
    title: str
    publisher: govuk.Publisher
    published: datetime
    procedure: str = "general"


DOCUMENTS: list[OfficialDocument] = [
    OfficialDocument(
        url="https://gstcouncil.gov.in/sites/default/files/2025-09/faq_0.pdf",
        title="FAQs on GST rate changes (GST Council, September 2025)",
        publisher=GST_COUNCIL,
        # Changes recommended at the 56th GST Council meeting, effective 22 September 2025.
        published=datetime(2025, 9, 22, tzinfo=timezone.utc),
    ),
]

_QUESTION = re.compile(r"(?m)^\s*(\d{1,3})\.\s+(?=\S)")


def _pdf_text(url: str) -> str:
    # verify=True is httpx's default and is relied on: see the module docstring.
    ca_bundle = os.getenv("OFFICIAL_DOCUMENT_CA_BUNDLE")
    verified_tls = ssl.create_default_context(cafile=ca_bundle) if ca_bundle else True
    response = httpx.get(url, timeout=60, follow_redirects=True, verify=verified_tls,
                         headers={"User-Agent": "Mozilla/5.0 (compatible; KritonResearch/1.0)"})
    response.raise_for_status()
    reader = PdfReader(io.BytesIO(response.content))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    # A browser print of a web page carries its header/footer on every page
    # ("9/9/25, 12:53 PM Press Release:Press Information Bureau https://… 8/10");
    # left in, it lands in the middle of answers.
    text = re.sub(r"\d{1,2}/\d{1,2}/\d{2}, \d{1,2}:\d{2} [AP]M[^\n]*", " ", text)
    text = re.sub(r"https?://\S+\s+\d{1,3}/\d{1,3}", " ", text)
    return text


def split_numbered_questions(text: str, title: str, url: str) -> list:
    """One passage per numbered question and its answer, headed by the
    document title so search knows which publication it belongs to."""
    starts = list(_QUESTION.finditer(text))
    passages = []
    for index, match in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        body = " ".join(text[match.start():end].split())
        if len(body) < 40:
            continue
        question = re.split(r"(?<=\?)\s", body, maxsplit=1)[0][:300]
        for piece_index, piece in enumerate(govuk._split_long(body)):
            locator = f"{url}#q{match.group(1)}" + (f"/{piece_index + 1}" if piece_index else "")
            passages.append(govuk.Passage(locator=locator, heading=question, content=f"{title} — {piece}"))
    # Keep locators unique even if the PDF numbers a question twice.
    seen: dict[str, int] = {}
    for passage in passages:
        count = seen.get(passage.locator, 0)
        seen[passage.locator] = count + 1
        if count:
            passage.locator += f"~{count + 1}"
    return passages


def fetch(document: OfficialDocument):
    text = _pdf_text(document.url)
    return govuk.Document(
        path=document.url, title=document.title, url=document.url, updated=document.published,
        body_hash=hashlib.sha256(f"chunker:{govuk.CHUNKER_VERSION}\n{text}".encode()).hexdigest(),
        passages=split_numbered_questions(text, document.title, document.url),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="fetch and split only; write nothing")
    parser.add_argument("--user-email", default="dashboard@zoikologia.com")
    args = parser.parse_args()
    if not args.dry_run and os.getenv("GST_INGESTION_RIGHTS_APPROVED", "").lower() != "true":
        parser.error("GST_INGESTION_RIGHTS_APPROVED=true is required after source rights approval")

    embedder, user_id = None, ""
    if not args.dry_run:
        with govuk.SessionLocal() as db:
            user = db.execute(select(govuk.User).where(govuk.User.email == args.user_email)).scalar_one_or_none()
        if user is None:
            sys.exit(f"No user {args.user_email}; pass --user-email of an existing user.")
        user_id = user.id
        embedder = govuk.LocalBgeEmbedder(os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5"))

    failures = 0
    for document in DOCUMENTS:
        try:
            fetched = fetch(document)
        except Exception as exc:  # noqa: BLE001 — one bad document must not stop the rest
            print(f"FAIL  {document.url}: {type(exc).__name__}: {exc}")
            failures += 1
            continue
        if not fetched.passages:
            print(f"SKIP  {document.title}: no passages")
            failures += 1
            continue
        if args.dry_run:
            longest = max(len(p.content) for p in fetched.passages)
            print(f"{len(fetched.passages):4d} passages (longest {longest}) {document.title}")
            print("      first:", fetched.passages[0].content[:160])
            continue
        outcome = govuk.ingest(fetched, document.procedure, user_id, embedder, publisher=document.publisher)
        print(f"{outcome:28s} {len(fetched.passages):4d} passages {document.title}")
    if failures:
        sys.exit(f"{failures} official document(s) could not be refreshed")


if __name__ == "__main__":
    main()
