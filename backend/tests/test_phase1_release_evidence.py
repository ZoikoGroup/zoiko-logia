"""Narrow diagnostic and audit tests; never live or accountant-approved accuracy."""
import hashlib
import json
import os
from pathlib import Path
import pytest
from sqlalchemy import select
from app.domains.audit_ledger.models import AuditEvent
from app.domains.audit_ledger.chain_integrity import compute_payload_hash, compute_chain_hash
from tests.offline_http_support import offline_http  # noqa: F401
from tests.test_agent_loop import _reply
from tests.test_phase1_targeted_remediation import QUESTION, JOURNAL
from app.orchestration.calculations.engine import calculate_from_query


@pytest.mark.parametrize("mode", ["missing", "invalid", "valid"])
async def test_credit_sale_api_verification_and_audit_agree(offline_http, mode):
    if mode == "valid":
        offline_http.state.responses=[_reply(JOURNAL)]
    elif mode == "invalid":
        offline_http.state.responses=[_reply("VAT £1,000; total £6,000. The requested journal has not been provided.")]
    result=await offline_http.ask(QUESTION,case_id="credit-sale-consistency-"+mode)
    body=result.body;answer=body["answer"]
    assert result.trace["http_status"] == 200
    assert answer is not None
    expected_complete="complete" if mode == "valid" else "partial"
    assert answer["completeness"] == expected_complete
    journal=next(d for d in body["requested_deliverables"] if d["description"] == "Credit-sale journal entry")
    assert journal["status"] == ("complete" if mode == "valid" else "incomplete")
    events={row["event"]:row for row in result.trace["audit"]}
    receipt=events["answer_receipt"]["payload"]
    finalised=events["response_finalised"]["payload"]
    verification=events["answer_verification_recorded"]["payload"]
    assert receipt["outcome"] == finalised["outcome"] == body["outcome"]
    assert receipt["route"] == finalised["route"] == body["route"]
    assert receipt["completeness"] == finalised["completeness"] == answer["completeness"]
    assert receipt["requested_deliverables"] == body["requested_deliverables"]
    assert verification["verification"] == answer["verification"]
    assert verification["answer_hash"] == hashlib.sha256(answer["text"].encode()).hexdigest()[:32]
    assert answer["text"] == answer["output_text"]
    assert verification["calculation"]["calculation_id"] == answer["verification"]["calculation_id"]
    # Composed replies may omit the optional top-level calculation object;
    # the canonical calculation is still identified in verification/audit.
    canonical=calculate_from_query(QUESTION)
    assert verification["calculation"]["calculation_id"] == canonical.fingerprint()
    expected_outputs=canonical.model_dump(mode="json")["outputs"]
    assert verification["calculation"]["outputs"] == [
        {key:item[key] for key in ("name","value","display_value")} for item in expected_outputs]
    if body.get("calculation") is not None:
        assert body["calculation"]["outputs"] == expected_outputs
    assert receipt["request_id"] == body["query_id"]
    assert receipt["review_required"] is (mode != "valid")
    if mode != "valid":
        assert answer["verification"]["overall"] == "partially_verified"
        assert body["next_action"]["type"] == "journal_review_required"
        assert any("Incomplete answer" in item and "journal" in item.lower() for item in answer["limitations"])
    # Verify the persisted rows, not only the trace serialization.
    async with offline_http.sessions() as db:
        rows=(await db.execute(select(AuditEvent).where(AuditEvent.tenant_id == "synthetic-a").order_by(AuditEvent.ingested_at))).scalars().all()
        assert rows
        previous=None
        for row in rows:
            assert row.payload_hash == compute_payload_hash(row.payload)
            assert row.previous_chain_hash == previous
            assert row.chain_hash == compute_chain_hash(row.id,row.event_name,row.payload_hash,previous)
            previous=row.chain_hash
        persisted=next(row for row in rows if row.event_name == "answer_receipt")
        assert persisted.payload == receipt


# Diagnostic alternate requests with explicit scope, not edits to gate cases.
SCOPE_CASES=[
    ("uk_vat","vat-frs-join"),("uk_vat","vat-frs-leave"),("uk_vat","vat-cash-accounting"),
    ("uk_vat","vat-annual-accounting"),("uk_vat","vat-late-submission-points"),
    ("uk_vat","vat-late-payment"),("uk_vat","vat-reverse-charge"),
    ("uk_vat_holdout","ho-mobility-aids"),("uk_vat_holdout","ho-bad-debt"),
    ("uk_vat_holdout","ho-pre-registration"),("uk_vat_holdout","ho-invoice-deadline"),
    ("uk_vat_holdout","ho-simplified-invoice"),("uk_vat_holdout","ho-annual-interim"),
    ("uk_vat_holdout","ho-points-monthly"),("uk_vat_holdout","ho-points-annual"),
    ("uk_vat_holdout","ho-reverse-charge-end-user")]


@pytest.mark.parametrize("dataset,case_id", SCOPE_CASES)
async def test_scoped_request_diagnostic_keeps_original_gate_case_unchanged(offline_http,dataset,case_id):
    backend=Path(__file__).resolve().parents[1]
    path=backend/"evals"/("uk_vat_questions.json" if dataset == "uk_vat" else "uk_vat_holdout.json")
    before=hashlib.sha256(path.read_bytes()).hexdigest()
    case=next(c for c in json.loads(path.read_text())["cases"] if c["id"]==case_id)
    body={"query":case["question"],"jurisdiction":"United Kingdom","conversation_id":"scope-diagnostic-"+case_id}
    response=await offline_http.client.post("/api/v1/orchestration/ask",json=body,
        headers={"Authorization":"Bearer offline-actor-a","Idempotency-Key":"scope-diagnostic-"+case_id})
    assert response.status_code == 200,response.text
    payload=response.json()
    assert not ((payload.get("next_action") or {}).get("message","").startswith("Specify the tax jurisdiction"))
    assert not (payload.get("source_bundle") or {}).get("clarification_required")
    assert (payload.get("source_bundle") or {}).get("jurisdiction") in {"GB", "UK", "United Kingdom"}  # API may canonicalize the label
    assert (payload.get("source_bundle") or {}).get("eligible_source_count") == 0
    assert payload["outcome"] == "unavailable"  # deliberate provider failure remains
    assert hashlib.sha256(path.read_bytes()).hexdigest()==before
    if folder:=os.getenv("PHASE1_EVIDENCE_DIR"):
        out=Path(folder);out.mkdir(parents=True,exist_ok=True)
        (out/("scope-"+case_id+".json")).write_text(json.dumps({"diagnostic_only":True,
            "not_a_release_pass":True,"dataset_sha256_before":before,
            "dataset_sha256_after":hashlib.sha256(path.read_bytes()).hexdigest(),
            "request":body,"http_status":response.status_code,"response":payload},indent=2))
