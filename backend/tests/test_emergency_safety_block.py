"""
Emergency Safety Block (ZL-T0-04 §14) — was a fully unused SQLAlchemy
model with no service function ever creating, checking, or disposing of
one before this. Wired end-to-end: create -> a matching query gets hard-
refused -> dispose -> the same query is no longer blocked. Plus the two
governance properties the spec actually specifies: maker-checker
(invoker != approver) and the 72-hour maximum duration cap.

Requires a live DB (creates real EmergencySafetyBlock/SafetyEvent rows) —
run inside the backend container:
    docker compose exec backend python3 tests/test_emergency_safety_block.py
"""
import os
import sys
import uuid

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from app.core.database import SessionLocal
from app.domains.risk_safety import service as safety_service
from app.domains.risk_safety.models import SafetyEvent
from app.domains.risk_safety.schemas import ClassifyRequest, EmergencyBlockCreateRequest


def test_active_block_hard_refuses_matching_query_then_dispose_lifts_it():
    db = SessionLocal()
    scope = f"unit-test-scope-{uuid.uuid4().hex[:8]}"
    query = f"Tell me about {scope} eligibility rules"
    request = ClassifyRequest(query=query, tenant_id="test-tenant-emergency-block")
    try:
        # Before any block exists, this query passes through untouched.
        assert safety_service.check_emergency_blocks(db, query) is None

        block = safety_service.create_emergency_block(db, EmergencyBlockCreateRequest(
            invoker="alice", approver="bob", scope=scope, reason="unit test block", duration_hours=1,
        ))
        assert block.is_active is True

        decision = safety_service.pre_screen(request, db=db)
        assert decision is not None, "an active emergency block must hard-block a matching query"
        assert decision.allowed is False
        assert decision.risk_level == "RESTRICTED"

        event = db.query(SafetyEvent).filter(SafetyEvent.event_type == "emergency_safety_block_invoked").order_by(SafetyEvent.id.desc()).first()
        assert event is not None and event.payload["block_id"] == block.id

        disposed = safety_service.dispose_emergency_block(db, block.id, reviewer="carol", disposition="released")
        assert disposed.is_active is False
        assert disposed.reviewer == "carol"

        dispose_event = db.query(SafetyEvent).filter(SafetyEvent.event_type == "emergency_safety_block_disposed").order_by(SafetyEvent.id.desc()).first()
        assert dispose_event is not None and dispose_event.payload["block_id"] == block.id

        # Once disposed, the same query must pass through again.
        assert safety_service.check_emergency_blocks(db, query) is None
        decision_after = safety_service.pre_screen(request, db=db)
        assert decision_after is None, "a disposed block must no longer affect the same query"

        print("test_active_block_hard_refuses_matching_query_then_dispose_lifts_it: PASSED")
    finally:
        # SafetyEvent rows are an immutable audit ledger by design (see the
        # model's own docstring) — left in place, same as every other test
        # in this suite that writes one. Only the test's own block row is
        # cleaned up.
        db.query(type(block)).filter(type(block).id == block.id).delete()
        db.commit()
        db.close()


def test_maker_checker_rejects_invoker_equal_to_approver():
    db = SessionLocal()
    try:
        raised = False
        try:
            safety_service.create_emergency_block(db, EmergencyBlockCreateRequest(
                invoker="dave", approver="dave", scope="irrelevant", reason="self-approval attempt", duration_hours=1,
            ))
        except ValueError:
            raised = True
        assert raised, "invoker and approver must not be allowed to be the same person"
        print("test_maker_checker_rejects_invoker_equal_to_approver: PASSED")
    finally:
        db.close()


def test_duration_over_72_hours_rejected_at_the_schema_boundary():
    """EmergencyBlockCreateRequest.duration_hours already declares Field(le=72)
    — Pydantic rejects an out-of-range request before it ever reaches
    create_emergency_block(). Same defense-in-depth pattern as
    OverrideRequest/create_safety_override(), which this mirrors."""
    from pydantic import ValidationError
    raised = False
    try:
        EmergencyBlockCreateRequest(invoker="erin", approver="frank", scope="cap-test", reason="testing the cap", duration_hours=1000)
    except ValidationError:
        raised = True
    assert raised, "a duration over 72 hours must be rejected at the schema boundary"
    print("test_duration_over_72_hours_rejected_at_the_schema_boundary: PASSED")


def test_service_layer_also_clamps_duration_defensively():
    """The service function's own min(duration, 72) clamp is defense-in-depth
    for a caller that bypasses Pydantic validation (e.g. constructing the
    dataclass directly) — verified by calling create_emergency_block()
    with a raw object that skips the schema's own Field(le=72) check."""
    from types import SimpleNamespace
    db = SessionLocal()
    block = None
    try:
        payload = SimpleNamespace(
            invoker="erin", approver="frank", scope=f"cap-test-{uuid.uuid4().hex[:8]}",
            reason="testing the service-level clamp", duration_hours=1000,
        )
        block = safety_service.create_emergency_block(db, payload)
        actual_hours = (block.expires_at - block.created_at).total_seconds() / 3600
        assert actual_hours <= 72.01, f"duration must be clamped at 72h, got {actual_hours}"
        print("test_service_layer_also_clamps_duration_defensively: PASSED")
    finally:
        if block is not None:
            db.query(type(block)).filter(type(block).id == block.id).delete()
            db.commit()
        db.close()


def main():
    test_maker_checker_rejects_invoker_equal_to_approver()
    test_duration_over_72_hours_rejected_at_the_schema_boundary()
    test_service_layer_also_clamps_duration_defensively()
    test_active_block_hard_refuses_matching_query_then_dispose_lifts_it()
    print("All tests passed successfully!")


if __name__ == "__main__":
    main()
