"""Stage S2 (shadow): the Task Contract against the S1 gold set, and against
the decisions other modules make for themselves. Not collected by the normal
test run; run it explicitly:

    CONTRACT_AGREEMENT_REPORT=report.json RETRIEVAL_QUESTIONS=questions.json \
        python -m pytest -q tests/contract_agreement_report.py

1. Accuracy (evals/gold_retrieval_set.json), part by part, reported apart
   for the held-back questions: part count, needs-official, fact type,
   countries (official parts), period; and whether a direct source (fixed
   page or connector) exists, and whether any planned search domain is
   another country's authority (must_not_domains).
2. Agreement: for every question (the gold set and RETRIEVAL_QUESTIONS), the
   contract beside the existing helpers each module calls on its own:
   detect_jurisdictions, detect_topics, structured_research_parts and
   evidence_search_queries (web search's parts), uk_vat_rules_requested,
   service._official_rate_question, needs_lookup and the strictness switch.
The contract is built directly (deterministic); no pipeline, model or network.
"""
import json
import os
from collections import Counter, defaultdict
from pathlib import Path

from app.orchestration.task_contract import build_task_contract

EVALS = Path(__file__).resolve().parents[1] / "evals"


def _part_problems(expect: dict, got) -> list[str]:
    problems = []
    if got.needs_official != expect["needs_official"]:
        problems.append("needs_official")
    if got.fact_type not in expect["fact_type"]:
        problems.append("fact_type")
    if expect["needs_official"] and expect["countries"] and set(got.jurisdictions) != set(expect["countries"]):
        problems.append("countries")
    if got.period.kind not in expect["period"]:
        problems.append("period")
    if set(got.official_domains) & set(expect.get("must_not_domains", [])):
        problems.append("wrong_country_domain")
    return problems


def _accuracy(cases) -> dict:
    fields = ("parts", "needs_official", "fact_type", "countries", "period", "wrong_country_domain")
    splits = ("dev", "holdout", "fresh", "dev2", "holdout3")
    tally = {split: Counter() for split in splits}
    totals = {split: Counter() for split in splits}
    by_country = defaultdict(Counter)
    coverage = defaultdict(Counter)
    disagreements = []
    for case in cases:
        split = ("holdout3" if case.get("holdout3") else "dev2" if case.get("dev2") else "fresh" if case.get("fresh_holdout")
                 else "holdout" if case["holdout"] else "dev")
        contract = build_task_contract(case["question"])
        got = contract.retrieval
        totals[split]["parts"] += 1
        if len(got) != len(case["parts"]):
            tally[split]["parts"] += 1
            disagreements.append({"id": case["id"], "split": split, "problem": "parts",
                                  "expected": len(case["parts"]), "actual": len(got)})
        for expect, actual in zip(case["parts"], got):
            for field in fields[1:]:
                if field == "countries" and not (expect["needs_official"] and expect["countries"]):
                    continue
                if field == "wrong_country_domain" and not expect.get("must_not_domains"):
                    continue
                totals[split][field] += 1
            problems = _part_problems(expect, actual)
            for problem in problems:
                tally[split][problem] += 1
            for country in expect["countries"] or ["(none)"]:
                by_country[country]["parts"] += 1
                by_country[country]["wrong"] += bool(problems)
                if expect["needs_official"]:
                    direct = bool(actual.official_pages or actual.connector)
                    coverage[country]["official_parts"] += 1
                    coverage[country]["direct_source"] += direct
            if problems:
                disagreements.append({"id": case["id"], "split": split, "question": case["question"][:140],
                                      "problems": problems,
                                      "expected": {k: expect[k] for k in ("needs_official", "fact_type", "countries", "period")},
                                      "actual": {"needs_official": actual.needs_official, "fact_type": actual.fact_type,
                                                 "countries": actual.jurisdictions, "period": actual.period.kind,
                                                 "reason": actual.reason}})
    rate = {split: {field: (f"{totals[split][field] - tally[split][field]}/{totals[split][field]}"
                            if totals[split][field] else "-") for field in fields} for split in totals}
    return {"accuracy": rate, "by_country": {k: dict(v) for k, v in sorted(by_country.items())},
            "direct_source_coverage": {k: dict(v) for k, v in sorted(coverage.items())},
            "disagreements": disagreements}


def _agreement(questions) -> dict:
    from app.orchestration.case_text import request_part
    from app.orchestration.calculation_service import needs_lookup
    from app.orchestration.input_requirements import uk_vat_rules_requested
    from app.orchestration.research_parts import structured_research_parts
    from app.orchestration.service import _official_rate_question
    from app.orchestration.source_taxonomy import detect_jurisdictions, detect_topics
    from app.orchestration.verification_service import requires_authoritative_evidence
    from app.orchestration.websearch import evidence_search_queries
    counts = Counter()
    examples = defaultdict(list)

    def note(key, agree, question, detail=""):
        counts[f"{key}:{'agree' if agree else 'differ'}"] += 1
        if not agree and len(examples[key]) < 12:
            examples[key].append(f"{question[:110]} | {detail}")

    for question in questions:
        contract = build_task_contract(question)
        parts = contract.retrieval
        countries = set().union(*(set(r.jurisdictions) for r in parts)) if parts else set()
        note("countries_vs_detect_jurisdictions(question)", countries == set(detect_jurisdictions(question)), question,
             f"contract {sorted(countries)} vs {detect_jurisdictions(question)}")
        asked = request_part(question)
        note("countries_vs_detect_jurisdictions(request_part)", countries == set(detect_jurisdictions(asked)), question,
             f"contract {sorted(countries)} vs {detect_jurisdictions(asked)}")
        topics = set().union(*(set(r.topics) for r in parts)) if parts else set()
        note("topics_vs_detect_topics(question)", topics == detect_topics(question), question,
             f"contract {sorted(topics)} vs {sorted(detect_topics(question))}")
        search_parts = len(evidence_search_queries(asked)) if asked.strip() else 0
        note("parts_vs_web_search_parts", max(len(parts), 1) == max(search_parts, 1), question,
             f"contract {len(parts)} vs search {search_parts}")
        structured = structured_research_parts(question)
        if structured:
            note("parts_vs_structured_research_parts", len(parts) == len(structured), question,
                 f"contract {len(parts)} vs structured {len(structured)}")
        official = any(r.needs_official for r in parts)
        if uk_vat_rules_requested(question):
            note("uk_vat_rules_requested_implies_contract_official", official, question)
        if _official_rate_question(question):
            note("official_rate_question_implies_contract_official_rate",
                 any(r.needs_official and r.fact_type == "rate" for r in parts), question)
        note("needs_lookup_vs_contract_official", needs_lookup(question) == official, question,
             f"needs_lookup {needs_lookup(question)} vs official {official}")
        if contract.authority_required is not None:
            note("authority_required_vs_bare_question",
                 contract.authority_required == requires_authoritative_evidence(question), question,
                 f"contract {contract.authority_required} vs bare {requires_authoritative_evidence(question)}")
    return {"counts": dict(sorted(counts.items())), "examples": dict(examples)}


def test_contract_agreement_report():
    gold = json.load(open(EVALS / "gold_retrieval_set.json"))["cases"]
    questions = [case["question"] for case in gold]
    extra = os.environ.get("RETRIEVAL_QUESTIONS")
    if extra:
        questions += json.load(open(extra))
    report = {"gold": _accuracy(gold), "agreement": _agreement(list(dict.fromkeys(q.strip() for q in questions if q.strip())))}
    out = os.environ.get("CONTRACT_AGREEMENT_REPORT")
    if out:
        Path(out).write_text(json.dumps(report, indent=1, ensure_ascii=False))
