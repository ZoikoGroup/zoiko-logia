"""Feedback is a signal to recheck, never knowledge (ZL-ENG-AGT-01 §08).

A rating does not change what Kriton knows. A thumbs-down opens a review case
(review.record_feedback), and only a reviewer's decision there can produce a
reusable answer (a gold case in review.GOLD_DATASET_ID). Nothing here writes to
the source library, the retrieval index or any answer memory.

What remains:
  • learnable() / answer_was_verified(): pure checks used by the offline
    training export (app/training/data.py), which has its own approval gate.
  • feedback_guidance(): when the same user asks the same question again
    after a thumbs-down, the prompt asks Kriton to re-check the figures it
    flagged. Only the structured reason codes are passed on, never the user's
    free-text comment, so a comment like "the rate is actually 50%" cannot
    steer the answer (§08 feedback-poisoning test).

Answers saved automatically by an earlier version (dataset "kriton-learned")
are no longer read anywhere; see reviewed_answers.find_reviewed_answers.
"""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.orchestration.reviewed_answers import figures

# Audit events that mean an answer did not pass cleanly.
_UNVERIFIED_EVENTS = frozenset({
    "release_check_degraded", "human_review_created", "refusal_returned",
    "composition_rejected", "composition_failed", "clarification_returned",
})
_MIN_QUESTION_TOKENS = 4
_REASON_TEXT = {
    "wrong_answer": "the answer is wrong", "wrong_calculation": "a calculation is wrong",
    "wrong_source": "it cites the wrong source", "outdated": "it is out of date",
    "wrong_jurisdiction": "it uses the wrong country's rules", "missing_evidence": "it lacks evidence",
    "missing_citation": "statements are uncited", "poor_explanation": "the explanation is unclear",
}

# Market and live figures change daily; their answers are never reused.
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


def _critique(rejected_answer: str, reasons: list[str]) -> str:
    said = "; ".join(_REASON_TEXT.get(reason, reason) for reason in reasons if reason in _REASON_TEXT) or "unspecified"
    return (
        "\n\n=== Feedback on an earlier answer to this question ===\n"
        f"The user marked the earlier answer below as unsatisfactory ({said}). This is a request to "
        "re-check, not evidence.\n"
        "Re-check every figure, rule and date against the evidence above. Do not repeat any "
        "statement from the earlier answer that the evidence does not support, answer every part "
        "of the question, and cite each factual statement.\n"
        "Earlier answer:\n" + rejected_answer[:4000]
    )


async def feedback_guidance(db: AsyncSession, *, tenant_id: str, user_id: str, question: str) -> str:
    """The user's own latest thumbs-down on this exact question, as a re-check
    request. Scoped to the user and tenant; never shared, never evidence."""
    from app.orchestration.models import AnswerFeedback, QueryAnswerRecord
    rows = (await db.execute(select(AnswerFeedback, QueryAnswerRecord).join(
        QueryAnswerRecord, AnswerFeedback.query_id == QueryAnswerRecord.query_id
    ).where(AnswerFeedback.tenant_id == tenant_id, AnswerFeedback.user_id == user_id,
            QueryAnswerRecord.tenant_id == tenant_id, QueryAnswerRecord.user_id == user_id,
            QueryAnswerRecord.question == question).order_by(AnswerFeedback.created_at.desc()).limit(1))).all()
    if not rows or rows[0][0].rating != "down":
        return ""
    feedback, record = rows[0]
    return _critique(record.answer_text, feedback.reasons or [])
