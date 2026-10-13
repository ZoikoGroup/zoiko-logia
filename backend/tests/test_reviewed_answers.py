"""Reviewer-approved answers are reused for the same question (reviewed_answers.py)."""
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.orchestration import review
from app.orchestration.persisted_objects import create_review_case
from app.orchestration.reviewed_answers import REVIEWED_PROVIDER, find_reviewed_answers


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    await engine.dispose()


async def _correct(db, tenant, question, answer, facts):
    case = await create_review_case(
        db, query_id=f"q-{tenant}-{abs(hash(question))}", correlation_id="c", tenant_id=tenant, risk_level="LOW",
        confidence_state="limited", reason="User reported: wrong_answer", query_text=question,
        draft_answer="The threshold is £85,000.",
    )
    await review.resolve_review_case(
        db, tenant_id=tenant, case_id=case.id, reviewer_id="reviewer", decision="corrected",
        corrected_answer=answer, key_facts=facts, category="reasoning",
    )


async def test_a_correction_is_reused_for_the_same_question(db):
    await _correct(db, "t1", "What is the UK VAT registration threshold?",
                   "You must register when taxable turnover exceeds £90,000.", ["£90,000"])
    [source] = await find_reviewed_answers(db, tenant_id="t1", question="What is the UK VAT registration threshold")
    assert source.provider == REVIEWED_PROVIDER
    assert "£90,000" in source.snippet and "Reviewer-approved answer" in source.snippet


async def test_another_tenants_corrections_are_never_used(db):
    await _correct(db, "t1", "What is the UK VAT registration threshold?",
                   "You must register when taxable turnover exceeds £90,000.", ["£90,000"])
    assert await find_reviewed_answers(db, tenant_id="t2", question="What is the UK VAT registration threshold?") == []


async def test_an_opposite_question_does_not_reuse_the_answer(db):
    await _correct(db, "t1", "What is the UK VAT registration threshold?",
                   "You must register when taxable turnover exceeds £90,000.", ["£90,000"])
    assert await find_reviewed_answers(db, tenant_id="t1", question="What is the UK VAT deregistration threshold?") == []


async def test_an_unrelated_question_gets_no_reviewed_answer(db):
    await _correct(db, "t1", "What is the UK VAT registration threshold?",
                   "You must register when taxable turnover exceeds £90,000.", ["£90,000"])
    assert await find_reviewed_answers(db, tenant_id="t1", question="How long must I keep VAT records?") == []


async def test_a_reviewer_correction_is_used_as_memory_guidance(db):
    """Corrections cite governed versions, never web snapshots; requiring
    snapshots meant a reviewer's correction was never reused."""
    from app.orchestration.reviewed_answers import safe_memory_guidance

    await _correct(db, "t1", "What is the UK VAT registration threshold?",
                   "You must register when taxable turnover exceeds £90,000.", ["£90,000"])
    guidance = await safe_memory_guidance(db, tenant_id="t1", question="What is the UK VAT registration threshold?",
                                          fresh_sources=[])
    assert "£90,000" in guidance and "not citable evidence" in guidance
