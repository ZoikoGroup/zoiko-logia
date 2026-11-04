"""WF-01 A3: the runtime QA ledger for the 72-case chatbot pack (Evaluation
Gates 19). Kept separate from the reporting, catalog and reference suites.

  qa_cases            the 72 cases, imported once from the ratified manifest
  qa_baseline         the 292 planned observations, all NOT_RUN, immutable
  qa_runs             a pinned run configuration; an unpinned run is refused
  qa_observations     one row per executed case x repetition, append-only
  qa_adjudications    an independent person's verdict on one observation,
                      append-only, bound to the observation's hashes
  qa_fixture_provisions  each fixture file loaded into a target environment,
                      append-only (migration i4c5d6e7f8a9)

An observation is never PASSED by itself: its result is the automated
evidence, and the case counts as PASSED only through an adjudication by a
qa.adjudicate holder who did not start the run. Append-only and the baseline's
immutability are enforced by the database (migration g2a3b4c5d6e7).
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

OBSERVATION_STATES = ("NOT_RUN", "RUNNING", "EXECUTED", "BLOCKED", "FAILED_TO_EXECUTE")
VERDICTS = ("NOT_RUN", "RUNNING", "PASSED", "FAILED", "BLOCKED", "INCONCLUSIVE")


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class QaCase(Base):
    __tablename__ = "qa_cases"
    __table_args__ = (UniqueConstraint("pack_sha256", "case_id", name="uq_qa_case"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    pack_sha256: Mapped[str] = mapped_column(String, nullable=False, index=True)
    case_id: Mapped[str] = mapped_column(String, nullable=False)
    suite: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str] = mapped_column(String, nullable=False)
    fixture: Mapped[str] = mapped_column(String, nullable=False, default="")
    text: Mapped[str] = mapped_column(Text, nullable=False)
    text_sha256: Mapped[str] = mapped_column(String, nullable=False)
    planned_repetitions: Mapped[int] = mapped_column(Integer, nullable=False)
    requires_upload: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class QaBaseline(Base):
    __tablename__ = "qa_baseline"
    __table_args__ = (UniqueConstraint("pack_sha256", "case_id", "repetition", name="uq_qa_baseline"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    pack_sha256: Mapped[str] = mapped_column(String, nullable=False, index=True)
    case_id: Mapped[str] = mapped_column(String, nullable=False)
    repetition: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="NOT_RUN")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class QaRun(Base):
    __tablename__ = "qa_runs"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_qa_run_idempotency"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    pack_sha256: Mapped[str] = mapped_column(String, nullable=False)
    pinned: Mapped[dict] = mapped_column(JSON, nullable=False)     # release sha, environment, model, retriever, prompt, policy, region, oracle, adapter
    pinned_sha256: Mapped[str] = mapped_column(String, nullable=False)
    environment: Mapped[str] = mapped_column(String, nullable=False)
    qualifying: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)   # staging + committed + connected adapter
    adapter_readiness: Mapped[str] = mapped_column(String, nullable=False)              # CONNECTED / MISSING / UNVERIFIED
    started_by: Mapped[str] = mapped_column(String, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class QaObservation(Base):
    __tablename__ = "qa_observations"
    __table_args__ = (UniqueConstraint("run_id", "case_id", "repetition", name="uq_qa_observation"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(String, ForeignKey("qa_runs.id"), nullable=False, index=True)
    case_id: Mapped[str] = mapped_column(String, nullable=False)
    repetition: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String, nullable=False)                    # EXECUTED / BLOCKED / FAILED_TO_EXECUTE
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    request_sha256: Mapped[str] = mapped_column(String, nullable=False, default="")
    output_sha256: Mapped[str] = mapped_column(String, nullable=False, default="")
    output_excerpt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    trace: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)       # query id, outcome, route, citations, http status, timing
    automated_checks: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class QaAdjudication(Base):
    __tablename__ = "qa_adjudications"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_qa_adjudication_idempotency"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    observation_id: Mapped[str] = mapped_column(String, ForeignKey("qa_observations.id"), nullable=False, index=True)
    verdict: Mapped[str] = mapped_column(String, nullable=False)                  # PASSED / FAILED / INCONCLUSIVE
    oracle_version: Mapped[str] = mapped_column(String, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    adjudicator_id: Mapped[str] = mapped_column(String, nullable=False)
    observation_sha256: Mapped[str] = mapped_column(String, nullable=False)
    signature_status: Mapped[str] = mapped_column(String, nullable=False)        # SIGNED / UNSIGNED_NO_KEY
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class QaFixtureProvision(Base):
    """Append-only. One fixture file loaded into a target environment: the
    file's sha256 (checked against evals/qa_fixtures/<ID>/MANIFEST.json before
    upload), the tenant slot it went to (A, the QA service account's tenant; B,
    the second tenant F7 is seeded in) and the document id the target returned.
    A file the target cannot accept is recorded UNSUPPORTED, never converted."""
    __tablename__ = "qa_fixture_provisions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    fixture_id: Mapped[str] = mapped_column(String, nullable=False)
    file_name: Mapped[str] = mapped_column(String, nullable=False)
    file_sha256: Mapped[str] = mapped_column(String, nullable=False, index=True)
    environment: Mapped[str] = mapped_column(String, nullable=False)
    base_url: Mapped[str] = mapped_column(String, nullable=False)
    tenant_slot: Mapped[str] = mapped_column(String, nullable=False)               # A / B
    status: Mapped[str] = mapped_column(String, nullable=False)                    # PROVISIONED / UNSUPPORTED / FAILED
    document_id: Mapped[str | None] = mapped_column(String, nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    provisioned_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
