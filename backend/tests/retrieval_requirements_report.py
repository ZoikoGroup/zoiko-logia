"""Task Contract, Stage C-1 (shadow): the recorded retrieval requirements
against hand-written expectations, and how many questions would need official
retrieval. Not collected by the normal test run; run it explicitly:

    RETRIEVAL_REPORT=report.json python -m pytest -q tests/retrieval_requirements_report.py
    (RETRIEVAL_QUESTIONS=extra.json adds a JSON list of question strings to the counts)

Each disagreement gives the expected requirement, the contract's requirement
and the reason. Counts are over every question in evals/*.json (and the extra
list), by jurisdiction, fact type, publisher and connector. The contract is
built directly (it is deterministic); no pipeline, model or network.
"""
import glob
import json
import os
from collections import Counter
from pathlib import Path

from app.orchestration.task_contract import build_task_contract

EVALS = Path(__file__).resolve().parents[1] / "evals"


def _as_dict(requirement) -> dict:
    return {"part": requirement.part, "needs_official": requirement.needs_official, "fact_type": requirement.fact_type,
            "jurisdictions": requirement.jurisdictions, "publisher": requirement.publisher,
            "connector": requirement.connector, "reason": requirement.reason}


def _compare(expect: dict, actual: dict) -> list[str]:
    problems = []
    if actual["needs_official"] != expect["needs_official"]:
        problems.append("false negative: needs an official figure or rule, not recorded" if expect["needs_official"]
                        else "false positive: recorded as needing official retrieval, needs none")
    if actual["fact_type"] not in expect["fact_type"]:
        problems.append(f"fact type {actual['fact_type']}, expected {'/'.join(expect['fact_type'])}")
    if "jurisdictions" in expect and actual["jurisdictions"] != expect["jurisdictions"]:
        problems.append(f"jurisdictions {actual['jurisdictions']}, expected {expect['jurisdictions']}")
    if expect["needs_official"] and actual["needs_official"] and "publisher" in expect:
        wanted, got = expect["publisher"], actual["publisher"]
        if wanted is None and got is not None:
            problems.append(f"publisher '{got}', expected none mapped (a gap)")
        elif wanted is not None and (got is None or wanted not in got):
            problems.append(f"publisher {got!r}, expected one containing '{wanted}'")
    if expect["needs_official"] and actual["needs_official"] and "connector" in expect \
            and actual["connector"] != expect["connector"]:
        problems.append(f"connector {actual['connector']}, expected {expect['connector']}")
    return problems


def _questions() -> list[str]:
    seen: dict[str, None] = {}
    for path in sorted(glob.glob(str(EVALS / "*.json"))):
        if "retrieval_requirement_expectations" in path:
            continue
        try:
            stack = [json.load(open(path))]
        except Exception:  # noqa: BLE001
            continue
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
            elif isinstance(node, dict):
                stack.extend(node.values())
                for key in ("question", "query", "user"):
                    if isinstance(node.get(key), str) and node[key].strip():
                        seen.setdefault(node[key].strip())
    extra = os.environ.get("RETRIEVAL_QUESTIONS")
    if extra:
        for question in json.load(open(extra)):
            seen.setdefault(question.strip())
    return list(seen)


def test_retrieval_requirements_report():
    report = {"expectations": [], "disagreements": [], "counts": {}}
    for case in json.load(open(EVALS / "retrieval_requirement_expectations.json"))["cases"]:
        actual = [_as_dict(r) for r in build_task_contract(case["query"]).retrieval]
        entry = {"id": case["id"], "group": case["group"], "expected": case["expect"], "actual": actual, "problems": []}
        if len(actual) != len(case["expect"]):
            entry["problems"].append(f"{len(actual)} part(s) recorded, expected {len(case['expect'])}")
        for index, (expect, got) in enumerate(zip(case["expect"], actual), 1):
            for problem in _compare(expect, got):
                entry["problems"].append(problem)
                report["disagreements"].append({"id": case["id"], "group": case["group"], "part": index,
                                                "query": case["query"][:160], "expected": expect, "actual": got,
                                                "problem": problem, "why_expected": case["why"]})
        report["expectations"].append(entry)

    questions = _questions()
    triggered, by_jurisdiction, by_fact, by_publisher, by_connector, parts = 0, Counter(), Counter(), Counter(), Counter(), 0
    examples: dict[str, list[str]] = {}
    for question in questions:
        requirements = build_task_contract(question).retrieval
        official = [r for r in requirements if r.needs_official]
        parts += len(requirements)
        if not official:
            continue
        triggered += 1
        for r in official:
            for key in r.jurisdictions or ["(none detected)"]:
                by_jurisdiction[key] += 1
            by_fact[r.fact_type] += 1
            by_publisher[r.publisher or "(no publisher mapped)"] += 1
            by_connector[r.connector or "(no connector)"] += 1
            examples.setdefault(r.fact_type, [])
            if len(examples[r.fact_type]) < 8:
                examples[r.fact_type].append(question[:140])
    report["counts"] = {"questions": len(questions), "parts": parts, "questions_triggering_official": triggered,
                        "official_parts_by_jurisdiction": dict(by_jurisdiction.most_common()),
                        "official_parts_by_fact_type": dict(by_fact.most_common()),
                        "official_parts_by_publisher": dict(by_publisher.most_common()),
                        "official_parts_by_connector": dict(by_connector.most_common()),
                        "examples_by_fact_type": examples}
    out = os.environ.get("RETRIEVAL_REPORT")
    if out:
        Path(out).write_text(json.dumps(report, indent=1, ensure_ascii=False))
