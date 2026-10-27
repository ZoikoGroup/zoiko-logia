"""End-to-end integration, golden-dataset testing and production acceptance
(ZoikoLogia Document 08, ZL-FSR-ENG-008).

Orchestrates nothing new: it reads the controlled decisions of Documents
02–07 and shows them as one G0–G7 chain, sixteen invariants and one
immutable FinancialReportingPackage (FRP) manifest. Golden fixtures are
signed by digest and run through the real engines; a tampered fixture
aborts (OPS-04). The 60 acceptance cases are a register that points at
executable tests — it never reports PASS on its own; CI does (§13).

Support is declared per framework (§16): nothing is AUTHORISED_RELEASE_READY,
because the rule packs are unreviewed and no filing adapter is certified.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from decimal import Decimal
from pathlib import Path

from . import journals, mapping, standards
from .assembly import PackageInputs, Snapshot, assemble
from .findings import blocking
from .resolutions import facts_from
from .service import run_intake

GOLDEN = Path(__file__).with_name("golden")             # fixtures + MANIFEST.json of their sha256 digests

SUPPORT_LEVELS = ("EXPERIMENTAL", "SUPPORTED_INTERNAL_DRAFT", "PROFESSIONALLY_REVIEWABLE", "AUTHORISED_RELEASE_READY")
SUPPORT = [
    {"scope": "UK FRS 102 (incl. Section 1A), individual accounts", "level": "SUPPORTED_INTERNAL_DRAFT",
     "why": "Engines and tests exist; rule packs are unreviewed and filing is not certified."},
    {"scope": "UK FRS 105 micro-entities", "level": "EXPERIMENTAL", "why": "Costs-by-nature format is not implemented."},
    {"scope": "UK FRS 101 reduced disclosure", "level": "EXPERIMENTAL", "why": "Disclosure exemptions are not modelled."},
    {"scope": "IFRS (UK-adopted or other)", "level": "EXPERIMENTAL", "why": "IAS 1 / IFRS 18 layouts exist; local endorsement is not verified."},
    {"scope": "US GAAP", "level": "UNSUPPORTED", "why": "Reference routing only (Document 03)."},
    {"scope": "Groups, interims beyond condensed layouts, sector entities", "level": "UNSUPPORTED",
     "why": "Consolidation and sector packs are refused, not performed."},
]
ERRORS = {
    "FR-APPLICABILITY-AMBIGUOUS": "No unique authorised framework/edition; evidence requirements returned, compliance blocked.",
    "FR-SOURCE-UNRECONCILED": "Source or ledger invariants failed; the report is held with the account-level discrepancy.",
    "FR-CLASSIFICATION-UNSUPPORTED": "A mapping lacks economically relevant evidence or approval.",
    "FR-DISCLOSURE-MISSING": "A mandatory note is absent or unapproved.",
    "FR-REVIEW-INVALIDATED": "Source, rule pack or report changed after review; signatures are obsolete.",
    "FR-PRESENTATION-DIVERGENCE": "A rendered channel differs from the signed semantic model.",
    "FR-FILING-UNCONFIRMED": "No official acceptance receipt; the state is never FILED.",
}

# §13: each case points at executable tests; coverage is stated honestly. A case "passes" only in CI.
_A, _S, _I, _P, _Q, _T, _U, _N = ("tests/test_financial_statements_assembly.py", "tests/test_financial_statements_standards.py",
                                  "tests/test_financial_statements_intake.py", "tests/test_financial_statements_publication.py",
                                  "tests/test_financial_statements_assurance.py", "tests/test_financial_statements_store.py",
                                  "tests/test_financial_statements_integration.py", None)
REGISTER = [
    ("APP-01", "FR-005", "FRS102 pre-/post-Jan-2026 start selects correct amendment cohort", "AUTOMATED",
     [(_S, "test_at03_at04_frs102_periodic_review_by_period_start")], ""),
    ("APP-02", "FR-005", "FRS102 supplier-finance disclosure earlier-effective exception respected", "AUTOMATED",
     [(_S, "test_at03_at04_frs102_periodic_review_by_period_start")], ""),
    ("APP-03", "FR-005", "IFRS18 2027 early-adoption switch changes presentation pack", "AUTOMATED",
     [(_S, "test_at06_at07_ifrs18_only_from_2027_unless_adopted_early"),
      (_A, "test_at06_ifrs18_presents_its_categories_and_starts_cash_flows_at_operating_profit")], ""),
    ("APP-04", "FR-005", "FRS 12A vs 12B adapted formats selected by period start", "AUTOMATED",
     [(_S, "test_at05_uk_adapted_formats_from_2027")], ""),
    ("APP-05", "FR-005", "FRS105 micro status lacks proof and blocks eligibility claim", "AUTOMATED",
     [(_S, "test_at12_frs105_without_size_evidence_stays_unproven_and_groups_cannot_use_it")], ""),
    ("APP-06", "FR-005", "US GAAP request lacks authorised pack and routes unsupported", "AUTOMATED",
     [(_S, "test_at09_a_us_registrant_gets_us_gaap_not_uk_formats"),
      (_A, "test_at01_at34_an_unsupported_regime_gets_no_uk_format_and_no_claim")], ""),
    ("SRC-01", "FR-006", "Workbook duplicate row does not duplicate revenue", "AUTOMATED",
     [(_I, "test_at07_a_duplicated_account_is_flagged_not_merged"), (_U, "test_metamorphic_row_order_and_split_accounts_keep_totals")], ""),
    ("SRC-02", "FR-006", "Misbalanced trial balance detected before assembly", "AUTOMATED",
     [(_I, "test_at09_debits_not_equal_to_credits_block_at_full_precision"), (_U, "test_mutations_fail_for_the_right_reason")], ""),
    ("SRC-03", "FR-006", "Balanced but omitted invoice remains a completeness exception", "PARTIAL",
     [(_Q, "test_a_first_run_is_blocked_and_says_what_was_not_checked")],
     "Completeness of liabilities is reported as untested; there is no invoice-level completeness test."),
    ("SRC-04", "FR-006", "Reversed-sign liability identified by control logic", "AUTOMATED",
     [(_I, "test_suspense_sign_anomaly_and_control_total_checks")], ""),
    ("SRC-05", "FR-006", "Multi-currency ledger without a rate is caught", "AUTOMATED",
     [(_I, "test_at06_mixed_currencies_are_not_summed"), (_A, "test_at21_at24_groups_and_mixed_currencies_are_hard_stops")], ""),
    ("SRC-06", "FR-006", "Uploaded narrative asking for a silent journal edit changes nothing", "AUTOMATED",
     [(_Q, "test_evidence_closes_findings_injection_is_ignored_and_withdrawal_reopens"),
      (_A, "test_at19_at27_at28_at33_note_text_is_checked_as_data")], ""),
    ("CLS-01", "FR-008", "Utilities routed by cost-centre evidence", "AUTOMATED",
     [(_I, "test_at12_utilities_needs_evidence_and_gets_no_line"), (_U, "test_classification_accounts_need_evidence")], ""),
    ("CLS-02", "FR-008", "Bank fees vs financing costs not classified by label", "AUTOMATED",
     [(_I, "test_at15_bank_charges_are_not_defaulted"), (_U, "test_classification_accounts_need_evidence")], ""),
    ("CLS-03", "FR-008", "Interest income £12,000 not declared operating without substance", "AUTOMATED",
     [(_U, "test_classification_accounts_need_evidence")], ""),
    ("CLS-04", "FR-008", "Marketing £42,600 not assumed distribution without proof", "AUTOMATED",
     [(_U, "test_classification_accounts_need_evidence")], ""),
    ("CLS-05", "FR-008", "Bad debt / expected-loss policy and evidence requested", "PARTIAL", [],
     "Bad-debt accounts map to administrative expenses without an expected-credit-loss evidence request."),
    ("CLS-06", "FR-008", "Tax expense equals tax payable but unpaid conclusion blocked", "AUTOMATED",
     [(_A, "test_at14_tax_payable_is_not_assumed_from_the_charge")], ""),
    ("BS-01", "FR-012", "A=L+E fails on mutated retained earnings", "AUTOMATED",
     [(_A, "test_at07_a_one_pound_residual_blocks_at_exact_precision"), (_U, "test_mutations_fail_for_the_right_reason")], ""),
    ("BS-02", "FR-012", "Current/non-current debt respects contractual dates", "AUTOMATED",
     [(_U, "test_borrowings_maturity_is_evidence_not_assumed")], ""),
    ("BS-03", "FR-012", "Restricted cash reclassification aligns note and cash flow", "NOT_IMPLEMENTED", [],
     "There is no restricted-cash concept in the statement catalogue."),
    ("BS-04", "FR-012", "Lease obligation and right-of-use asset coherent", "NOT_IMPLEMENTED", [],
     "There are no lease concepts in the statement catalogue."),
    ("BS-05", "FR-012", "Inventory/receivables adjustments flow through balance sheet and profit", "PARTIAL",
     [(_A, "test_at05_a_retrospective_correction_under_ifrs_needs_a_third_balance_sheet")],
     "Approved journals flow through; inventory and receivable adjustment fixtures are not built."),
    ("BS-06", "FR-012", "NCI and consolidation entries reconcile group equity", "BLOCKED_AS_UNSUPPORTED",
     [(_A, "test_at21_at24_groups_and_mixed_currencies_are_hard_stops")], "Consolidation is refused, not performed."),
    ("PL-01", "FR-013", "£14,900 Kriton-vs-five difference raises a comparison exception", "AUTOMATED",
     [(_U, "test_kriton_versus_five_raises_a_classification_dispute")], ""),
    ("PL-02", "FR-013", "Profit − tax sign handled correctly", "AUTOMATED", [(_U, "test_golden_five_platform_figures")], ""),
    ("PL-03", "FR-013", "OCI item wrongly booked to income detected", "NOT_IMPLEMENTED", [],
     "There are no OCI concepts; OCI is presented as nil."),
    ("PL-04", "FR-013", "Profit flows into changes in equity and reserves roll-forward", "AUTOMATED",
     [(_A, "test_cash_flow_from_evidenced_movements_and_at11_a_cash_mismatch")], ""),
    ("PL-05", "FR-013", "£40,000 dividends not an operating expense", "AUTOMATED",
     [(_A, "test_at15_unsubstantiated_dividends_stay_in_equity_never_in_profit")], ""),
    ("PL-06", "FR-013", "Prior-year restatement without opening bridge blocks release", "AUTOMATED",
     [(_A, "test_at05_a_retrospective_correction_under_ifrs_needs_a_third_balance_sheet")], ""),
    ("CF-01", "FR-015", "Cash flow category mismatch flagged", "PARTIAL",
     [(_A, "test_cash_flow_from_evidenced_movements_and_at11_a_cash_mismatch")],
     "Categories follow one fixed policy; a misclassified schedule shows only as a roll-forward difference."),
    ("CF-02", "FR-015", "Indirect-method double counting detected", "AUTOMATED",
     [(_A, "test_cash_flow_from_evidenced_movements_and_at11_a_cash_mismatch")], ""),
    ("CF-03", "FR-015", "Closing cash differs from the balance sheet and blocks", "AUTOMATED",
     [(_A, "test_cash_flow_from_evidenced_movements_and_at11_a_cash_mismatch")], ""),
    ("CF-04", "FR-015", "Foreign-currency translation reconciled separately", "PARTIAL",
     [(_A, "test_at21_at24_groups_and_mixed_currencies_are_hard_stops")],
     "The FX effect is a separate line; translation is refused without an FX policy."),
    ("CF-05", "FR-015", "Non-cash lease addition not a cash movement", "NOT_IMPLEMENTED", [], "There is no non-cash lease schedule."),
    ("CF-06", "FR-015", "Exempt cash flow tested as an exemption, not an omission", "AUTOMATED",
     [(_A, "test_one_set_of_facts_ties_every_statement_out")], ""),
    ("DISC-01", "FR-016", "Mandatory accounting policy missing blocks", "AUTOMATED",
     [(_A, "test_at13_a_missing_revenue_policy_blocks_until_evidenced_and_approved")], ""),
    ("DISC-02", "FR-016", "FY2025 comparative missing blocks statutory issue", "AUTOMATED",
     [(_A, "test_at16_comparatives_are_never_invented")], ""),
    ("DISC-03", "FR-016", "Tax note without current/deferred split is an evidence gap", "AUTOMATED",
     [(_A, "test_at14_tax_payable_is_not_assumed_from_the_charge")], ""),
    ("DISC-04", "FR-016", "Related-party disclosures not omitted for want of names", "AUTOMATED",
     [(_A, "test_at19_at27_at28_at33_note_text_is_checked_as_data")], ""),
    ("DISC-05", "FR-016", "Post-balance-sheet events review missing requires confirmation", "AUTOMATED",
     [(_Q, "test_a_first_run_is_blocked_and_says_what_was_not_checked")], ""),
    ("DISC-06", "FR-016", "A future effective rule does not alter historical disclosures", "AUTOMATED",
     [(_S, "test_at03_at04_frs102_periodic_review_by_period_start")], ""),
    ("OUT-01", "FR-019", "HTML vs Word: same values, units and note references", "AUTOMATED",
     [(_P, "test_pub_t001_every_channel_reads_back_equal_to_the_model")], ""),
    ("OUT-02", "FR-019", "PDF page breaks keep note references and line headings", "AUTOMATED",
     [(_P, "test_pub_t001_every_channel_reads_back_equal_to_the_model"), (_P, "test_pub_t006_an_inverted_sign_in_the_pdf_fails_parity")], ""),
    ("OUT-03", "FR-019", "XBRL polarity and scaling from the semantic model", "BLOCKED_AS_UNSUPPORTED",
     [(_P, "test_pub_t019_tagging_is_blocked_without_an_installed_licensed_taxonomy")],
     "Structured tagging is blocked until a licensed taxonomy is installed."),
    ("OUT-04", "FR-019", "Filleted public filing keeps the approved full set intact", "AUTOMATED",
     [(_U, "test_public_filing_filleting_keeps_the_full_set")], ""),
    ("OUT-05", "FR-019", "IFRS taxonomy for 2026 pinned to the published current version", "AUTOMATED",
     [(_U, "test_taxonomy_registry_pins_versions")], ""),
    ("OUT-06", "FR-019", "Filing without an authority receipt stays pending, not completed", "AUTOMATED",
     [(_P, "test_issue_after_release_statutory_stays_blocked_and_filing_is_never_sent")], ""),
    ("GOV-01", "FR-020", "Another tenant cannot retrieve evidence or downloads", "AUTOMATED",
     [(_A, "test_at29_another_tenant_is_denied_and_the_attempt_logged"), (_P, "test_pub_t031_another_tenant_cannot_download"),
      (_Q, "test_t24_another_tenant_is_denied_and_logged")], ""),
    ("GOV-02", "FR-020", "Prompt injection in an invoice changes no rule", "AUTOMATED",
     [(_Q, "test_evidence_closes_findings_injection_is_ignored_and_withdrawal_reopens")], ""),
    ("GOV-03", "FR-020", "A false accounting citation is refused as a source", "PARTIAL",
     [(_Q, "test_maker_checker_on_decisions")], "Citations are required and recorded, not verified against licensed source text."),
    ("GOV-04", "FR-020", "A changed rule pack invalidates signatures", "AUTOMATED",
     [(_U, "test_a_ruleset_change_invalidates_the_package"),
      (_S, "test_at19_a_replaced_approval_needs_revalidation_and_keeps_its_pinned_pack")], ""),
    ("GOV-05", "FR-020", "No reviewer signature cannot pass the review gate", "AUTOMATED",
     [(_Q, "test_the_full_ladder_to_an_internal_release_certificate")], ""),
    ("GOV-06", "FR-020", "A failed filing retry is idempotent and auditable", "AUTOMATED",
     [(_P, "test_issue_after_release_statutory_stays_blocked_and_filing_is_never_sent")], ""),
    ("OPS-01", "FR-023", "Same idempotency request returns the same job and snapshot", "AUTOMATED",
     [(_A, "test_a_package_goes_stale_when_its_snapshot_changes"), (_P, "test_a_draft_renders_watermarked_and_cannot_be_issued")], ""),
    ("OPS-02", "FR-023", "Partial queue outage replays without missing events", "NOT_APPLICABLE", [],
     "Handoffs are synchronous database transactions; there is no queue to replay."),
    ("OPS-03", "FR-023", "Database rollback restores a consistent package version", "NOT_IMPLEMENTED", [],
     "Restore and rollback rehearsal is an operational control for SRE."),
    ("OPS-04", "FR-023", "A golden fixture hash mismatch aborts the suite safely", "AUTOMATED",
     [(_U, "test_a_tampered_golden_fixture_aborts")], ""),
    ("OPS-05", "FR-023", "High-volume batch keeps tenant scopes isolated", "PARTIAL",
     [(_T, "test_another_tenant_cannot_see_the_trial_balance")], "Isolation is tested per object; no high-volume batch test exists."),
    ("OPS-06", "FR-023", "A deadline alert never publishes or files", "PARTIAL",
     [(_P, "test_issue_after_release_statutory_stays_blocked_and_filing_is_never_sent")],
     "No deadline automation exists; issue and filing always need a named person."),
]


def register() -> list[dict]:
    return [{"id": i, "feature": f, "stimulus": s, "coverage": c, "tests": [f"{path}::{name}" for path, name in t],
             "note": n, "status": "NOT_RUN_IN_PRODUCT"} for i, f, s, c, t, n in REGISTER]


# ── golden datasets (§9) ────────────────────────────────────────────────────

class GoldenFixtureError(RuntimeError):
    pass


def load_fixture(name: str) -> dict:
    """OPS-04: a fixture whose bytes do not match the signed digest aborts."""
    raw = (GOLDEN / name).read_bytes().replace(b"\r\n", b"\n")      # line endings differ by checkout, not content
    expected = json.loads((GOLDEN / "MANIFEST.json").read_text()).get(name)
    actual = hashlib.sha256(raw).hexdigest()
    if expected != actual:
        raise GoldenFixtureError(f"Golden fixture {name} does not match its signed digest; the run is aborted.")
    return json.loads(raw)


def run_fixture(fixture: dict, variant: str, *, tb_csv: str | None = None) -> dict:
    """The fixture through the real engines: intake → reviewer decisions → snapshot → resolution → assembly."""
    content = (tb_csv or fixture["tb_csv"]).encode()
    intake = run_intake("golden.csv", content, uploaded_by="golden-preparer")
    choices = fixture["variants"][variant]["mappings"]
    approved, needs = [], []
    for p in intake.mappings:
        if p.status == mapping.NEEDS_EVIDENCE:
            needs.append(p.account_name)
            approved.append(mapping.approve(p, reviewer="golden-reviewer", line_id=choices[p.account_name],
                                            evidence_ref="fixture-evidence"))
        elif p.status == mapping.SUGGESTED:
            approved.append(mapping.approve(p, reviewer="golden-reviewer", line_id=choices.get(p.account_name, p.line_id)))
        else:
            approved.append(p)
    hard = blocking(intake.findings)
    snapshot = Snapshot(trial_balance_id=fixture["id"], content_hash="sha256:" + hashlib.sha256(content).hexdigest(),
                        approved=not hard and all(a.status == mapping.APPROVED for a in approved),
                        line_totals=journals.line_totals(approved), period_end=fixture["facts"]["period_end"],
                        findings=tuple(f.to_dict() for f in intake.findings))
    result = standards.resolve(facts_from(fixture["facts"]), approved=True).to_dict()
    resolution = {"id": f"{fixture['id']}-resolution", "revision": 1, "state": "FROZEN",
                  "rule_pack_digest": result["rule_pack"]["digest"], "facts": fixture["facts"], "result": result}
    package = assemble(PackageInputs(snapshot=snapshot, resolution=resolution, schedules=fixture.get("schedules", {})))
    figures, balance = {}, {}
    for s in package.get("statements", []):
        for l in s.get("lines", []):
            if s["statement_id"] == "profit_or_loss":
                figures[l["line_id"]] = l["amount"]
            elif s["statement_id"] == "balance_sheet":
                balance[l["line_id"]] = l["amount"]
    return {"variant": variant, "balanced": intake.report.balanced, "total_debits": str(intake.report.total_debits),
            "hard_stops": [f.code for f in hard], "needs_evidence": sorted(needs), "figures": figures, "balance_sheet": balance,
            "assertions": {a["assertion_id"]: a["status"] for a in package.get("assertions", [])},
            "findings": sorted({f["code"] for f in package.get("findings", [])}), "halted": package.get("halted"),
            "mappings": {a.account_name: a.line_id for a in approved}}


def check_fixture(fixture: dict, variant: str, run: dict) -> list[str]:
    """Differences from the signed expectations; an empty list means the oracle is met."""
    want, issues = fixture["expected"], []

    def same(got, expected) -> bool:
        return got is not None and Decimal(str(got)) == Decimal(str(expected))
    for k, v in want.get(variant, {}).items():
        if not same(run["figures"].get(k), v):
            issues.append(f"{k}: expected {v}, got {run['figures'].get(k)}")
    if variant == "five_platform":
        for k, v in want["balance_sheet"].items():
            if not same(run["balance_sheet"].get(k), v):
                issues.append(f"balance sheet {k}: expected {v}, got {run['balance_sheet'].get(k)}")
        for k, v in want["assertions"].items():
            if run["assertions"].get(k) != v:
                issues.append(f"{k}: expected {v}, got {run['assertions'].get(k)}")
        missing = set(want["findings_include"]) - set(run["findings"])
        if missing:
            issues.append(f"expected findings missing: {sorted(missing)}")
        if sorted(want["needs_evidence"]) != run["needs_evidence"]:
            issues.append(f"needs-evidence accounts: expected {sorted(want['needs_evidence'])}, got {run['needs_evidence']}")
        if not same(run["total_debits"], want["tb_total"]):
            issues.append(f"trial balance total: expected {want['tb_total']}, got {run['total_debits']}")
    return issues


def compare_variants(a: dict, b: dict) -> dict | None:
    """PL-01: two classifications of the same facts that move operating profit but not PBT are a dispute, not a fact."""
    op_a, op_b = Decimal(a["figures"]["operating_profit"]), Decimal(b["figures"]["operating_profit"])
    pbt_a, pbt_b = Decimal(a["figures"]["profit_before_tax"]), Decimal(b["figures"]["profit_before_tax"])
    if op_a == op_b:
        return None
    moved = sorted(k for k in a["mappings"] if a["mappings"][k] != b["mappings"].get(k))
    return {"code": "CLASSIFICATION_DISPUTE", "operating_profit": {a["variant"]: str(op_a), b["variant"]: str(op_b)},
            "difference": str(abs(op_a - op_b)), "profit_before_tax_agrees": pbt_a == pbt_b, "accounts": moved,
            "disposition": "Transaction-substance evidence is required; neither presentation is approved by agreement of PBT."}


def metamorphic(tb_csv: str) -> dict:
    """Semantically equivalent inputs (§9): rows reversed, and revenue split into two accounts."""
    rows = list(csv.reader(io.StringIO(tb_csv)))
    header, body = rows[0], rows[1:]
    out = io.StringIO()
    csv.writer(out, lineterminator="\n").writerows([header, *reversed(body)])
    split = io.StringIO()
    writer = csv.writer(split, lineterminator="\n")
    writer.writerow(header)
    for r in body:
        if r[1] == "Revenue":
            total = Decimal(r[3])
            writer.writerow([r[0], "Revenue - UK", "", str(total - Decimal("600000.00"))])
            writer.writerow(["4001", "Revenue - export", "", "600000.00"])
        else:
            writer.writerow(r)
    return {"reversed": out.getvalue(), "revenue_split": split.getvalue()}


def mutate(tb_csv: str, account: str, column: int, value: str) -> str:
    rows = list(csv.reader(io.StringIO(tb_csv)))
    for r in rows[1:]:
        if r[1] == account:
            r[column] = value
    out = io.StringIO()
    csv.writer(out, lineterminator="\n").writerows(rows)
    return out.getvalue()
