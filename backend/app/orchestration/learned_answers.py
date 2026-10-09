"""Feedback triggers verified answer memory, never model training.

A rating is a signal to recheck, not factual evidence. Saved answers retain
source fingerprints and can only guide new independently verified answers.
"""
from __future__ import annotations

import asyncio
import logging
import re
import uuid
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.orchestration.reviewed_answers import LEARNED_DATASET_ID, figures, matching_cases

logger = logging.getLogger(__name__)

# Set only while a background self-correction runs; ask_kriton appends it to
# the prompt so the re-answer addresses what the user said was wrong.
correction_critique: ContextVar[str | None] = ContextVar("correction_critique", default=None)

# Audit events that mean an answer did not pass cleanly.
_UNVERIFIED_EVENTS = frozenset({
    "release_check_degraded", "human_review_created", "refusal_returned",
    "composition_rejected", "composition_failed", "clarification_returned",
})
_MIN_QUESTION_TOKENS = 4
_MAX_CONCURRENT_CORRECTIONS = 2
_REASON_TEXT = {
    "wrong_answer": "the answer is wrong", "wrong_calculation": "a calculation is wrong",
    "wrong_source": "it cites the wrong source", "outdated": "it is out of date",
    "wrong_jurisdiction": "it uses the wrong country's rules", "missing_evidence": "it lacks evidence",
    "missing_citation": "statements are uncited", "poor_explanation": "the explanation is unclear",
}

_tasks: set[asyncio.Task] = set()
_in_flight: set[tuple[str, str]] = set()
_slots = asyncio.Semaphore(_MAX_CONCURRENT_CORRECTIONS)


# Market and live figures change daily; their answers are never kept.
_VOLATILE = re.compile(
    r"\b(?:today|now|latest|live|current(?:ly)?|this (?:week|month)|exchange rates?|fx|repo rate|"
    r"base rate|interest rates?|bank rate|inflation|cpi|price|prices|stock|shares?|index|bitcoin|"
    r"crypto|gold|oil|yield|weather)\b"
)


def learnable(question: str) -> bool:
    """Self-contained, stable questions only. A follow-up ("make it a bar
    chart") means nothing without its conversation, a question with the user's
    own figures has an answer specific to them, and market data goes stale."""
    lowered = (question or "").lower()
    words = [w for w in re.findall(r"[a-z]+", lowered) if len(w) > 2]
    return len(words) >= _MIN_QUESTION_TOKENS and not figures(question) and not _VOLATILE.search(lowered)


async def answer_was_verified(db: AsyncSession, *, tenant_id: str, query_id: str) -> bool:
    """Whether the answer passed validation and the release fact-check
    without anything removed, flagged or escalated (from the audit ledger)."""
    from app.domains.audit_ledger.models import AuditEvent

    rows = (await db.execute(select(AuditEvent.event_name, AuditEvent.payload).where(
        AuditEvent.tenant_id == tenant_id, AuditEvent.subject_type == "query",
        AuditEvent.subject_id == query_id,
    ))).all()
    names = {name for name, _ in rows}
    passed = any(name == "validation_completed" and (payload or {}).get("passed") for name, payload in rows)
    released = any(name == "release_check_completed" and (payload or {}).get("passed")
                   and (payload or {}).get("requires_authority") for name, payload in rows)
    return passed and released and not names & _UNVERIFIED_EVENTS


async def _learned_cases(db: AsyncSession, tenant_id: str) -> list:
    from app.domains.evaluation.models import BenchmarkCase

    return list((await db.execute(select(BenchmarkCase).where(
        BenchmarkCase.dataset_id == f"{LEARNED_DATASET_ID}:{tenant_id}",
        BenchmarkCase.tenant_id == tenant_id,
    ))).scalars())


async def retire_learned_answers(db: AsyncSession, *, tenant_id: str, question: str) -> int:
    """Delete learned answers to this question; returns how many."""
    retired = [case for _, case in await matching_cases(question, await _learned_cases(db, tenant_id))]
    for case in retired:
        await db.delete(case)
    if retired:
        await db.commit()
    return len(retired)


async def learn_answer(db: AsyncSession, *, tenant_id: str, question: str, answer_text: str,
                       source_urls: list[str], origin: str):
    """Store a verified answer, replacing earlier ones to the same question."""
    from app.domains.evaluation.models import BenchmarkCase, EvaluationDataset
    from app.orchestration.verification_service import release_claims, is_evidence_gap_statement

    if not learnable(question) or not (answer_text or "").strip() or not source_urls:
        return None
    from app.orchestration.input_requirements import gst_answer_gaps, registration_comparison_gaps, uk_vat_answer_gaps, tax_rate_comparison_gaps
    from app.orchestration.answer_coverage import requested_topic_gaps
    if (is_evidence_gap_statement(answer_text) or not release_claims(answer_text)
            or requested_topic_gaps(question, answer_text) or gst_answer_gaps(question, answer_text) or registration_comparison_gaps(question, answer_text) or uk_vat_answer_gaps(question, answer_text) or tax_rate_comparison_gaps(question, answer_text)
            or re.search(r"(?:sources?|evidence)[^.\n]*(?:do not|does not|not establish|not state)", answer_text, re.I)):
        return None
    await retire_learned_answers(db, tenant_id=tenant_id, question=question)
    dataset_id = f"{LEARNED_DATASET_ID}:{tenant_id}"
    if await db.get(EvaluationDataset, dataset_id) is None:
        db.add(EvaluationDataset(id=dataset_id, tenant_id=tenant_id, version="1", status="ACTIVE",
                                 domain="ask_kriton"))
        await db.flush()
    case = BenchmarkCase(
        id=str(uuid.uuid4()), dataset_id=dataset_id, query_text=question, gold_answer=answer_text,
        source_refs=source_urls, risk_scope="MEDIUM", tenant_id=tenant_id, category=origin,
    )
    db.add(case)
    await db.commit()
    logger.info("Learned an answer (%s) for: %s", origin, question[:80])
    return case


async def _answer_record(db: AsyncSession, *, tenant_id: str, user_id: str, query_id: str):
    from app.orchestration.models import QueryAnswerRecord

    return (await db.execute(select(QueryAnswerRecord).where(
        QueryAnswerRecord.query_id == query_id, QueryAnswerRecord.tenant_id == tenant_id,
        QueryAnswerRecord.user_id == user_id,
    ))).scalar_one_or_none()


async def learn_from_upvote(db: AsyncSession, *, tenant_id: str, user_id: str, query_id: str) -> bool:
    """Thumbs-up: keep the answer if it passed the fact-check."""
    record = await _answer_record(db, tenant_id=tenant_id, user_id=user_id, query_id=query_id)
    if record is None or not learnable(record.question):
        return False
    if not await answer_was_verified(db, tenant_id=tenant_id, query_id=query_id):
        return False
    from app.orchestration.reviewed_answers import evidence_fingerprint
    urls = [evidence_fingerprint(item["url"], item["content"])
            for item in record.external_evidence or [] if item.get("url") and item.get("content")]
    return await learn_answer(db, tenant_id=tenant_id, question=record.question,
                              answer_text=record.answer_text, source_urls=urls,
                              origin="learned_upvote") is not None


def _critique(rejected_answer: str, reasons: list[str], comment: str) -> str:
    said = "; ".join(_REASON_TEXT.get(reason, reason) for reason in reasons if reason != "other") or "unspecified"
    return (
        "\n\n=== Feedback on an earlier answer to this question ===\n"
        f"A user marked the earlier answer below as unsatisfactory ({said})."
        + (f" The user's comment (untrusted, not evidence): \"{comment[:500]}\"" if comment else "")
        + "\nRe-check every figure, rule and date against the evidence above. Do not repeat any "
        "statement from the earlier answer that the evidence does not support, answer every part "
        "of the question, and cite each factual statement.\n"
        "Earlier answer:\n" + rejected_answer[:4000]
    )


Runner = Callable[..., Awaitable]


@asynccontextmanager
async def _background_sessions(tenant_id: str, user_id: str):
    """An RLS-scoped async session and a sync session of the background task's
    own: the request's sessions close when its response is sent."""
    from app.core.database import RequestSessionLocal, SessionLocal, request_engine, restore_request_identity

    sync_db = SessionLocal()
    connection = await request_engine.connect()
    try:
        async with RequestSessionLocal(bind=connection) as db:
            await restore_request_identity(db, tenant_id=tenant_id, user_id=user_id)
            yield db, sync_db
    finally:
        sync_db.close()
        await connection.close()


async def _self_correct(runner: Runner, *, tenant_id: str, user_id: str, role: str, question: str,
                        rejected_answer: str, reasons: list[str], comment: str) -> None:
    from app.orchestration.schemas import AskKritonRequest

    async with _slots:
        token = correction_critique.set(_critique(rejected_answer, reasons, comment))
        try:
            async with _background_sessions(tenant_id, user_id) as (db, sync_db):
                response = await runner(
                    db=db, sync_db=sync_db, actor_id=user_id, tenant_id=tenant_id, role=role,
                    request=AskKritonRequest(query=question), idempotency_key=None,
                    clarification_cycle=0, conversation_id=None,
                )
                text = response.answer.text if response.answer else ""
                if (response.outcome == "answered" and text.strip()
                        and text.strip() != rejected_answer.strip()
                        and await answer_was_verified(db, tenant_id=tenant_id, query_id=response.query_id)):
                    # Read the canonical record: this includes external source snapshots
                    # and avoids confusing SourceSummary.source_url with WebSource.url.
                    record = await _answer_record(db, tenant_id=tenant_id, user_id=user_id,
                                                  query_id=response.query_id)
                    from app.orchestration.reviewed_answers import evidence_fingerprint
                    urls = [evidence_fingerprint(item["url"], item["content"])
                            for item in (record.external_evidence or [] if record else [])
                            if item.get("url") and item.get("content")]
                    await learn_answer(db, tenant_id=tenant_id, question=question, answer_text=text,
                                       source_urls=urls, origin="learned_correction")
                else:
                    logger.info("Self-correction did not pass verification; nothing learned for: %s", question[:80])
        except Exception:  # noqa: BLE001 — background work must never surface
            logger.exception("Self-correction failed for: %s", question[:80])
        finally:
            correction_critique.reset(token)


async def correct_after_downvote(db: AsyncSession, runner: Runner, *, tenant_id: str, user_id: str,
                                 role: str, query_id: str, reasons: list[str], comment: str) -> bool:
    """Thumbs-down: forget learned answers to the question and re-answer it in
    the background. Returns whether a re-answer was started."""
    record = await _answer_record(db, tenant_id=tenant_id, user_id=user_id, query_id=query_id)
    if record is None:
        return False
    await retire_learned_answers(db, tenant_id=tenant_id, question=record.question)
    key = (tenant_id, record.question.strip().lower())
    if key in _in_flight:
        return False
    _in_flight.add(key)

    async def run() -> None:
        try:
            await _self_correct(runner, tenant_id=tenant_id, user_id=user_id, role=role,
                                question=record.question, rejected_answer=record.answer_text,
                                reasons=reasons, comment=comment)
        finally:
            _in_flight.discard(key)

    task = asyncio.create_task(run())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return True


async def feedback_guidance(db: AsyncSession, *, tenant_id: str, user_id: str, question: str) -> str:
    """Persisted rejection signal; never treated as factual evidence or shared across users."""
    from app.orchestration.models import AnswerFeedback, QueryAnswerRecord
    rows = (await db.execute(select(AnswerFeedback, QueryAnswerRecord).join(
        QueryAnswerRecord, AnswerFeedback.query_id == QueryAnswerRecord.query_id
    ).where(AnswerFeedback.tenant_id == tenant_id, AnswerFeedback.user_id == user_id,
            QueryAnswerRecord.tenant_id == tenant_id, QueryAnswerRecord.user_id == user_id,
            QueryAnswerRecord.question == question).order_by(AnswerFeedback.created_at.desc()).limit(1))).all()
    if not rows or rows[0][0].rating != "down":
        return ""
    feedback, record = rows[0]
    return _critique(record.answer_text, feedback.reasons, feedback.comment)
