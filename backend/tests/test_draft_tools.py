"""Drafts & Reports: delete, sources and export are owner-scoped, and export
produces real Word/PDF/Markdown files (app/domains/kriton_workspace/draft_tools.py)."""
import io

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.domains.audit_ledger.models import AuditEvent
from app.domains.identity.models import Tenant, User
from app.domains.kriton_workspace.draft_tools import delete_draft, draft_sources, export_draft, export_filename
from app.domains.kriton_workspace.models import Draft, SavedAnswer
from app.domains.kriton_workspace.router import export_draft_file, remove_draft
from app.orchestration.models import QueryAnswerRecord

CONTENT = "## Summary\n\nThe UK VAT registration threshold is £90,000.\n\n- Applies to taxable turnover\n- Rolling 12 months\n"


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        session.add_all([
            Tenant(id="t1", name="T"), Tenant(id="t2", name="Other"),
            SavedAnswer(id="sa1", tenant_id="t1", user_id="u1", query_id="q1", query_text="UK VAT threshold?",
                        answer_text=CONTENT, risk_level="LOW"),
            QueryAnswerRecord(query_id="q1", tenant_id="t1", user_id="u1", question="UK VAT threshold?", answer_text=CONTENT,
                              external_evidence=[
                                  {"title": "VAT registration", "url": "https://www.gov.uk/vat-registration"},
                                  {"title": "VAT registration (dup)", "url": "https://www.gov.uk/vat-registration"},
                                  {"title": "Not web", "url": None},
                              ]),
            Draft(id="d1", tenant_id="t1", user_id="u1", title="VAT memo: client A", content=CONTENT, saved_answer_id="sa1"),
            Draft(id="d-blank", tenant_id="t1", user_id="u1", title="Blank", content=""),
            Draft(id="d-other", tenant_id="t1", user_id="u2", title="Not mine", content="x"),
        ])
        await session.commit()
        yield session
    await engine.dispose()


async def test_sources_come_from_the_answer_the_draft_was_made_from_once_per_url(db):
    assert await draft_sources(db, "t1", "u1", "d1") == [
        {"title": "VAT registration", "url": "https://www.gov.uk/vat-registration"},
    ]
    assert await draft_sources(db, "t1", "u1", "d-blank") == []


async def test_another_users_or_tenants_draft_is_not_found(db):
    for call in (
        lambda: draft_sources(db, "t1", "u1", "d-other"),
        lambda: delete_draft(db, "t1", "u1", "d-other"),
        lambda: export_draft(db, "t2", "u1", "d1", "md"),
    ):
        with pytest.raises(HTTPException) as err:
            await call()
        assert err.value.status_code == 404
    assert await db.get(Draft, "d-other") is not None


@pytest.mark.parametrize("fmt", ["docx", "pdf", "md"])
async def test_export_builds_a_valid_file_with_the_sources(db, fmt):
    content, filename, mime, _ = await export_draft(db, "t1", "u1", "d1", fmt)
    assert filename == f"VAT memo client A.{fmt}"
    if fmt == "docx":
        from docx import Document
        text = "\n".join(p.text for p in Document(io.BytesIO(content)).paragraphs)
        assert "£90,000" in text and "gov.uk/vat-registration" in text
        assert mime.endswith("wordprocessingml.document")
    elif fmt == "pdf":
        from pypdf import PdfReader
        text = "".join(page.extract_text() for page in PdfReader(io.BytesIO(content)).pages)
        assert "90,000" in text and mime == "application/pdf"
    else:
        text = content.decode("utf-8")
        assert text.startswith("# VAT memo: client A") and "## Sources" in text and "£90,000" in text


async def test_export_rejects_unknown_formats_and_empty_drafts(db):
    for draft_id, fmt in (("d1", "exe"), ("d-blank", "docx")):
        with pytest.raises(HTTPException) as err:
            await export_draft(db, "t1", "u1", draft_id, fmt)
        assert err.value.status_code == 422


async def test_delete_endpoint_removes_the_draft_and_records_it(db):
    user = User(id="u1", tenant_id="t1", email="u1@example.com", full_name="U1", role="Admin")
    response = await remove_draft("d1", db=db, current_user=user)
    assert response.status_code == 204
    assert await db.get(Draft, "d1") is None
    event = (await db.execute(select(AuditEvent).where(AuditEvent.event_name == "kriton_workspace.draft_deleted"))).scalar_one()
    assert event.subject_id == "d1" and event.actor_id == "u1"


async def test_export_endpoint_returns_an_attachment(db):
    user = User(id="u1", tenant_id="t1", email="u1@example.com", full_name="U1", role="Admin")
    response = await export_draft_file("d1", format="MD", db=db, current_user=user)
    assert response.media_type.startswith("text/markdown")
    assert response.headers["content-disposition"] == 'attachment; filename="VAT memo client A.md"'


async def test_export_drops_citation_markers_and_undrawable_characters(db):
    draft = await db.get(Draft, "d1")
    draft.content = "The threshold is £90,000 in a 12‑month period[REF-1]. Register once exceeded [REF-7]."
    await db.commit()
    content, *_ = await export_draft(db, "t1", "u1", "d1", "md")
    text = content.decode("utf-8")
    assert "12-month period. Register once exceeded." in text and "REF-" not in text


def test_export_filename_strips_unsafe_characters():
    assert export_filename('Q2 / "final" <memo>', "pdf") == "Q2  final memo.pdf"
    assert export_filename("///", "md") == "draft.md"
