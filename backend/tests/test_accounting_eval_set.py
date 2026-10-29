"""The reviewed accounting eval set (evals/accounting_review.json), offline.

Its expectations are themselves checked: every expected figure is recomputed
here with Decimal arithmetic, so a wrong expectation cannot make a wrong
answer pass. The scorer fails an answer whose treatment the accounting checks
flag even when every figure matches, and the release gate runs the set.
No model, database or network: running the set live costs model calls.
"""
import importlib.util
import json
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest

from app.domains.evaluation.pipeline_metrics import aggregate, measure

BACKEND = Path(__file__).resolve().parents[1]
DATASET = json.loads((BACKEND / "evals" / "accounting_review.json").read_text())
CASES = {case["id"]: case for case in DATASET["cases"]}


def _load(name):
    spec = importlib.util.spec_from_file_location(name, BACKEND / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runner = _load("run_baseline_eval")


def cents(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'), ROUND_HALF_UP):,}"


def whole(value: Decimal) -> str:
    return f"{value.quantize(Decimal('1'), ROUND_HALF_UP):,}"


LEASE = Decimal(50000) * (1 - Decimal("1.06") ** -5) / Decimal("0.06")
MONTHLY = Decimal("0.005")
# Each expected figure, worked independently of the dataset.
EXPECTED = {
    "acct-input-vat-inclusive": [whole(Decimal(6000) / 6)],
    "acct-output-vat-exclusive": [whole(Decimal(10000) * Decimal("0.2")), whole(Decimal(10000) * Decimal("1.2"))],
    "acct-vat-inclusive-takings": [whole(Decimal(1440) / 6), whole(Decimal(1440) * 5 / 6)],
    "acct-net-vat-return": [whole(Decimal(120000) * Decimal("0.2")), whole(Decimal(60000) / 6),
                            whole(Decimal(120000) * Decimal("0.2") - Decimal(60000) / 6)],
    "acct-journal-credit-sale-vat": [whole(Decimal(5000) * Decimal("1.2")), "5,000", whole(Decimal(5000) * Decimal("0.2"))],
    "acct-journal-tax-accrual": ["36,000"],
    "acct-expense-accrual": ["3,000"],
    "acct-prepayment": [whole(Decimal(12000) * 3 / 12), whole(Decimal(12000) * 9 / 12)],
    "acct-lease-asc842": [cents(LEASE)[:7], "50,000"],
    "acct-lease-ifrs16": [cents(LEASE / 5)[:6], cents(LEASE * Decimal("0.06"))[:6]],
    "acct-present-value": [cents(Decimal(10000) / Decimal("1.05") ** 3)],
    "acct-loan-payment": [cents(Decimal(200000) * MONTHLY / (1 - (1 + MONTHLY) ** -300))],
    "acct-percentage-increase": [whole((Decimal(552000) - 480000) / 480000 * 100)],
    "acct-gross-margin": [whole(Decimal(250000) - Decimal(162500)),
                          whole((Decimal(250000) - Decimal(162500)) / 250000 * 100)],
    "acct-currency-conversion": [whole(Decimal(2500) / Decimal("1.25"))],
    "acct-diluted-eps-convertible": [cents(Decimal(1000000) / 500000),
                                     cents((Decimal(1000000) + Decimal(60000) * Decimal("0.75")) / 550000)],
}

# The 11 provisional US GAAP / PCAOB cases (Stage 6, 27 Oct 2026), worked the same way.
ARO_BEFORE = Decimal(279200) * Decimal("1.06") ** 4
ARO_AFTER = Decimal(400000) / Decimal("1.06") ** 6
LEASE_842 = Decimal(90000) + Decimal(298991)
EXPECTED.update({
    "prov-asc350-40-cloud-implementation": [whole(Decimal(450000)), whole(Decimal(80000) + 60000 + 40000)],
    "prov-asc606-right-of-return": [whole(1000 * Decimal(200) * Decimal("0.9")), whole(1000 * Decimal(200) * Decimal("0.1")),
                                    whole(100 * Decimal(110)), whole(900 * Decimal(110))],
    "prov-asc323-downstream-profit": [whole((Decimal(100000) - 60000) * Decimal("0.3") * Decimal("0.4")),
                                      whole(Decimal(250000) * Decimal("0.4") - (Decimal(100000) - 60000) * Decimal("0.3") * Decimal("0.4"))],
    "prov-asc410-20-aro-downward-revision": [cents(ARO_BEFORE)[:7], whole(ARO_AFTER), whole(ARO_BEFORE - ARO_AFTER)[:6]],
    "prov-asc815-cash-flow-hedge": ["45,000", "60,000"],
    "prov-asc470-20-bonds-with-warrants": [
        whole(Decimal(3000000) * Decimal("1.02")),
        whole(Decimal(3000000) * Decimal("1.02") * 2880000 / (2880000 + 180000)),
        whole(Decimal(3000000) * Decimal("1.02") * 180000 / (2880000 + 180000)),
        whole(Decimal(3000000) - Decimal(3000000) * Decimal("1.02") * 2880000 / (2880000 + 180000))],
    "prov-asc842-finance-lease-advance": [whole(LEASE_842), cents(Decimal(298991) * Decimal("0.08"))[:6],
                                          cents(LEASE_842 / 5)[:6]],
    "prov-asc845-boot-no-commercial-substance": [
        f"{whole(Decimal(30000) / 150000 * 100)}%", whole((Decimal(150000) - 120000) * 30000 / 150000),
        whole(Decimal(120000) - 30000 + (Decimal(150000) - 120000) * 30000 / 150000)],
    "prov-asc740-valuation-allowance": [whole(Decimal(800000) - 300000)],
    "prov-asc280-segment-measure": ["600,000", whole((Decimal(12000000) + 7000000 + 3000000) / 10)],
    "prov-pcaob-sampling-deviations": [f"{(Decimal(2) / 45 * 100).quantize(Decimal('0.1'), ROUND_HALF_UP)}"],
})
PROVISIONAL = [case_id for case_id in CASES if case_id.startswith("prov-")]


def test_the_set_is_well_formed():
    assert DATASET["status"] == "proposed" and len(CASES) == len(DATASET["cases"]) == 31
    for case in DATASET["cases"]:
        assert {"id", "category", "topic", "question", "conclusion"} <= set(case), case["id"]
        assert case.get("must_contain") or case.get("must_contain_any") or case.get("must_contain_groups"), case["id"]


def test_the_eleven_us_cases_are_provisional_and_claim_no_evidence():
    assert len(PROVISIONAL) == 11
    for case_id in PROVISIONAL:
        case = CASES[case_id]
        assert case["provisional"] is True
        assert case["review_status"] == "provisional: awaiting approval by a qualified accountant"
        assert "No authorised FASB or PCAOB evidence" in case["evidence_note"]
        assert case["jurisdiction"].startswith("United States")
        # Never a citation expectation: there is no authorised source to cite.
        assert not {"must_cite", "citations", "min_citations"} & set(case), case_id
    # The 20 earlier cases are untouched by the provisional markers.
    assert not any(CASES[case_id].get("provisional") for case_id in CASES if case_id not in PROVISIONAL)


def test_the_plan_topics_are_covered():
    topics = {case["topic"] for case in DATASET["cases"]}
    assert {"input VAT", "output VAT", "tax-inclusive amounts", "journal entries", "expense recognition versus payment",
            "lease accounting", "IFRS versus US GAAP", "present values", "percentages", "currency conversion",
            "follow-up questions"} <= topics


@pytest.mark.parametrize("case_id", sorted(EXPECTED))
def test_every_expected_figure_is_recomputed(case_id):
    assert CASES[case_id]["must_contain"] == EXPECTED[case_id]


def test_wrong_answers_named_in_the_set_really_are_wrong():
    assert whole(Decimal(6000) * Decimal("0.2")) in CASES["acct-input-vat-inclusive"]["must_not_contain"]
    assert whole(Decimal(1440) * Decimal("0.2")) in CASES["acct-vat-inclusive-takings"]["must_not_contain"]
    assert whole(Decimal(2500) * Decimal("1.25")) in CASES["acct-currency-conversion"]["must_not_contain"]
    assert cents(LEASE / 5 + LEASE * Decimal("0.06"))[:6] in CASES["acct-lease-asc842"]["must_not_contain"]


def _result(text):
    return {"outcome": "answered", "answer": {"text": text, "citations": []}}


def test_a_right_answer_passes():
    text = ("Output VAT = £120,000 × 20% = £24,000. Input VAT = £60,000 × 1/6 = £10,000. "
            "VAT payable = £24,000 − £10,000 = £14,000.")
    case = {**CASES["acct-net-vat-return"], "source": "accounting"}
    assert runner.score(case, _result(text)) == []


def test_right_figures_with_the_wrong_treatment_fail():
    # The 24 Oct follow-up: figures that add up, treatment that does not.
    text = ("Purchases £50 000 (VAT‑inclusive). Input VAT: £50 000.\n"
            "Total tax burden = VAT payable + corporation tax = £140 000 + £28 500 = £168 500.\nIllustrative example.")
    case = {**CASES["acct-follow-up-grounded-example"], "source": "accounting"}
    failures = runner.score(case, _result(text))
    assert "treatment: collected_tax_as_cost, tax_equals_inclusive_amount" in failures
    metrics = measure(case, _result(text), failures)
    assert metrics["treatment"] is False
    assert aggregate([{"metrics": metrics}])["treatment"] == {"passed": 0, "total": 1, "rate": 0.0}


def test_the_runner_and_the_gate_include_the_set():
    assert [case["id"] for case in runner.load_cases("accounting")] == list(CASES)
    gate = _load("release_gate")
    assert gate.DATASETS["accounting"] == "accounting"
    config = json.loads((BACKEND / "evals" / "release_gates.json").read_text())["sets"]["accounting"]
    verdict = gate.judge("accounting", [{"id": "acct-present-value", "category": "calculation", "passed": False,
                                         "failures": ["content: missing '8,638.38'"], "metrics": {}}],
                         config, baseline={"acct-present-value": True})
    assert verdict["regressions"] == ["acct-present-value"]        # a case that passed before blocks
    assert not verdict["below_minimum"]                            # no minimum until sign-off


def test_an_answer_its_own_evidence_check_flagged_fails():
    case = {**CASES["acct-present-value"], "source": "accounting"}
    result = {"outcome": "answered", "answer": {"text": "£10,000 ÷ 1.05³ = £8,638.38", "citations": [], "limitations": [
        "Evidence check: 5% is not stated in the source cited for it. Have these statements reviewed before relying on them."]}}
    failures = runner.score(case, result)
    assert failures == ["evidence: Evidence check: 5% is not stated in the source cited for it. Have these statements "
                        "reviewed before relying on them."]
    assert measure(case, result, failures)["evidence"] is False
