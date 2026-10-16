"""Ingest official documents published as PDF (outside GOV.UK) into the
governed knowledge base.

    cd backend
    .venv/bin/python scripts/ingest_official.py --dry-run
    .venv/bin/python scripts/ingest_official.py

Each document is fetched over verified TLS only, split by its own structure
(numbered questions for an FAQ), and stored exactly as scripts/ingest_govuk.py
stores GOV.UK pages: an approved, versioned, rights-recorded source whose
changed content supersedes the old version.

Covers the India GST corpus and the UAE VAT basics. Each publisher has its
own rights gate (OfficialDocument.rights_env): a document is written only
after that publisher's reproduction rights are approved.

Deliberately NOT included:
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


UAE_GOVERNMENT = govuk.Publisher(
    name="UAE Government (u.ae)",
    jurisdiction_scope="United Arab Emirates,AE,UAE",
    reason_code="AE_GOV_PUBLICATION",
    terms=(
        "UAE Government official portal content. Reproduction for internal reference relied on; "
        "confirm with legal before production use."
    ),
)


IFRS_FOUNDATION = govuk.Publisher(
    name="IFRS Foundation",
    jurisdiction_scope="International,IFRS",
    reason_code="IFRS_FOUNDATION_STANDARD",
    terms=(
        "IFRS Accounting Standards are copyright of the IFRS Foundation. Reading them on ifrs.org is free; "
        "storing, indexing and reproducing them in a product requires a licence from the IFRS Foundation. "
        "Do not set IFRS_INGESTION_RIGHTS_APPROVED until that licence is confirmed."
    ),
)
_IFRS_HTML = "https://www.ifrs.org/content/dam/ifrs/publications/html-standards/english/2026/issued/{}.html"


@dataclass(frozen=True)
class OfficialDocument:
    url: str
    title: str
    publisher: govuk.Publisher
    published: datetime
    procedure: str = "general"
    # "faq_pdf": numbered questions; "pdf": paragraphs; "html": h2/h3 sections;
    # "ifrs_html": a standard split at its own paragraph numbers (pinpoint "¶33").
    kind: str = "faq_pdf"
    rights_env: str = "GST_INGESTION_RIGHTS_APPROVED"


DOCUMENTS: list[OfficialDocument] = [
    OfficialDocument(
        url="https://gstcouncil.gov.in/sites/default/files/2025-09/faq_0.pdf",
        title="FAQs on GST rate changes (GST Council, September 2025)",
        publisher=GST_COUNCIL,
        # Changes recommended at the 56th GST Council meeting, effective 22 September 2025.
        published=datetime(2025, 9, 22, tzinfo=timezone.utc),
    ),
    # The registration thresholds (₹40/20/10 lakh by supply type and State):
    # no governed source stated them, so "What is the GST registration
    # threshold in India?" was answered "the sources do not state this".
    OfficialDocument(
        url="https://gstcouncil.gov.in/sites/default/files/e-version-gst-flyers/Registration_under_GST_Law_new.pdf",
        title="Registration under GST Law (GST Council flyer)",
        publisher=GST_COUNCIL,
        published=datetime(2019, 4, 1, tzinfo=timezone.utc),
        kind="pdf",
    ),
    # The UAE VAT rate and registration threshold; the FTA's own pages carry
    # the rate only inside a calculator widget.
    OfficialDocument(
        url="https://u.ae/en/information-and-services/finance-and-investment/taxation/vat/valueaddedtaxvat",
        title="Value added tax (VAT) — The Official Portal of the UAE Government",
        publisher=UAE_GOVERNMENT,
        published=datetime(2018, 1, 1, tzinfo=timezone.utc),
        kind="html",
        rights_env="UAE_INGESTION_RIGHTS_APPROVED",
    ),
    # IFRS standards: the governed library held none, so IFRS 18 / IAS 2
    # questions rested on web search alone. IAS 1 is not listed: the IFRS
    # Foundation no longer publishes its text (superseded by IFRS 18).
    OfficialDocument(
        url=_IFRS_HTML.format("ifrs18"),
        title="IFRS 18 Presentation and Disclosure in Financial Statements (issued April 2024; effective for "
              "annual periods beginning on or after 1 January 2027, earlier application permitted)",
        publisher=IFRS_FOUNDATION, published=datetime(2024, 4, 9, tzinfo=timezone.utc),
        kind="ifrs_html", rights_env="IFRS_INGESTION_RIGHTS_APPROVED",
    ),
    OfficialDocument(
        url=_IFRS_HTML.format("ias2"), title="IAS 2 Inventories (IFRS Foundation, 2026 issued edition)",
        publisher=IFRS_FOUNDATION, published=datetime(2026, 1, 1, tzinfo=timezone.utc),
        kind="ifrs_html", rights_env="IFRS_INGESTION_RIGHTS_APPROVED",
    ),
    OfficialDocument(
        url=_IFRS_HTML.format("ias7"), title="IAS 7 Statement of Cash Flows (IFRS Foundation, 2026 issued edition)",
        publisher=IFRS_FOUNDATION, published=datetime(2026, 1, 1, tzinfo=timezone.utc),
        kind="ifrs_html", rights_env="IFRS_INGESTION_RIGHTS_APPROVED",
    ),
]

# "33 | …" in the body; "B139 | …" and "C1 | …" in the appendices (the
# effective date is IFRS 18 C1 — without the letter prefix it fell into ¶131).
_IFRS_PARAGRAPH = re.compile(r"(?:^|\s)([A-Z]{0,2}\d{1,3}[A-Z]{0,2})\s\|\s")
_IFRS_MAX_PASSAGE = 2500


def split_ifrs_paragraphs(text: str, title: str, url: str) -> list:
    """One passage per numbered paragraph ("33 | When the circumstances…"),
    located as url#p33 so a citation can name the paragraph. A paragraph
    longer than the embedder can use is split into parts (#p33/2)."""
    marks = list(_IFRS_PARAGRAPH.finditer(text))
    passages = []
    for index, mark in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) else len(text)
        body = " ".join(text[mark.end():end].split())
        if len(body) < 40:
            continue
        number = mark.group(1)
        pieces = [body[i:i + _IFRS_MAX_PASSAGE] for i in range(0, len(body), _IFRS_MAX_PASSAGE)]
        for part, piece in enumerate(pieces):
            passages.append(govuk.Passage(
                locator=f"{url}#p{number}" + (f"/{part + 1}" if part else ""),
                heading=f"{title.split(' (')[0]} ¶{number}",
                content=f"{title.split(' (')[0]} paragraph {number}: {piece}",
            ))
    return passages

_QUESTION = re.compile(r"(?m)^\s*(\d{1,3})\.\s+(?=\S)")


def _get(url: str) -> httpx.Response:
    # verify=True is httpx's default and is relied on: see the module docstring.
    ca_bundle = os.getenv("OFFICIAL_DOCUMENT_CA_BUNDLE")
    verified_tls = ssl.create_default_context(cafile=ca_bundle) if ca_bundle else True
    response = httpx.get(url, timeout=60, follow_redirects=True, verify=verified_tls,
                         headers={"User-Agent": "Mozilla/5.0 (compatible; KritonResearch/1.0)"})
    response.raise_for_status()
    return response


def _pdf_text(url: str) -> str:
    reader = PdfReader(io.BytesIO(_get(url).content))
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


def split_paragraphs(text: str, title: str, url: str) -> list:
    """A document without numbered questions: passages of whole lines, each
    headed by the document title."""
    lines = [" ".join(line.split()) for line in text.splitlines()]
    body = "\n".join(line for line in lines if line)
    return [
        govuk.Passage(locator=f"{url}#p{index + 1}", heading=title, content=f"{title} — {piece}")
        for index, piece in enumerate(govuk._split_long(body)) if len(piece) >= 40
    ]


_MAIN = re.compile(r"<main\b[^>]*>(.*?)</main>", re.S | re.I)


def fetch(document: OfficialDocument):
    if document.kind == "ifrs_html":
        from app.orchestration.websearch import _html_to_text
        text = _html_to_text(_get(document.url).text)
        passages = split_ifrs_paragraphs(text, document.title, document.url)
    elif document.kind == "html":
        html = _get(document.url).text
        main = _MAIN.search(html)
        text = main.group(1) if main else html
        passages = govuk._sections(text, document.url, "", document.title)
    else:
        text = _pdf_text(document.url)
        split = split_numbered_questions if document.kind == "faq_pdf" else split_paragraphs
        passages = split(text, document.title, document.url)
    return govuk.Document(
        path=document.url, title=document.title, url=document.url, updated=document.published,
        body_hash=hashlib.sha256(f"chunker:{govuk.CHUNKER_VERSION}\n{text}".encode()).hexdigest(),
        passages=passages,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="fetch and split only; write nothing")
    parser.add_argument("--user-email", default="dashboard@zoikologia.com")
    args = parser.parse_args()

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
        if not args.dry_run and os.getenv(document.rights_env, "").lower() != "true":
            print(f"SKIP  {document.title}: set {document.rights_env}=true after source rights approval")
            continue
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
