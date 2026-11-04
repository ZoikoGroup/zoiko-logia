"""Database-free checks that calculator tax basis matches the input guard."""
from decimal import Decimal
import pytest
from app.orchestration.calculations.engine import vat_amounts
from app.orchestration.input_requirements import missing_vat_inputs


@pytest.mark.parametrize("delivery", ["including delivery", "excluding delivery", "net of delivery", "gross of delivery"])
def test_incidental_delivery_does_not_establish_calculator_tax_basis(delivery):
    query = f"Calculate VAT on £5,000 at 20%, {delivery}."
    assert missing_vat_inputs(query) is not None
    assert vat_amounts(query) is None


@pytest.mark.parametrize("delivery", ["including delivery", "excluding delivery"])
@pytest.mark.parametrize("basis,vat,other_name,other", [
    ("including VAT", Decimal("5000") / 6, "amount_excluding_vat", Decimal("5000") * 5 / 6),
    ("excluding VAT", Decimal("1000"), "total_including_vat", Decimal("6000")),
])
def test_explicit_vat_basis_controls_calculation_despite_delivery_wording(delivery,basis,vat,other_name,other):
    query = f"Calculate VAT on £5,000 at 20%, {delivery}, {basis}."
    assert missing_vat_inputs(query) is None
    result = vat_amounts(query)
    assert result is not None and result.status == "success"
    outputs = {item.name:item for item in result.outputs}
    assert abs(outputs["vat_amount"].value - vat) < Decimal("0.00000000000000000001")
    assert abs(outputs[other_name].value - other) < Decimal("0.00000000000000000001")
    assert outputs["vat_amount"].display_value == ("£833.33" if basis == "including VAT" else "£1,000.00")
    assert outputs[other_name].display_value == ("£4,166.67" if basis == "including VAT" else "£6,000.00")


from tests.offline_http_support import offline_http  # noqa: E402,F401


@pytest.mark.parametrize("basis", [None, "including VAT", "excluding VAT"])
async def test_delivery_response_verification_and_persisted_audit_agree(offline_http,basis):
    import hashlib
    from sqlalchemy import select
    from app.domains.audit_ledger.models import AuditEvent
    qualifier = "including delivery" + (f", {basis}" if basis else "")
    result = await offline_http.ask(f"Calculate VAT on £5,000 at 20%, {qualifier}.", case_id="delivery-"+str(basis))
    body = result.body
    assert result.trace["http_status"] == 200
    async with offline_http.sessions() as db:
        rows = (await db.execute(select(AuditEvent).where(AuditEvent.tenant_id == "synthetic-a"))).scalars().all()
    events = {row.event_name:row.payload for row in rows}
    receipt = events["answer_receipt"]
    final = events["response_finalised"]
    assert receipt["outcome"] == final["outcome"] == body["outcome"]
    if basis is None:
        assert body["outcome"] == "clarification_required"
        assert "include VAT or exclude VAT" in body["next_action"]["message"]
        assert body.get("calculation") is None
    else:
        assert body["outcome"] == "answered"
        answer = body["answer"]
        assert answer["completeness"] == "complete"
        assert receipt["completeness"] == final["completeness"] == answer["completeness"]
        verification = events["answer_verification_recorded"]
        assert verification["verification"] == answer["verification"]
        assert verification["answer_hash"] == hashlib.sha256(answer["text"].encode()).hexdigest()[:32]
        outputs = {item["name"]:item for item in verification["calculation"]["outputs"]}
        assert outputs["vat_amount"]["display_value"] == ("£833.33" if basis == "including VAT" else "£1,000.00")
        other = "amount_excluding_vat" if basis == "including VAT" else "total_including_vat"
        assert outputs[other]["display_value"] == ("£4,166.67" if basis == "including VAT" else "£6,000.00")
        for item in (outputs["vat_amount"],outputs[other]):
            assert item["display_value"] in answer["text"]
