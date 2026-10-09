"""Kriton learns from feedback with no reviewer (learned_answers.py)."""
import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.domains.audit_ledger.models import AuditEvent
from app.orchestration import learned_answers
from app.orchestration.models import QueryAnswerRecord
from app.orchestration.reviewed_answers import LEARNED_PROVIDER, find_reviewed_answers

QUESTION = "What is the UK VAT registration threshold?"
GOOD = "You must register for VAT when taxable turnover exceeds £90,000 [REF-1]."
BAD = "The UK VAT registration threshold is £85,000."


@pytest.fixture
async def sessions():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
async def db(sessions):
    async with sessions() as session:
        yield session


async def _answer(db, query_id, *, question=QUESTION, text=GOOD, events=(("validation_completed", True), ("release_check_completed", True))):
    db.add(QueryAnswerRecord(query_id=query_id, tenant_id="t1", user_id="u1", question=question,
                             answer_text=text, external_evidence=[{"url": "https://www.gov.uk/vat-registration", "content": "Register above £90,000."}]))
    for name, passed in events:
        db.add(AuditEvent(event_name=name, emitting_service="orchestration", tenant_id="t1",
                          subject_type="query", subject_id=query_id, payload={"passed": passed, "requires_authority": True},
                          payload_hash="h", chain_hash="h"))
    await db.commit()


async def test_a_verified_answer_is_learned_on_thumbs_up_and_reused(db):
    await _answer(db, "q1")
    assert await learned_answers.learn_from_upvote(db, tenant_id="t1", user_id="u1", query_id="q1")
    [source] = await find_reviewed_answers(db, tenant_id="t1", question="What's the VAT registration threshold in the UK?")
    assert source.provider == LEARNED_PROVIDER and "£90,000" in source.snippet
    assert "[REF-1]" not in source.snippet  # the old answer's own citation numbers
    assert await find_reviewed_answers(db, tenant_id="t2", question=QUESTION) == []


async def test_a_thumbs_up_on_an_unverified_answer_teaches_nothing(db):
    await _answer(db, "q1", events=(("validation_completed", True), ("release_check_degraded", None)))
    assert not await learned_answers.learn_from_upvote(db, tenant_id="t1", user_id="u1", query_id="q1")
    assert await find_reviewed_answers(db, tenant_id="t1", question=QUESTION) == []


async def test_questions_with_the_users_own_figures_are_not_learned(db):
    question = "How much VAT is due on £12,000 of standard-rated UK sales?"
    await _answer(db, "q1", question=question, text="VAT due is £2,400.")
    assert not await learned_answers.learn_from_upvote(db, tenant_id="t1", user_id="u1", query_id="q1")
    assert learned_answers.learnable("What was the UK VAT threshold in 2023?")
    assert not learned_answers.learnable("What is the South Africa repo rate?")
    assert not learned_answers.learnable("Make it a bar chart")


async def test_thumbs_down_retires_the_answer_and_learns_a_verified_correction(db, sessions, monkeypatch):
    await _answer(db, "q1")
    await learned_answers.learn_from_upvote(db, tenant_id="t1", user_id="u1", query_id="q1")
    await _answer(db, "q2", text=BAD)

    @asynccontextmanager
    async def background_sessions(tenant_id, user_id):
        async with sessions() as session:
            yield session, None

    seen = {}

    async def runner(*, db, request, **_):
        seen["critique"] = learned_answers.correction_critique.get()
        await _answer(db, "q3", text=GOOD + " Registration is due within 30 days [REF-2].")
        return SimpleNamespace(outcome="answered", query_id="q3", source_bundle=None,
                               answer=SimpleNamespace(text=GOOD + " Registration is due within 30 days [REF-2]."))

    monkeypatch.setattr(learned_answers, "_background_sessions", background_sessions)
    assert await learned_answers.correct_after_downvote(
        db, runner, tenant_id="t1", user_id="u1", role="Analyst", query_id="q2",
        reasons=["wrong_answer"], comment="threshold changed",
    )
    assert await find_reviewed_answers(db, tenant_id="t1", question=QUESTION) == []  # retired at once
    await asyncio.gather(*learned_answers._tasks)

    assert "£85,000" in seen["critique"] and "the answer is wrong" in seen["critique"]
    [source] = await find_reviewed_answers(db, tenant_id="t1", question=QUESTION)
    assert "30 days" in source.snippet


async def test_a_correction_that_fails_verification_is_not_learned(db, sessions, monkeypatch):
    await _answer(db, "q2", text=BAD)

    @asynccontextmanager
    async def background_sessions(tenant_id, user_id):
        async with sessions() as session:
            yield session, None

    async def runner(*, db, **_):
        await _answer(db, "q3", text="Still £85,000.", events=(("validation_completed", False),))
        return SimpleNamespace(outcome="answered", query_id="q3", source_bundle=None,
                               answer=SimpleNamespace(text="Still £85,000."))

    monkeypatch.setattr(learned_answers, "_background_sessions", background_sessions)
    await learned_answers.correct_after_downvote(
        db, runner, tenant_id="t1", user_id="u1", role="Analyst", query_id="q2", reasons=[], comment="",
    )
    await asyncio.gather(*learned_answers._tasks)
    assert await find_reviewed_answers(db, tenant_id="t1", question=QUESTION) == []


async def test_validation_alone_cannot_authorize_learning(db):
    await _answer(db, "q1", events=(("validation_completed", True),))
    assert not await learned_answers.learn_from_upvote(db, tenant_id="t1", user_id="u1", query_id="q1")


async def test_numeric_downvote_starts_recheck_without_learning_private_figures(db, sessions, monkeypatch):
    question = "Calculate profit with revenue ₹500,000 and expenses ₹350,000."
    await _answer(db, "numeric", question=question, text="Profit ₹100,000.")
    seen = []

    @asynccontextmanager
    async def background_sessions(tenant_id, user_id):
        async with sessions() as session:
            yield session, None

    async def runner(*, request, **kwargs):
        seen.append(request.query)
        return SimpleNamespace(outcome="clarification_required", answer=None)

    monkeypatch.setattr(learned_answers, "_background_sessions", background_sessions)
    assert await learned_answers.correct_after_downvote(db, runner, tenant_id="t1", user_id="u1", role="Analyst", query_id="numeric", reasons=["wrong_calculation"], comment="Check subtraction")
    await asyncio.gather(*learned_answers._tasks)
    assert seen == [question]
    assert not learned_answers.learnable(question)


async def test_persisted_rejection_guidance_is_user_and_tenant_scoped(db):
    from app.orchestration.models import AnswerFeedback
    await _answer(db, "rejected", text=BAD)
    db.add(AnswerFeedback(tenant_id="t1", user_id="u1", query_id="rejected", rating="down", reasons=["wrong_answer"], comment="Check official threshold"))
    await db.commit()
    guidance = await learned_answers.feedback_guidance(db, tenant_id="t1", user_id="u1", question=QUESTION)
    assert BAD in guidance and "untrusted, not evidence" in guidance
    assert not await learned_answers.feedback_guidance(db, tenant_id="t2", user_id="u1", question=QUESTION)
    assert not await learned_answers.feedback_guidance(db, tenant_id="t1", user_id="u2", question=QUESTION)


async def test_memory_requires_unchanged_independent_evidence(db):
    from app.orchestration.reviewed_answers import safe_memory_guidance
    from app.orchestration.websearch import WebSource
    await _answer(db, "q1")
    assert await learned_answers.learn_from_upvote(db, tenant_id="t1", user_id="u1", query_id="q1")
    source = WebSource(title="Official guidance", url="https://www.gov.uk/vat-registration",
                       snippet="Register above £90,000.", provider="official")
    guidance = await safe_memory_guidance(db, tenant_id="t1", question=QUESTION, fresh_sources=[source])
    assert "not citable evidence" in guidance and "£90,000" in guidance
    assert "[REF-" not in guidance
    source.snippet = "Register above £100,000."
    assert await safe_memory_guidance(db, tenant_id="t1", question=QUESTION, fresh_sources=[source]) == ""
    assert await safe_memory_guidance(db, tenant_id="t1", question=QUESTION, fresh_sources=[]) == ""
    assert await safe_memory_guidance(db, tenant_id="t2", question=QUESTION, fresh_sources=[source]) == ""


async def test_memory_does_not_cross_historical_years(db):
    await _answer(db, "q1", question="What was the UK VAT registration threshold in 2023?")
    assert await learned_answers.learn_from_upvote(db, tenant_id="t1", user_id="u1", query_id="q1")
    assert await find_reviewed_answers(db, tenant_id="t1", question="What was the UK VAT registration threshold in 2026?") == []


async def test_missing_source_snapshot_is_not_learned(db):
    await _answer(db, "q1")
    record = await db.get(QueryAnswerRecord, "q1")
    record.external_evidence = []
    await db.commit()
    assert not await learned_answers.learn_from_upvote(db, tenant_id="t1", user_id="u1", query_id="q1")


async def test_evidence_gap_cannot_become_answer_memory(db):
    await _answer(db, "q1", text="The sources provided do not establish an answer to this.")
    assert not await learned_answers.learn_from_upvote(db, tenant_id="t1", user_id="u1", query_id="q1")


def test_a_redacted_snapshot_matches_its_fresh_source():
    """Saved evidence is redacted with a random placeholder; the fresh snippet
    of the same page must still fingerprint identically."""
    from app.orchestration.redaction import redact_for_external_exposure
    from app.orchestration.reviewed_answers import evidence_fingerprint

    url, page = "https://www.gov.uk/x", "Email frsapplications.vrs@hmrc.gov.uk to leave the scheme."
    saved = redact_for_external_exposure(page).redacted_text
    assert evidence_fingerprint(url, saved) == evidence_fingerprint(url, page)
    assert evidence_fingerprint(url, page) != evidence_fingerprint(url, page + " Changed.")


async def test_a_reworded_question_reuses_memory_when_its_evidence_is_unchanged(db):
    """A reworded question searches differently: one saved page back unchanged
    plus new pages is enough; any saved page back with changed text is not."""
    from app.orchestration.reviewed_answers import safe_memory_guidance
    from app.orchestration.websearch import WebSource
    await _answer(db, "q1")
    record = await db.get(QueryAnswerRecord, "q1")
    record.external_evidence = [*record.external_evidence,
                                {"url": "https://www.gov.uk/other", "content": "Other guidance."}]
    await db.commit()
    assert await learned_answers.learn_from_upvote(db, tenant_id="t1", user_id="u1", query_id="q1")
    unchanged = WebSource(title="g", url="https://www.gov.uk/vat-registration", snippet="Register above £90,000.")
    new_page = WebSource(title="n", url="https://www.gov.uk/new", snippet="Something new.")
    paraphrase = "What's the VAT registration threshold in the UK?"
    assert "£90,000" in await safe_memory_guidance(db, tenant_id="t1", question=paraphrase,
                                                   fresh_sources=[unchanged, new_page])
    changed = WebSource(title="o", url="https://www.gov.uk/other", snippet="Other guidance, revised.")
    assert await safe_memory_guidance(db, tenant_id="t1", question=paraphrase,
                                      fresh_sources=[unchanged, changed]) == ""
    assert await safe_memory_guidance(db, tenant_id="t1", question=paraphrase, fresh_sources=[new_page]) == ""


async def test_upvote_cannot_save_an_incomplete_company_comparison(db):
    question = 'Compare UK corporation tax at profits of £300,000 and £40,000.'
    result = await learned_answers.learn_answer(
        db, tenant_id='t1', question=question, answer_text='| £300,000 | 25% [REF-1] |',
        source_urls=['https://www.gov.uk/corporation-tax-rates'], origin='learned_upvote',
    )
    assert result is None
