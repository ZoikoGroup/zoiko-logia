"""
Bounded evaluation of classify_query_llm() (semantic) vs. the existing regex
pipeline (_fallback_classify, which composes the SAME functions
ask_kriton() already uses) — Phase 4/4B support tooling.

NOT the 300-500-case suite a full production evaluation would eventually
want; this is ~42 hand-picked cases (27 dev + 15 holdout) across the
categories that matter most, meant to be run manually while reviewing this
migration, not as a CI gate yet.

Infra failures (rate limits, timeouts, schema-validation errors) are tracked
SEPARATELY from semantic misses — a Groq daily-quota exhaustion must never
silently count as "the classifier got this wrong" (see
query_classifier_llm.py's ClassificationAttempt / failure_category).

Results are persisted incrementally to results/<set>_results.json as each
case completes, so a quota interruption partway through does not lose
already-completed work — rerun with --resume to pick up where it left off
(already-succeeded cases are skipped; cases that previously failed for an
infra reason, not a semantic one, are retried).

Usage:
    python3 scripts/evaluate_query_classifier.py [--dev-only | --holdout-only]
        [--max-cases N] [--resume]

Requires GROQ_API_KEY (makes one real LLM call per case attempted).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
load_dotenv()

from app.orchestration.query_classifier import _fallback_classify
from app.orchestration.query_classifier_llm import attempt_classify_query_llm

RESULTS_DIR = Path(__file__).resolve().parent / "results"

# Failure categories that mean "we don't know what the model would have
# said" — must never be scored as a semantic miss. Contrast with a
# successful call whose intent is simply wrong, or None (a real "I don't
# know"/refusal-shaped response), which ARE semantic signal.
_INFRA_FAILURE_CATEGORIES = {
    "rate_limit_day", "rate_limit_minute", "APITimeoutError", "InternalServerError",
    "APIConnectionError", "not_configured", "AuthenticationError",
}

# (query, category, expected_intent_or_None, expected_wants_visualization, expected_out_of_scope)
CASES: list[tuple[str, str, str | None, bool, bool]] = [
    ("Show India CPI for the last ten years.", "trend-direct", "TREND", True, False),
    ("How has consumer inflation in India evolved over roughly the past decade?", "trend-paraphrase", "TREND", True, False),
    ("Has the burden on UK companies become heavier or lighter since 2020?", "trend-paraphrase", "TREND", True, False),
    ("Is Apple's stock worth more or less than it was two months ago?", "trend-paraphrase", "TREND", True, False),
    ("How spread out are these 300 tax liabilities?", "distribution-paraphrase", "DISTRIBUTION", True, False),
    ("How volatile has UK inflation been over the past year?", "distribution-paraphrase", "DISTRIBUTION", True, False),
    ("Does taxable income appear related to the amount of tax ultimately paid?", "correlation-paraphrase", "CORRELATION", True, False),
    ("Show how the PO, receipt, supplier invoice and payment are connected: PO leads to Receipt; Receipt leads to Invoice; Invoice leads to Payment.", "relationship", "RELATIONSHIP", True, False),
    ("Company A owns Company B, and Company B invoices Company C.", "relationship", "RELATIONSHIP", True, False),
    ("Who owns Barclays?", "composition", "COMPOSITION", True, False),
    ("Walk me through the steps: Invoice Received, Approved, Paid, Reconciled.", "process", "PROCESS", True, False),
    ("Show the yearly UK CPI values as columns.", "explicit-chart", "TREND", True, False),
    ("Show ten years of UK inflation as a pie chart.", "explicit-chart-mismatched", "TREND", True, False),
    ("What is a deferred tax liability?", "definitional", None, False, False),
    ("Explain PAYE to me.", "definitional", None, False, False),
    ("What's the difference between a tax credit and a tax deduction?", "definitional", None, False, False),
    ("What is the current GBP to USD exchange rate?", "current-metric", "CURRENT_METRIC", False, False),
    ("Compare the rates.", "ambiguous", None, False, False),
    ("Show me the numbers.", "ambiguous", None, False, False),
    ("Who won last night's football match?", "out-of-scope", None, False, True),
    ("What's a good recipe for biryani?", "out-of-scope", None, False, True),
    ("What's the weather like in London tomorrow?", "out-of-scope", None, False, True),
    ("Frontend-Service depends on Auth-API; Auth-API depends on User-Database.", "out-of-scope-shape-trap", None, False, True),
    ("Partner reviews Audit File; Audit File is reviewed by Quality Control.", "relationship-reviews", "RELATIONSHIP", True, False),
    ("Should my company claim R&D tax credits for internally-used software?", "advice", None, False, False),
    ("Compare UK and India corporation tax rates over the last ten years.", "comparison", "TREND", True, False),
    ("Which of Germany or France has had the heavier inflation burden this year?", "comparison-paraphrase", "TREND", True, False),
]

# Held out from prompt-tuning: written AFTER the CORRELATION/RELATIONSHIP/
# COMPOSITION prompt language in query_classifier_llm.py's _SYSTEM, in fresh
# phrasings not lifted from CASES above or from the prompt's own examples —
# labels here are FROZEN. If one looks wrong after a run, flag it in the
# report; do not silently edit it (see conversation: "keep holdout labels
# frozen").
HOLDOUT_CASES: list[tuple[str, str, str | None, bool, bool]] = [
    ("Do audit adjustments tend to rise and fall together with total company revenue?", "correlation-contrast", "CORRELATION", True, False),
    ("Is there a link between a subsidiary's headcount and its parent's reported costs?", "correlation-contrast", "CORRELATION", True, False),
    ("Which subsidiaries report up to Meridian Holdings?", "relationship-contrast", "RELATIONSHIP", True, False),
    ("Beta Ltd invoices Gamma Inc, and Gamma Inc pays Delta Supplies.", "relationship-contrast", "RELATIONSHIP", True, False),
    ("What percentage of Tesco does each major investor hold?", "composition-contrast", "COMPOSITION", True, False),
    ("Northwind Traders owns 40% of Southgate Logistics.", "relationship-contrast", "RELATIONSHIP", True, False),
    ("Show Germany CPI for the last twenty years.", "trend-spelled-number", "TREND", True, False),
    ("Compare France and Japan inflation over the last five years.", "trend-spelled-number", "TREND", True, False),
    ("How consistent have monthly payroll costs been this year?", "distribution-contrast", "DISTRIBUTION", True, False),
    ("How erratic has the exchange rate been lately?", "distribution-contrast", "DISTRIBUTION", True, False),
    ("Who are the major shareholders of Vodafone?", "composition-recall", "COMPOSITION", True, False),
    ("Tell me the ownership breakdown of Lloyds Banking Group.", "composition-recall", "COMPOSITION", True, False),
    ("First the requisition is raised, then approved, then the purchase order is issued, then goods are received.", "process-paraphrase", "PROCESS", True, False),
    ("Server-A depends on Database-B; Database-B depends on Cache-C.", "out-of-scope-shape-trap", None, False, True),
    ("What's the trend?", "ambiguous", None, False, False),
]


def _load_results(set_name: str) -> dict[str, dict]:
    path = RESULTS_DIR / f"{set_name}_results.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _save_result(set_name: str, query: str, record: dict) -> None:
    RESULTS_DIR.mkdir(exist_ok=True)
    path = RESULTS_DIR / f"{set_name}_results.json"
    existing = _load_results(set_name)
    existing[query] = record
    path.write_text(json.dumps(existing, indent=2))


async def _run_set(
    set_key: str, name: str, cases: list[tuple[str, str, str | None, bool, bool]],
    *, max_cases: int | None, resume: bool,
) -> dict:
    existing = _load_results(set_key) if resume else {}
    rows = []
    intent_agree_llm = intent_agree_fallback = 0
    viz_agree_llm = viz_agree_fallback = 0
    scope_agree_llm = scope_agree_fallback = 0
    confusion: Counter[tuple[str, str]] = Counter()  # (expected, actual) -> count, LLM only, semantic misses only
    infra_failures = 0
    scored = 0  # cases actually scorable for LLM intent accuracy (excludes infra failures)
    per_intent_tp: Counter[str] = Counter()
    per_intent_expected: Counter[str] = Counter()
    per_intent_predicted: Counter[str] = Counter()
    attempted_this_run = 0

    for query, category, expected_intent, expected_viz, expected_oos in cases:
        if max_cases is not None and attempted_this_run >= max_cases:
            break

        cached = existing.get(query)
        if cached and cached.get("failure_category") not in _INFRA_FAILURE_CATEGORIES:
            attempt_dict = cached
        else:
            fb = _fallback_classify(query)
            result = await attempt_classify_query_llm(query)
            attempted_this_run += 1
            attempt_dict = {
                "intent": result.intent.intent if result.intent else None,
                "wants_visualization": result.intent.wants_visualization if result.intent else False,
                "out_of_scope": result.intent.out_of_scope if result.intent else False,
                "failure_category": result.failure_category,
                "fallback_intent": fb.intent,
                "fallback_wants_visualization": fb.wants_visualization,
            }
            _save_result(set_key, query, attempt_dict)

        fb_intent_ok = attempt_dict["fallback_intent"] == expected_intent
        fb_viz_ok = attempt_dict["fallback_wants_visualization"] == expected_viz
        intent_agree_fallback += fb_intent_ok
        viz_agree_fallback += fb_viz_ok
        scope_agree_fallback += (expected_oos == False)  # fallback never sets True — see query_classifier.py

        is_infra_failure = attempt_dict["failure_category"] in _INFRA_FAILURE_CATEGORIES
        if is_infra_failure:
            infra_failures += 1
            rows.append((category, query[:60], expected_intent, attempt_dict["fallback_intent"],
                         "OK" if fb_intent_ok else "MISS", "INFRA_FAIL", attempt_dict["failure_category"]))
            continue

        scored += 1
        llm_intent = attempt_dict["intent"]
        llm_intent_ok = llm_intent == expected_intent
        llm_viz_ok = attempt_dict["wants_visualization"] == expected_viz
        llm_oos_ok = attempt_dict["out_of_scope"] == expected_oos

        per_intent_expected[str(expected_intent)] += 1
        per_intent_predicted[str(llm_intent)] += 1
        if llm_intent_ok:
            per_intent_tp[str(expected_intent)] += 1
        else:
            confusion[(str(expected_intent), str(llm_intent))] += 1

        intent_agree_llm += llm_intent_ok
        viz_agree_llm += llm_viz_ok
        scope_agree_llm += llm_oos_ok

        rows.append((category, query[:60], expected_intent, attempt_dict["fallback_intent"],
                     "OK" if fb_intent_ok else "MISS", llm_intent, "OK" if llm_intent_ok else "MISS"))

    total = len(cases) if max_cases is None else min(len(cases), attempted_this_run + len(existing))
    print(f"\n=== {name} (n={len(cases)}, scored={scored}, infra_failures={infra_failures}) ===")
    print(f"{'category':<26} {'query':<62} {'expect':<12} {'old':<12} {'':6} {'llm':<12} {''}")
    for r in rows:
        print(f"{r[0]:<26} {r[1]:<62} {str(r[2]):<12} {str(r[3]):<12} {r[4]:<6} {str(r[5]):<12} {r[6]}")

    print()
    if scored:
        print(f"Intent accuracy (scorable only) — old regex: {intent_agree_fallback}/{scored} ({100*intent_agree_fallback/scored:.0f}%)   semantic LLM: {intent_agree_llm}/{scored} ({100*intent_agree_llm/scored:.0f}%)")
        print(f"Visualization accuracy          — old regex: {viz_agree_fallback}/{scored} ({100*viz_agree_fallback/scored:.0f}%)   semantic LLM: {viz_agree_llm}/{scored} ({100*viz_agree_llm/scored:.0f}%)")
        print(f"Out-of-scope accuracy           — old regex: {scope_agree_fallback}/{scored} ({100*scope_agree_fallback/scored:.0f}%)   semantic LLM: {scope_agree_llm}/{scored} ({100*scope_agree_llm/scored:.0f}%)")
    if infra_failures:
        print(f"Infra failures (excluded from accuracy above): {infra_failures}/{len(cases)} — see failure_category column")
    if confusion:
        print("\nLLM confusion pairs (expected -> actual), semantic misses only:")
        for (expected, actual), count in confusion.most_common():
            print(f"  {expected:<14} -> {actual:<14} {count}")
    if per_intent_expected:
        print("\nPer-intent recall (correct/expected) and precision (correct/predicted):")
        for label in sorted(per_intent_expected):
            exp = per_intent_expected[label]
            tp = per_intent_tp[label]
            pred = per_intent_predicted.get(label, 0)
            recall = f"{tp}/{exp} ({100*tp/exp:.0f}%)"
            precision = f"{tp}/{pred} ({100*tp/pred:.0f}%)" if pred else "n/a (never predicted)"
            print(f"  {label:<14} recall {recall:<14} precision {precision}")

    return {
        "n": len(cases), "scored": scored, "infra_failures": infra_failures,
        "intent_llm": intent_agree_llm, "intent_fallback": intent_agree_fallback,
        "viz_llm": viz_agree_llm, "viz_fallback": viz_agree_fallback,
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dev-only", action="store_true")
    parser.add_argument("--holdout-only", action="store_true")
    parser.add_argument("--max-cases", type=int, default=None, help="cap NEW LLM calls made this run (across both sets if neither --dev-only nor --holdout-only)")
    parser.add_argument("--resume", action="store_true", help="skip cases already recorded in results/*.json with a non-infra result")
    args = parser.parse_args()

    if not os.environ.get("GROQ_API_KEY"):
        print("GROQ_API_KEY not set — cannot run the LLM side of this evaluation.")
        return

    results = {}
    if not args.holdout_only:
        results["dev"] = await _run_set(
            "dev", "DEV SET (used while tuning the prompt)", CASES,
            max_cases=args.max_cases, resume=args.resume,
        )
    if not args.dev_only:
        remaining = None
        if args.max_cases is not None:
            used = results.get("dev", {}).get("scored", 0) + results.get("dev", {}).get("infra_failures", 0)
            remaining = max(0, args.max_cases - used)
        results["holdout"] = await _run_set(
            "holdout", "HOLDOUT SET (new phrasings, not used to tune the prompt)", HOLDOUT_CASES,
            max_cases=remaining, resume=args.resume,
        )

    print("\n=== SUMMARY ===")
    for name, r in results.items():
        if not r["scored"]:
            print(f"{name:<8} n={r['n']:<4} no scorable results (infra_failures={r['infra_failures']})")
            continue
        print(
            f"{name:<8} n={r['n']:<4} scored={r['scored']:<4} infra_failures={r['infra_failures']:<4} "
            f"intent: old {100*r['intent_fallback']/r['scored']:.0f}% / llm {100*r['intent_llm']/r['scored']:.0f}%   "
            f"viz: old {100*r['viz_fallback']/r['scored']:.0f}% / llm {100*r['viz_llm']/r['scored']:.0f}%"
        )


if __name__ == "__main__":
    asyncio.run(main())
