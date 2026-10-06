"""The Ask Kriton review loop: user feedback, the review queue, and reviewed
answers becoming evaluation cases.

Before this, an escalated answer was written to review_cases and never read
again — 324 cases, none resolved — and there was no way for a user to say an
answer was wrong. Now:

  thumbs-down on an answer ──> review case (source "user_feedback")
  validator escalation      ──> review case (source "escalation", with the draft)
  reviewer approves/corrects ──> gold BenchmarkCase with the reviewer's key facts
                                 (scripts/run_baseline_eval.py --only gold)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.evaluation.models import BenchmarkCase, EvaluationDataset
from app.orchestration.models import AnswerFeedback, ReviewCase
from app.orchestration.persisted_objects import create_review_case

GOLD_DATASET_ID = "kriton-reviewed-gold"
FEEDBACK_REASONS = frozenset({
    "wrong_answer", "wrong_calculation", "wrong_source", "outdated", "wrong_jurisdiction",
    "missing_evidence", "missing_citation", "poor_explanation", "other",
})
DECISIONS = frozenset({"approved", "corrected", "rejected", "needs_evidence"})
EVALUATION_CATEGORIES = frozenset({"retrieval", "citation", "calculation", "jurisdiction", "freshness", "reasoning", "safety", "off_domain", "missing_context", "visualization"})


class ReviewError(ValueError):
    """A review request that cannot be applied (unknown case, wrong state, …)."""


async def record_feedback(
    db: AsyncSession,
    *,
    tenant_id: str,
    user_id: str,
    query_id: str,
    rating: str,
    reasons: list[str],
    comment: str,
    question: str,
    answer_text: str,
) -> AnswerFeedback:
    """Store a rating. A thumbs-down opens a review case carrying the answer
    the user saw, so a reviewer can correct it."""
    from app.orchestration.models import QueryAnswerRecord
    record = (await db.execute(select(QueryAnswerRecord).where(
        QueryAnswerRecord.query_id == query_id, QueryAnswerRecord.tenant_id == tenant_id,
        QueryAnswerRecord.user_id == user_id,
    ))).scalar_one_or_none()
    if record is None or not record.answer_text:
        raise ReviewError("Answer not found for the current user")
    question, answer_text = record.question, record.answer_text
    reasons = sorted({reason for reason in reasons if reason in FEEDBACK_REASONS})
    # A repeated thumbs-down on the same answer joins the case it already
    # opened rather than queuing the answer for review twice.
    review_case_id = (await db.execute(
        select(AnswerFeedback.review_case_id).where(
            AnswerFeedback.query_id == query_id, AnswerFeedback.tenant_id == tenant_id,
            AnswerFeedback.user_id == user_id, AnswerFeedback.review_case_id.is_not(None),
        ).limit(1)
    )).scalar_one_or_none() if rating == "down" else None
    if rating == "down" and review_case_id is None:
        case = await create_review_case(
            db,
            query_id=query_id,
            correlation_id=query_id,
            tenant_id=tenant_id,
            risk_level="REPORTED",
            confidence_state="user_reported",
            reason="User reported: " + (", ".join(reasons) or "unspecified") + (f" — {comment}" if comment else ""),
            query_text=question,
            assigned_queue="accounting_review",
            draft_answer=answer_text,
            source="user_feedback",
        )
        review_case_id = case.id
    feedback = AnswerFeedback(
        tenant_id=tenant_id, user_id=user_id, query_id=query_id, rating=rating,
        reasons=reasons, comment=comment, review_case_id=review_case_id,
    )
    db.add(feedback)
    await db.commit()
    await db.refresh(feedback)
    return feedback


async def list_review_cases(db: AsyncSession, *, tenant_id: str, status: str = "open", limit: int = 50) -> list[ReviewCase]:
    query = select(ReviewCase).where(ReviewCase.tenant_id == tenant_id)
    if status != "all":
        query = query.where(ReviewCase.status == status)
    result = await db.execute(query.order_by(ReviewCase.created_at.desc()).limit(limit))
    return list(result.scalars())


async def review_counts(db: AsyncSession, *, tenant_id: str) -> dict[str, int]:
    rows = await db.execute(
        select(ReviewCase.status, func.count()).where(ReviewCase.tenant_id == tenant_id).group_by(ReviewCase.status)
    )
    return {status: count for status, count in rows.all()}


async def _gold_dataset(db: AsyncSession, tenant_id: str) -> EvaluationDataset:
    dataset_id = f"{GOLD_DATASET_ID}:{tenant_id}"
    dataset = await db.get(EvaluationDataset, dataset_id)
    if dataset is None:
        dataset = EvaluationDataset(id=dataset_id, tenant_id=tenant_id, version="1", status="ACTIVE", domain="ask_kriton")
        db.add(dataset)
        await db.flush()
    return dataset


async def resolve_review_case(
    db: AsyncSession,
    *,
    tenant_id: str,
    case_id: str,
    reviewer_id: str,
    decision: str,
    note: str = "",
    corrected_answer: str = "",
    key_facts: list[str] | None = None,
    category: str = "reasoning",
) -> tuple[ReviewCase, BenchmarkCase | None]:
    """Record a reviewer's decision. An approved or corrected answer becomes
    a gold evaluation case; a rejected one (the question should not have been
    answered, or the report was unfounded) does not."""
    if decision not in DECISIONS:
        raise ReviewError(f"Unknown decision {decision!r}")
    case = (await db.execute(
        select(ReviewCase).where(ReviewCase.id == case_id, ReviewCase.tenant_id == tenant_id).with_for_update()
    )).scalar_one_or_none()
    if case is None:
        raise ReviewError("Review case not found")
    if case.status not in ("open", "needs_evidence"):
        raise ReviewError("Review case is already resolved")
    corrected_answer = corrected_answer.strip()
    if decision == "corrected" and not corrected_answer:
        raise ReviewError("A correction needs the corrected answer")
    if decision == "approved" and not case.draft_answer.strip():
        raise ReviewError("There is no draft answer to approve; correct it instead")

    facts = list(dict.fromkeys(fact.strip() for fact in (key_facts or []) if fact.strip()))
    if category not in EVALUATION_CATEGORIES:
        raise ReviewError("Unknown evaluation category")
    if decision in ("approved", "corrected"):
        if not case.query_text.strip():
            raise ReviewError("A gold case needs the original question")
        if not facts:
            raise ReviewError("Approval or correction needs at least one key fact")
        answer = corrected_answer if decision == "corrected" else case.draft_answer
        if any(fact.casefold() not in answer.casefold() for fact in facts):
            raise ReviewError("Every key fact must appear in the approved answer")
    if decision in ("rejected", "needs_evidence") and not note.strip():
        raise ReviewError("This decision needs a review note")

    case.status = "needs_evidence" if decision == "needs_evidence" else "resolved"
    case.reviewer_decision = decision
    case.reviewer_id = reviewer_id
    case.review_note = note.strip()
    case.resolved_at = None if decision == "needs_evidence" else datetime.now(timezone.utc)

    gold = None
    if decision in ("approved", "corrected") and case.query_text.strip():
        dataset = await _gold_dataset(db, tenant_id)
        gold = BenchmarkCase(
            id=f"gold-{uuid.uuid4().hex[:12]}",
            dataset_id=dataset.id,
            query_text=case.query_text,
            gold_answer=corrected_answer if decision == "corrected" else case.draft_answer,
            source_refs=await reviewed_source_refs(db, tenant_id=tenant_id, query_id=case.query_id),
            tenant_id=tenant_id, category=category,
            risk_scope=case.risk_level if case.risk_level in ("LOW", "MEDIUM", "HIGH", "RESTRICTED") else "LOW",
            key_facts=facts,
        )
        db.add(gold)
    await db.commit()
    await db.refresh(case)
    return case, gold


async def reviewed_source_refs(db: AsyncSession, *, tenant_id: str, query_id: str) -> list[str]:
    from app.orchestration.models import EvidenceBundleManifest
    rows = (await db.execute(select(EvidenceBundleManifest).where(
        EvidenceBundleManifest.tenant_id == tenant_id, EvidenceBundleManifest.query_id == query_id,
    ))).scalars().all()
    return sorted({p["source_version_id"] for row in rows for p in row.manifest.get("passages", [])})


async def review_evidence(db: AsyncSession, *, tenant_id: str, case_id: str) -> list[dict]:
    """Replay registered evidence subject to CURRENT display rights.

    A review permission does not grant permission to read revoked/private
    passage text. Withheld and changed evidence remains visible as metadata.
    """
    import hashlib
    from datetime import date
    from app.domains.source_library.licensing import SourceUseContext, can_use_many
    from app.domains.source_library.models import SourcePassage, SourceVersion
    from app.orchestration.models import EvidenceBundleManifest
    case = (await db.execute(select(ReviewCase).where(
        ReviewCase.id == case_id, ReviewCase.tenant_id == tenant_id,
    ))).scalar_one_or_none()
    if case is None:
        raise ReviewError("Review case not found")
    bundles = (await db.execute(select(EvidenceBundleManifest).where(
        EvidenceBundleManifest.tenant_id == tenant_id, EvidenceBundleManifest.query_id == case.query_id,
    ).order_by(EvidenceBundleManifest.created_at.desc()))).scalars().all()
    evidence = []
    for bundle in bundles:
        selections = bundle.manifest.get("passages", [])
        version_ids = [p["source_version_id"] for p in selections]
        as_of = bundle.manifest.get("as_of")
        rights = await can_use_many(db, version_ids, SourceUseContext(
            tenant_id=tenant_id, effective_date=date.fromisoformat(as_of) if as_of else None,
        ), "display")
        allowed_ids = [p["passage_id"] for p in selections if rights[p["source_version_id"]].allowed]
        # Text is fetched only after display rights have passed.
        passages = {p.id: p for p in (await db.execute(select(SourcePassage).where(
            SourcePassage.id.in_(allowed_ids),
        ))).scalars()} if allowed_ids else {}
        versions = {v.id: v for v in (await db.execute(select(SourceVersion).where(
            SourceVersion.id.in_(version_ids),
        ))).scalars()} if version_ids else {}
        sources = {s["id"]: s for s in bundle.manifest.get("sources", [])}
        for selection in selections:
            decision = rights[selection["source_version_id"]]
            passage = passages.get(selection["passage_id"])
            version = versions.get(selection["source_version_id"])
            reason = "" if decision.allowed else decision.reason_code
            if decision.allowed and (passage is None or passage.source_version_id != selection["source_version_id"]
                    or hashlib.sha256(passage.content.encode()).hexdigest() != selection["content_hash"]):
                reason = "EVIDENCE_INTEGRITY_FAILURE"
            evidence.append({
                "bundle_id": bundle.id, "passage_id": selection["passage_id"],
                "source_version_id": selection["source_version_id"],
                "title": sources.get(selection["source_id"], {}).get("title", "Registered evidence"),
                "locator": selection["locator"], "url": version.source_url if version else None,
                "effective_from": str(version.effective_from) if version and version.effective_from else None,
                "effective_to": str(version.effective_to) if version and version.effective_to else None,
                "content": passage.content if passage and not reason else None,
                "withheld_reason": reason or None,
            })
    from app.orchestration.models import QueryAnswerRecord
    record = (await db.execute(select(QueryAnswerRecord).where(
        QueryAnswerRecord.query_id == case.query_id, QueryAnswerRecord.tenant_id == tenant_id,
    ))).scalar_one_or_none()
    if record:
        evidence.extend(record.external_evidence or [])
    return evidence


async def record_answer(db: AsyncSession, *, query_id: str, tenant_id: str, user_id: str,
                        question: str, answer_text: str, external_evidence: list[dict]) -> None:
    from app.orchestration.models import QueryAnswerRecord
    from app.orchestration.redaction import redact_for_external_exposure
    db.add(QueryAnswerRecord(
        query_id=query_id, tenant_id=tenant_id, user_id=user_id,
        question=redact_for_external_exposure(question).redacted_text,
        answer_text=redact_for_external_exposure(answer_text).redacted_text,
        external_evidence=external_evidence,
    ))
    await db.commit()


def external_evidence_snapshot(sources: list) -> list[dict]:
    """External snippets are explicitly labelled, never registered passages."""
    import hashlib
    from app.orchestration.redaction import redact_for_external_exposure
    evidence = []
    seen = set()
    for source in sources:
        url = source.url or ""
        if url in seen or not url.startswith("https://") or source.provider == "uploaded_document":
            continue
        seen.add(url)
        evidence.append({
            "bundle_id": "external", "passage_id": hashlib.sha256(url.encode()).hexdigest()[:16],
            "source_version_id": "external_snapshot", "title": source.title, "locator": url,
            "url": url, "effective_from": None, "effective_to": None,
            "content": redact_for_external_exposure(source.snippet or "").redacted_text,
            "withheld_reason": None,
        })
    return evidence
