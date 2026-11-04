"""Stage E1: the rule-table part classifier against the gold set, beside the
current Task Contract. Not collected by the normal test run; run it explicitly:

    CLASSIFIER_REPORT=report.json python -m pytest -q tests/classifier_report.py

Per group (tuning sets dev and dev2; held-back sets holdout, fresh, holdout3,
and the untouched holdout4): accuracy of needs_official, fact type, period
and tax countries; calibration (accuracy per confidence band); and the share
of parts a model would see (low confidence). No model, database or network.
"""
import json
import os
from collections import Counter, defaultdict
from pathlib import Path

from app.orchestration.part_classifier import classify_part
from app.orchestration.task_contract import build_task_contract

EVALS = Path(__file__).resolve().parents[1] / "evals"
GROUPS = ("dev", "dev2", "holdout", "fresh", "holdout3", "holdout4")


def _group(case):
    for flag in ("holdout4", "holdout3", "dev2"):
        if case.get(flag):
            return flag
    return "fresh" if case.get("fresh_holdout") else "holdout" if case["holdout"] else "dev"


def _check(expect, official, fact, period, countries):
    out = {"needs_official": official == expect["needs_official"], "fact_type": fact in expect["fact_type"],
           "period": period in expect["period"]}
    if expect["needs_official"] and expect["countries"]:
        out["countries"] = set(countries) == set(expect["countries"])
    return out


def test_classifier_report():
    cases = json.load(open(EVALS / "gold_retrieval_set.json"))["cases"]
    totals = {who: defaultdict(Counter) for who in ("classifier", "contract")}
    bands = defaultdict(Counter)
    routed = Counter()
    rows = []
    for case in cases:
        group = _group(case)
        contract = build_task_contract(case["question"])
        # The full part text (RetrievalRequirement.part is a 200-character summary).
        texts = [part.text for part in contract.parts] or [case["question"]]
        for index, (expect, text) in enumerate(zip(case["parts"], texts)):
            result = classify_part(text, case["question"])
            mine = _check(expect, result.needs_official, result.fact_type, result.period_kind, result.tax_countries)
            theirs = {}
            if index < len(contract.retrieval):
                r = contract.retrieval[index]
                theirs = _check(expect, r.needs_official, r.fact_type, r.period.kind, r.jurisdictions)
            for field, ok in mine.items():
                totals["classifier"][group][field] += ok
                totals["classifier"][group][field + "_n"] += 1
            for field, ok in theirs.items():
                totals["contract"][group][field] += ok
                totals["contract"][group][field + "_n"] += 1
            band = result.confidence["fact_type"]
            bands[band]["n"] += 1
            bands[band]["correct"] += mine["needs_official"] and mine["fact_type"]
            routed[group, band] += 1
            if not all(mine.values()):
                rows.append({"id": case["id"], "group": group, "question": case["question"][:140],
                             "wrong": [f for f, ok in mine.items() if not ok],
                             "expected": {k: expect[k] for k in ("needs_official", "fact_type", "countries", "period")},
                             "classifier": result.as_record(), "contract_right": all(theirs.values()) if theirs else None})
    def table(who):
        return {g: {f: f"{totals[who][g][f]}/{totals[who][g][f + '_n']}" for f in ("needs_official", "fact_type", "period", "countries")
                    if totals[who][g][f + "_n"]} for g in GROUPS}
    report = {"classifier": table("classifier"), "contract": table("contract"),
              "calibration": {b: f"{v['correct']}/{v['n']}" for b, v in bands.items()},
              "low_confidence_share": {g: f"{routed[g, 'low']}/{sum(routed[g, b] for b in ('high', 'medium', 'low'))}" for g in GROUPS},
              "disagreements": rows}
    out = os.environ.get("CLASSIFIER_REPORT")
    if out:
        Path(out).write_text(json.dumps(report, indent=1, ensure_ascii=False))
