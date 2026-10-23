"""Controlled files drive validation and draft boundaries, not certification."""
import copy
import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.domains.reporting.pipeline import build_draft
from app.domains.reporting.request_service import build_requested_draft
from app.domains.reporting.specification import (SPEC, SpecificationError, catalog_support,
    load_table, schema_validator, specification_hashes, validate_contract)
from app.domains.reporting.states import ReportState

FIXTURE = json.loads((SPEC.parent / "fixtures/golden_route_001.json").read_text())


def request():
    ledger = FIXTURE["ledger"]
    return {"template_id": "RPT-001", "report_class": "STATUTORY_DRAFT",
            "entity_scope": {"entity_ids": [ledger["entity"]], "scope_type": "SEPARATE"},
            "framework": {"code": "MANAGEMENT_BASIS", "adoption_mode": "DEFAULT"},
            "period": {"start": ledger["period_start"], "end": ledger["period_end"]},
            "basis": "SYNTHETIC", "presentation": {"currency": "USD", "scale": 1, "locale": "en-GB"},
            "outputs": ["JSON"]}


def run(payload=None, ledger=None, authorised=None):
    return build_requested_draft(payload or request(), copy.deepcopy(ledger or FIXTURE["ledger"]),
        copy.deepcopy(FIXTURE["account_map"]),
        authorised_entity_ids=frozenset([FIXTURE["ledger"]["entity"]] if authorised is None else authorised))


def fact():
    return run().facts[0]


def test_all_source_files_load_and_catalogue_does_not_imply_certification():
    assert [len(load_table(n)) for n in ("report_catalog", "reconciliation_rules", "acceptance_test_cases")] == [90, 10, 58]
    entries = catalog_support()
    assert sum(e["draft_compiler_supported"] for e in entries) == 4
    assert not any(e["certified"] for e in entries)
    assert len(specification_hashes()) == 6
    for name in ("report_request", "financial_fact", "report_manifest"):
        schema_validator(name)


@pytest.mark.parametrize("template", ["RPT-001", "RPT-002", "RPT-004", "RPT-006"])
def test_supported_template_emits_only_its_own_validated_facts(template):
    q = request(); q["template_id"] = template
    result = run(q)
    assert result.draft.state == ReportState.DRAFT_RECONCILED
    assert result.facts
    for item in result.facts:
        validate_contract("financial_fact", item)
        assert item["source_snapshot_id"] == result.draft.snapshot_hash
    assert {o.rule_id for o in result.draft.outcomes} == {"TB-001", "BS-001", "PL-001", "CF-001", "EQ-001"}
    assert all(o.specification_source == "reconciliation_rules.csv" for o in result.draft.outcomes if o.rule_id != "PL-001")


@pytest.mark.parametrize("mutate,code", [
    (lambda q: q.update(template_id="RPT-unknown"), "template_unknown"),
    (lambda q: q.update(template_id="RPT-003"), "template_not_implemented"),
    (lambda q: q.update(report_class="MANAGEMENT"), "report_class_mismatch"),
    (lambda q: q.update(basis="ACTUAL_POSTED"), "basis_unsupported"),
    (lambda q: q["framework"].update(code="IFRS"), "basis_unsupported"),
    (lambda q: q["presentation"].update(scale=1000), "presentation_unsupported"),
    (lambda q: q.update(outputs=["PDF"]), "presentation_unsupported"),
    (lambda q: q["period"].update(start="2025-01-01"), "period_mismatch"),
    (lambda q: q["period"].update(end="2026-02-30"), "request_invalid"),
    (lambda q: q["period"].update(start="2027-01-01"), "request_invalid"),
    (lambda q: q.update(tenant_id="spoof"), "request_invalid"),
    (lambda q: q["entity_scope"].update(scope_type="CONSOLIDATED"), "scope_unsupported"),
])
def test_unsupported_or_invalid_request_never_compiles(mutate, code):
    q = request(); mutate(q)
    result = run(q)
    assert result.draft.state == ReportState.UNAVAILABLE
    assert result.draft.error_code == code
    assert result.facts == [] and result.draft.compiled is None


def test_entity_scope_requires_server_supplied_authorisation():
    assert run(authorised=[]).draft.error_code == "entity_access_denied"


@pytest.mark.parametrize("value", ["12.50", "-12.50", "0.01", "123", "0"])
def test_decimal_overlay_accepts_real_decimal_strings(value):
    item = fact(); item.update(value=value, value_status="ZERO" if Decimal(value) == 0 else "PRESENT")
    validate_contract("financial_fact", item)


@pytest.mark.parametrize("value,status", [(None,"PRESENT"),("0","MISSING"),("0","PRESENT"),("1","ZERO"),("1.2.3","PRESENT"),("1\\x2","PRESENT")])
def test_fact_missing_zero_and_invalid_decimals_cannot_be_confused(value,status):
    item = fact(); item.update(value=value,value_status=status)
    with pytest.raises(SpecificationError):validate_contract("financial_fact",item)


def test_unavailable_fact_must_be_null_and_periods_have_one_context():
    item = fact();item.update(value=None,value_status="MISSING")
    validate_contract("financial_fact",item)
    item["period"].update(start="2026-01-01",end="2026-12-31")
    with pytest.raises(SpecificationError):validate_contract("financial_fact",item)


def test_invalid_and_valid_manifest_contract():
    with pytest.raises(SpecificationError): validate_contract("report_manifest",{})
    item = {"report_id":"draft-1","revision":1,"state":"DRAFT_RECONCILED","source_snapshots":["snapshot"],
            "rule_pack_id":"synthetic-only","calc_engine_version":"g1g2-v1","template_version":"v1",
            "rendered_artifacts":[],"audit_commit_id":"test-reference"}
    validate_contract("report_manifest",item)
    item["revision"]=0
    with pytest.raises(SpecificationError):validate_contract("report_manifest",item)


def test_duplicate_or_malformed_catalogue_is_not_silently_accepted(tmp_path):
    raw=(SPEC/"report_catalog.csv").read_text();lines=raw.splitlines()
    (tmp_path/"report_catalog.csv").write_text(raw+lines[1]+"\n")
    with pytest.raises(SpecificationError,match="duplicate"):load_table("report_catalog",tmp_path)


def test_missing_required_rule_blocks_existing_pipeline(monkeypatch):
    from app.domains.reporting import reconcile
    original = reconcile.load_table
    monkeypatch.setattr(reconcile,"load_table",lambda name:[r for r in original(name) if r["rule_id"]!="TB-001"])
    draft=build_draft(copy.deepcopy(FIXTURE["ledger"]),copy.deepcopy(FIXTURE["account_map"]))
    assert draft.state == ReportState.DRAFT_INCOMPLETE
    assert draft.error_code == "specification_invalid"


# Each supplied acceptance row is collected. Unimplemented families are
# deliberately skipped, never declared passing by merely loading the CSV.
IMPLEMENTED = {"FRQA-0001","FRQA-0002","FRQA-0003","FRQA-0004","FRQA-0007","FRQA-0008","FRQA-0013","FRQA-0051","FRQA-0055"}


@pytest.mark.parametrize("case",load_table("acceptance_test_cases"),ids=lambda c:c["test_id"]+"-"+c["test_case"])
def test_supplied_acceptance(case,monkeypatch):
    identity=case["test_id"]
    if identity not in IMPLEMENTED:
        pytest.skip("Not implemented: "+case["suite"]+" / "+case["test_case"])
    if identity=="FRQA-0001":assert run().draft.state==ReportState.DRAFT_RECONCILED
    elif identity=="FRQA-0002":
        ledger=copy.deepcopy(FIXTURE["ledger"]);ledger["journals"][1]["lines"].append({"account":"1100","debit":"1"})
        assert run(ledger=ledger).draft.state==ReportState.DRAFT_INCOMPLETE
    elif identity=="FRQA-0003":
        q=request();q["presentation"]["scale"]=1000
        assert run(q).draft.error_code=="presentation_unsupported"
    elif identity=="FRQA-0004":
        ledger=copy.deepcopy(FIXTURE["ledger"]);ledger["journals"].append(copy.deepcopy(ledger["journals"][1]))
        result=run(ledger=ledger)
        assert result.draft.snapshot_hash==run().draft.snapshot_hash
        assert result.draft.receipt.duplicates_ignored==1
    elif identity=="FRQA-0007":
        item=fact();item.update(value=None,value_status="ZERO")
        with pytest.raises(SpecificationError):validate_contract("financial_fact",item)
    elif identity=="FRQA-0008":
        q=request();q["template_id"]="RPT-004";result=run(q)
        amounts={f["concept_id"]:Decimal(f["value"])/1000 for f in result.facts}
        assert [amounts[n] for n in ["cf.cash.opening","cf.operating","cf.investing","cf.financing","cf.fx_effect","cf.cash.closing"]]==[150,140,-50,-40,0,200]
    elif identity=="FRQA-0013":
        item=fact();item["period"].update(start="2026-01-01",end="2026-12-31")
        with pytest.raises(SpecificationError):validate_contract("financial_fact",item)
    elif identity=="FRQA-0051":
        item=fact();item["value"]=1.25
        with pytest.raises(SpecificationError):validate_contract("financial_fact",item)
    elif identity=="FRQA-0055":
        from app.domains.model_gateway import service
        def unavailable(*args,**kwargs):raise RuntimeError("provider unavailable")
        monkeypatch.setattr(service,"run_test_prompt",unavailable)
        assert run().draft.state==ReportState.DRAFT_RECONCILED


def test_local_validation_command_and_draft_command(tmp_path):
    import subprocess
    import sys
    command = Path(__file__).resolve().parents[1] / "scripts/validate_reporting_specs.py"
    result = subprocess.run([sys.executable, str(command)], capture_output=True, text=True, check=True)
    summary = json.loads(result.stdout)
    assert summary["tables"]["report_catalog"] == 90
    for name, payload in [("request", request()), ("ledger", FIXTURE["ledger"]), ("map", FIXTURE["account_map"])]:
        (tmp_path / (name + ".json")).write_text(json.dumps(payload))
    args = [sys.executable, str(command), "--request", str(tmp_path / "request.json"),
            "--ledger", str(tmp_path / "ledger.json"), "--account-map", str(tmp_path / "map.json")]
    denied = subprocess.run(args, capture_output=True, text=True)
    assert denied.returncode == 1
    assert json.loads(denied.stdout)["draft"]["error_code"] == "entity_access_denied"
    permitted = subprocess.run(args + ["--authorised-entity", FIXTURE["ledger"]["entity"]], capture_output=True, text=True, check=True)
    draft = json.loads(permitted.stdout)["draft"]
    assert draft["state"] == "DRAFT_RECONCILED" and draft["facts"]
