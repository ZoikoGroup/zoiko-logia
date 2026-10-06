"""The review loop: user feedback and escalations reach a reviewer, and
reviewed answers become gold evaluation cases (app/orchestration/review.py)."""
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.domains.evaluation.models import BenchmarkCase
from app.domains.identity.permissions import REVIEW_READ, REVIEW_RESOLVE, permissions_for_role
from app.orchestration import review
from app.orchestration.models import AnswerFeedback
from app.orchestration.persisted_objects import create_review_case


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    await engine.dispose()


async def test_thumbs_down_opens_a_review_case_with_the_answer_the_user_saw(db):
    await review.record_answer(db, query_id="q1", tenant_id="t1", user_id="u1",
        question="What is the late payment penalty for VAT?", answer_text="It is 2% at day 15.", external_evidence=[])
    feedback = await review.record_feedback(
        db, tenant_id="t1", user_id="u1", query_id="q1", rating="down",
        reasons=["outdated", "wrong_answer", "not-a-reason"], comment="Rate changed in April",
        question="What is the late payment penalty for VAT?", answer_text="It is 2% at day 15.",
    )
    assert feedback.reasons == ["outdated", "wrong_answer"]  # unknown reasons dropped
    [case] = await review.list_review_cases(db, tenant_id="t1")
    assert feedback.review_case_id == case.id
    assert case.source == "user_feedback" and case.status == "open"
    assert case.draft_answer == "It is 2% at day 15."
    assert "outdated, wrong_answer" in case.reason and "Rate changed in April" in case.reason


async def test_repeated_thumbs_down_reuses_the_open_review_case(db):
    await review.record_answer(db, query_id="q1", tenant_id="t1", user_id="u1", question="q", answer_text="a", external_evidence=[])
    first, second = [
        await review.record_feedback(
            db, tenant_id="t1", user_id="u1", query_id="q1", rating="down", reasons=["wrong_answer"],
            comment="", question="q", answer_text="a",
        )
        for _ in range(2)
    ]
    [case] = await review.list_review_cases(db, tenant_id="t1")
    assert first.review_case_id == second.review_case_id == case.id


async def test_thumbs_up_is_recorded_without_a_review_case(db):
    await review.record_answer(db, query_id="q1", tenant_id="t1", user_id="u1", question="q", answer_text="a", external_evidence=[])
    feedback = await review.record_feedback(
        db, tenant_id="t1", user_id="u1", query_id="q1", rating="up", reasons=[], comment="",
        question="q", answer_text="a",
    )
    assert feedback.review_case_id is None
    assert await review.list_review_cases(db, tenant_id="t1") == []
    assert (await db.execute(select(AnswerFeedback))).scalar_one().rating == "up"


async def test_a_correction_becomes_a_gold_case_with_the_reviewers_key_facts(db):
    case = await create_review_case(
        db, query_id="q2", correlation_id="c2", tenant_id="t1", risk_level="LOW",
        confidence_state="limited", reason="Composition rejected", query_text="When must I leave cash accounting?",
        draft_answer="When turnover exceeds £1.35 million.",
    )
    resolved, gold = await review.resolve_review_case(
        db, tenant_id="t1", case_id=case.id, reviewer_id="reviewer", decision="corrected",
        corrected_answer="You must leave if your VAT taxable turnover is more than £1.6 million.",
        key_facts=["£1.6 million", " "], note="Join limit given as exit limit",
    )
    assert resolved.status == "resolved" and resolved.reviewer_decision == "corrected"
    assert resolved.reviewer_id == "reviewer" and resolved.resolved_at is not None
    stored = (await db.execute(select(BenchmarkCase).where(BenchmarkCase.id == gold.id))).scalar_one()
    assert stored.dataset_id == f"{review.GOLD_DATASET_ID}:t1"
    assert stored.gold_answer.startswith("You must leave") and stored.key_facts == ["£1.6 million"]
    assert await review.review_counts(db, tenant_id="t1") == {"resolved": 1}


async def test_approving_keeps_the_draft_and_rejecting_creates_no_gold_case(db):
    approve = await create_review_case(
        db, query_id="q3", correlation_id="c3", tenant_id="t1", risk_level="LOW", confidence_state="limited",
        reason="r", query_text="UK VAT registration threshold?", draft_answer="£90,000.",
    )
    _, gold = await review.resolve_review_case(
        db, tenant_id="t1", case_id=approve.id, reviewer_id="r", decision="approved", key_facts=["90,000"],
    )
    assert gold.gold_answer == "£90,000."
    reject = await create_review_case(
        db, query_id="q4", correlation_id="c4", tenant_id="t1", risk_level="LOW", confidence_state="limited",
        reason="r", query_text="q", draft_answer="a",
    )
    _, none = await review.resolve_review_case(db, tenant_id="t1", case_id=reject.id, reviewer_id="r", decision="rejected", note="Report rejected")
    assert none is None


@pytest.mark.parametrize("decision, kwargs, message", [
    ("corrected", {}, "needs the corrected answer"),
    ("maybe", {}, "Unknown decision"),
])
async def test_invalid_resolutions_are_refused(db, decision, kwargs, message):
    case = await create_review_case(
        db, query_id="q5", correlation_id="c5", tenant_id="t1", risk_level="LOW", confidence_state="limited",
        reason="r", query_text="q", draft_answer="a",
    )
    with pytest.raises(review.ReviewError, match=message):
        await review.resolve_review_case(db, tenant_id="t1", case_id=case.id, reviewer_id="r", decision=decision, **kwargs)


async def test_a_case_is_resolved_once_and_only_within_its_tenant(db):
    case = await create_review_case(
        db, query_id="q6", correlation_id="c6", tenant_id="t1", risk_level="LOW", confidence_state="limited",
        reason="r", query_text="q", draft_answer="a",
    )
    with pytest.raises(review.ReviewError, match="not found"):
        await review.resolve_review_case(db, tenant_id="other-tenant", case_id=case.id, reviewer_id="r", decision="rejected", note="Report rejected")
    await review.resolve_review_case(db, tenant_id="t1", case_id=case.id, reviewer_id="r", decision="rejected", note="Report rejected")
    with pytest.raises(review.ReviewError, match="already resolved"):
        await review.resolve_review_case(db, tenant_id="t1", case_id=case.id, reviewer_id="r", decision="rejected", note="Report rejected")
    assert await review.list_review_cases(db, tenant_id="other-tenant", status="all") == []


def test_only_designated_roles_can_review():
    assert REVIEW_RESOLVE in permissions_for_role("Risk Admin")
    assert REVIEW_READ in permissions_for_role("System Auditor")
    assert REVIEW_RESOLVE not in permissions_for_role("System Auditor")
    assert REVIEW_READ not in permissions_for_role("Source Admin")

@pytest.mark.parametrize("facts, message", [([], "at least one key fact"), (["99%"], "must appear")])
async def test_gold_approval_requires_meaningful_facts(db, facts, message):
    case = await create_review_case(db, query_id="facts", correlation_id="facts", tenant_id="t1", risk_level="LOW",
                                    confidence_state="limited", reason="r", query_text="Rate?", draft_answer="The rate is 20%.")
    with pytest.raises(review.ReviewError, match=message):
        await review.resolve_review_case(db, tenant_id="t1", case_id=case.id, reviewer_id="r", decision="approved", key_facts=facts)
    assert case.status == "open"


async def test_requesting_evidence_keeps_case_actionable_and_creates_no_gold(db):
    case = await create_review_case(db, query_id="evidence", correlation_id="evidence", tenant_id="t1", risk_level="LOW",
                                    confidence_state="limited", reason="r", query_text="Rate?", draft_answer="20%.")
    pending, gold = await review.resolve_review_case(db, tenant_id="t1", case_id=case.id, reviewer_id="r",
                                                    decision="needs_evidence", note="Retrieve the official notice")
    assert gold is None and pending.status == "needs_evidence" and pending.resolved_at is None
    resolved, gold = await review.resolve_review_case(db, tenant_id="t1", case_id=case.id, reviewer_id="r",
                                                     decision="corrected", corrected_answer="The rate is 5%.", key_facts=["5%"], category="citation")
    assert resolved.status == "resolved" and gold.tenant_id == "t1" and gold.category == "citation"


async def test_evidence_for_another_tenant_case_is_unavailable(db):
    case = await create_review_case(db, query_id="private", correlation_id="private", tenant_id="t1", risk_level="LOW",
                                    confidence_state="limited", reason="r", query_text="q")
    with pytest.raises(review.ReviewError, match="not found"):
        await review.review_evidence(db, tenant_id="other", case_id=case.id)

async def test_feedback_cannot_replace_server_answer_or_cross_user_boundary(db):
    await review.record_answer(db, query_id="trusted", tenant_id="t1", user_id="u1",
                              question="Actual question", answer_text="Actual answer", external_evidence=[])
    feedback = await review.record_feedback(db, tenant_id="t1", user_id="u1", query_id="trusted", rating="down",
                                            reasons=[], comment="", question="Forged question", answer_text="Forged answer")
    cases = await review.list_review_cases(db, tenant_id="t1")
    case = next(c for c in cases if c.id == feedback.review_case_id)
    assert case.query_text == "Actual question" and case.draft_answer == "Actual answer"
    with pytest.raises(review.ReviewError, match="not found"):
        await review.record_feedback(db, tenant_id="t1", user_id="other", query_id="trusted", rating="up",
                                    reasons=[], comment="", question="", answer_text="")
