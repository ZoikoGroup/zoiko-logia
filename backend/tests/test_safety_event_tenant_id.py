"""
Regression test for a live-schema-drift bug found during the enterprise-
grade consistency audit: safety_events, safety_overrides, and
escalation_cases all have a NOT NULL tenant_id column on the real Postgres
DB that was added outside this codebase's own Alembic migrations — none of
the three SQLAlchemy models declared it (or declared it nullable=True).

Confirmed live, not hypothetical: reproducing resolve_escalation() against
the real DB raised psycopg2.errors.NotNullViolation on every call, meaning
the reviewer approve/refuse/escalate endpoint — the human-review workflow
that HIGH-risk and evasion-gate routes depend on — was completely broken.
create_safety_override() failed the same way.

Requires a live Postgres connection (the manually-added NOT NULL columns
only exist there); skips itself under SQLite, same convention as
test_tenant_isolation.py.

Run with: python tests/test_safety_event_tenant_id.py
"""
import os
import sys
import uuid

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.domains.risk_safety import service as safety_service
from app.domains.risk_safety.models import EscalationCase, RiskLevel, EscalationStatus, SafetyEvent, SafetyOverride
from app.domains.risk_safety.schemas import OverrideRequest

settings = get_settings()


def test_resolve_escalation_writes_safety_event_without_crashing():
    if settings.is_sqlite:
        print("test_resolve_escalation_writes_safety_event_without_crashing: SKIPPED (SQLite has no live schema drift)")
        return

    db = SessionLocal()
    case_id = f"ESC-test-{uuid.uuid4().hex[:8]}"
    case = EscalationCase(
        id=case_id, query_id="q-test-tenant-id", query_text="test", topic="test",
        tenant_id="tenant-test-safety-event", risk_level=RiskLevel.HIGH, jurisdiction="GLOBAL",
        reviewer_role="SME Reviewer", status=EscalationStatus.PENDING, owner="alice", evidence_refs=[],
    )
    db.add(case)
    db.commit()
    try:
        result = safety_service.resolve_escalation(db=db, case_id=case_id, action="approve", reviewer_id="bob", reason="test")
        assert result is not None and result.status == EscalationStatus.RESOLVED
        event = db.query(SafetyEvent).filter(SafetyEvent.query_id == "q-test-tenant-id").first()
        assert event is not None, "resolve_escalation must write a SafetyEvent row"
        assert event.tenant_id == "tenant-test-safety-event"
        print("test_resolve_escalation_writes_safety_event_without_crashing: PASSED")
    finally:
        db.rollback()
        db.query(SafetyEvent).filter(SafetyEvent.query_id == "q-test-tenant-id").delete()
        db.query(EscalationCase).filter(EscalationCase.id == case_id).delete()
        db.commit()
        db.close()


def test_maker_checker_violation_writes_safety_event_without_crashing():
    if settings.is_sqlite:
        print("test_maker_checker_violation_writes_safety_event_without_crashing: SKIPPED (SQLite has no live schema drift)")
        return

    db = SessionLocal()
    case_id = f"ESC-test-{uuid.uuid4().hex[:8]}"
    case = EscalationCase(
        id=case_id, query_id="q-test-maker-checker", query_text="test", topic="test",
        tenant_id="tenant-test-maker-checker", risk_level=RiskLevel.HIGH, jurisdiction="GLOBAL",
        reviewer_role="SME Reviewer", status=EscalationStatus.PENDING, owner="alice", evidence_refs=[],
    )
    db.add(case)
    db.commit()
    try:
        raised = False
        try:
            safety_service.resolve_escalation(db=db, case_id=case_id, action="approve", reviewer_id="alice", reason="test")
        except ValueError:
            raised = True
        assert raised, "maker-checker violation must still raise ValueError (the intended business-logic error)"
        print("test_maker_checker_violation_writes_safety_event_without_crashing: PASSED")
    finally:
        db.rollback()
        db.query(SafetyEvent).filter(SafetyEvent.query_id == "q-test-maker-checker").delete()
        db.query(EscalationCase).filter(EscalationCase.id == case_id).delete()
        db.commit()
        db.close()


def test_create_safety_override_without_crashing():
    if settings.is_sqlite:
        print("test_create_safety_override_without_crashing: SKIPPED (SQLite has no live schema drift)")
        return

    db = SessionLocal()
    actor_id = f"test-actor-{uuid.uuid4().hex[:8]}"
    payload = OverrideRequest(
        actor_id=actor_id, authority_role="SME", original_route="REFUSAL", new_route="HUMAN_REVIEW",
        scope="query-scoped", reason="test override", tenant_id="tenant-test-override", duration_hours=1,
    )
    try:
        override = safety_service.create_safety_override(db, payload)
        assert override.tenant_id == "tenant-test-override"
        event = (
            db.query(SafetyEvent)
            .filter(SafetyEvent.event_type == "safety_override_applied", SafetyEvent.tenant_id == "tenant-test-override")
            .first()
        )
        assert event is not None, "create_safety_override must write a SafetyEvent row"
        print("test_create_safety_override_without_crashing: PASSED")
    finally:
        db.rollback()
        db.query(SafetyOverride).filter(SafetyOverride.actor_id == actor_id).delete()
        db.query(SafetyEvent).filter(SafetyEvent.tenant_id == "tenant-test-override").delete()
        db.commit()
        db.close()


def main():
    test_resolve_escalation_writes_safety_event_without_crashing()
    test_maker_checker_violation_writes_safety_event_without_crashing()
    test_create_safety_override_without_crashing()
    print("All tests passed successfully!")


if __name__ == "__main__":
    main()
