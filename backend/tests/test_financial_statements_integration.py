"""Document 08 acceptance tests (ZL-FSR-ENG-008): golden datasets, mutation
and metamorphic tests, the six-platform benchmark, the 60-case register,
the G0–G7 command centre and the FRP manifest (integration.py,
integration_store.py)."""
import json
import re
from decimal import Decimal as D
from pathlib import Path

import pytest

from app.domains.financial_statements import assembly, integration as g, integration_store as ic, packages, publication as pub
from app.domains.financial_statements.assembly import PackageInputs, Snapshot, assemble
from tests.test_financial_statements_assurance import PREPARER, _package, db  # noqa: F401 - the db fixture is used by name

FIXTURE = g.load_fixture("nb_synthetic_2026.json")


# ── golden, benchmark, mutation and metamorphic ─────────────────────────────

def test_golden_five_platform_figures():
    run = g.run_fixture(FIXTURE, "five_platform")
    assert g.check_fixture(FIXTURE, "five_platform", run) == []
    f = run["figures"]
    assert D(f["profit_before_tax"]) - D(f["tax"]) == D(f["profit"]) == D("154400")                      # PL-02
    assert run["balanced"] and run["total_debits"] == "3056300.00"                                         # NB-06: necessary only
    assert "COMPARATIVES_MISSING" in run["findings"] and "X-08_FAILED" in run["findings"]                  # NB-04, NB-05


def test_kriton_versus_five_raises_a_classification_dispute():
    five, kriton = g.run_fixture(FIXTURE, "five_platform"), g.run_fixture(FIXTURE, "kriton_001")
    assert g.check_fixture(FIXTURE, "kriton_001", kriton) == []
    dispute = g.compare_variants(five, kriton)
    assert dispute["difference"] == "14900.00" and dispute["profit_before_tax_agrees"]
    assert dispute["accounts"] == ["Bank charges", "Interest received"]
    assert g.compare_variants(five, five) is None


def test_classification_accounts_need_evidence():
    run = g.run_fixture(FIXTURE, "five_platform")
    assert {"Utilities", "Bank charges", "Interest received", "Marketing"} <= set(run["needs_evidence"])  # CLS-01..04


def test_metamorphic_row_order_and_split_accounts_keep_totals():
    base = g.run_fixture(FIXTURE, "five_platform")["figures"]
    for name, tb in g.metamorphic(FIXTURE["tb_csv"]).items():
        figures = g.run_fixture(FIXTURE, "five_platform", tb_csv=tb)["figures"]
        assert {k: D(v) for k, v in figures.items()} == {k: D(v) for k, v in base.items()}, name


def test_mutations_fail_for_the_right_reason():
    unbalanced = g.run_fixture(FIXTURE, "five_platform", tb_csv=g.mutate(FIXTURE["tb_csv"], "Cash at bank", 2, "187300.00"))
    assert not unbalanced["balanced"] and "UNBALANCED" in unbalanced["hard_stops"] and unbalanced["halted"] == "SOURCE_UNAPPROVED"
    # Retained earnings mutated with a matching cash change: balanced, but the prior-period link must catch it (BS-01).
    snap = Snapshot("tb", "sha256:x", True, {"bs.cash": D("100"), "eq.retained_earnings": D("-100")})
    prior = Snapshot("tb-prior", "sha256:p", True, {"bs.cash": D("90"), "eq.retained_earnings": D("-90")})
    result = assemble(PackageInputs(snapshot=snap, prior=prior))
    assert next(a for a in result["assertions"] if a["assertion_id"] == "X-10")["status"] == "FAIL"


def test_a_tampered_golden_fixture_aborts(tmp_path, monkeypatch):
    (tmp_path / "nb_synthetic_2026.json").write_text((g.GOLDEN / "nb_synthetic_2026.json").read_text().replace("1850000.00", "1850001.00"))
    (tmp_path / "MANIFEST.json").write_text((g.GOLDEN / "MANIFEST.json").read_text())
    monkeypatch.setattr(g, "GOLDEN", tmp_path)
    with pytest.raises(g.GoldenFixtureError, match="aborted"):
        g.load_fixture("nb_synthetic_2026.json")
    assert ic.golden_run("nb_synthetic_2026.json")["aborted"]


def test_borrowings_maturity_is_evidence_not_assumed():
    totals = {"bs.cash": D("1000"), "bs.borrowings": D("-1000")}
    unknown = assemble(PackageInputs(snapshot=Snapshot("t", "h", True, totals)))
    assert "BORROWINGS_MATURITY_MISSING" in {f["code"] for f in unknown["findings"]}
    split = assemble(PackageInputs(snapshot=Snapshot("t", "h", True, totals), schedules={"borrowings_due_after_one_year": "600"}))
    bs = next(s for s in split["statements"] if s["statement_id"] == "balance_sheet")
    lines = {l["line_id"]: l["amount"] for l in bs["lines"]}
    assert lines["borrowings_current"] == "400" and lines["borrowings_non_current"] == "600"


def test_public_filing_filleting_keeps_the_full_set():
    run_package = {"id": "p", "version": 1, "result": assemble(PackageInputs(snapshot=Snapshot("t", "h", True, {
        "bs.cash": D("100"), "pl.revenue": D("-100")})))}
    small = {"result": {"size_class": "small"}, "facts": {}}
    run_package["result"]["profile"]["family"] = "UK_COMPANIES_ACT"
    filed = pub.build_model(package=run_package, resolution=small, audience="public_filing", scale="units", state="WORKING_DRAFT")
    members = pub.build_model(package=run_package, resolution=small, audience="member_accounts", scale="units", state="WORKING_DRAFT")
    assert [o["statement_id"] for o in filed["omitted"]] == ["profit_or_loss"]
    assert any(s["statement_id"] == "profit_or_loss" for s in members["statements"])                   # full set intact
    assert [n["requirement_id"] for n in filed["notes"]] == [n["requirement_id"] for n in members["notes"]]


def test_taxonomy_registry_pins_versions():
    assert pub.TAXONOMIES["IFRS-2025"]["title"].endswith("(current for 2026)")
    assert all(not t["installed"] for t in pub.TAXONOMIES.values())
    assert all(a["status"] == "NOT_CERTIFIED" for a in pub.ADAPTERS.values())


def test_support_levels_never_claim_release_ready():
    assert all(s["level"] != "AUTHORISED_RELEASE_READY" for s in g.SUPPORT)


def test_the_register_lists_sixty_cases_and_points_at_real_tests():
    cases = g.register()
    assert len(cases) == 60 and len({c["id"] for c in cases}) == 60
    assert all(c["status"] == "NOT_RUN_IN_PRODUCT" for c in cases)                 # CI, not the register, reports passes
    root = Path(__file__).resolve().parents[1]
    for c in cases:
        assert c["tests"] or c["coverage"] in ("NOT_IMPLEMENTED", "NOT_APPLICABLE", "PARTIAL"), c["id"]
        assert c["coverage"] == "AUTOMATED" or c["note"], c["id"]
        for node in c["tests"]:
            path, name = node.split("::")
            assert re.search(rf"^(async )?def {name}\(", (root / path).read_text(encoding="utf-8"), re.M), node


# ── stored command centre and manifest ──────────────────────────────────────

async def test_command_centre_shows_the_chain_invariants_and_manifest(db):
    pkg = await _package(db)
    view = await ic.command_centre(db, PREPARER, pkg["id"])
    chain = {c["gate"]: c for c in view["chain"]}
    assert [c["gate"] for c in view["chain"]] == [f"G{i}" for i in range(8)]
    assert chain["G0"]["status"] == chain["G1"]["status"] == chain["G2"]["status"] == chain["G3"]["status"] == "PASS"
    assert chain["G5"]["status"] == "NOT_STARTED" and chain["G7"]["error_code"] == "FR-FILING-UNCONFIRMED"
    assert [i["id"] for i in view["invariants"]] == [f"INV-{i:02d}" for i in range(1, 17)]
    assert next(i for i in view["invariants"] if i["id"] == "INV-02")["status"] == "PASS"
    manifest = view["manifest"]
    assert manifest["status"] == "DRAFT" and manifest["sources"][0]["sha256"] and manifest["audit_event_root"].startswith("sha256:")
    assert (await ic.frp(db, PREPARER, pkg["id"]))["idempotency_key"] == manifest["idempotency_key"]   # OPS-01
    assert view["publication_disabled_reason"]


async def test_a_ruleset_change_invalidates_the_package(db, monkeypatch):
    pkg = await _package(db)
    monkeypatch.setitem(assembly.RULESET, "version", "2099.01.01")
    view = await packages.get(db, PREPARER, pkg["id"])
    assert view["state"] == "INVALIDATED" and any("rule set" in r for r in view["stale_reasons"])
    chain = (await ic.command_centre(db, PREPARER, pkg["id"]))["chain"]
    assert next(c for c in chain if c["gate"] == "G3")["error_code"] == "FR-REVIEW-INVALIDATED"


def test_the_golden_manifest_is_valid_json():
    assert set(json.loads((g.GOLDEN / "MANIFEST.json").read_text())) == {"nb_synthetic_2026.json"}
