"""Global Source Registry, Stage S4 (shadow): the registry's source selection
against today's, scored on the gold retrieval set. Not collected by the normal
test run; run it explicitly:

    REGISTRY_REPORT=report.json python -m pytest -q tests/registry_shadow_report.py

For every gold question the contract is built directly (deterministic; no
pipeline, model or network) and each official part is selected both ways.
Per question, over its official parts, a selection is scored on its domains
(fixed-page hosts, connector hosts and search domains):
- publisher hit: at least one of the gold publisher_domains is selected;
- leak: a gold must_not_domain (another country's authority) is selected.
Splits are reported separately; nothing here tunes rules on any split.
"""
import json
import os
from collections import Counter, defaultdict
from pathlib import Path

from app.orchestration import registry_shadow
from app.orchestration.task_contract import build_task_contract

EVALS = Path(__file__).resolve().parents[1] / "evals"


def _split(case: dict) -> str:
    for key, name in (("holdout4", "holdout4"), ("holdout3", "holdout3"), ("dev2", "dev2"), ("fresh_holdout", "fresh")):
        if case.get(key):
            return name
    return "holdout" if case.get("holdout") else "dev"


def registry_shadow_host(value: str) -> str:
    value = (value or "").lower().removeprefix("https://").removeprefix("http://").removeprefix("www.")
    return value.split("/")[0]


def _connector_hosts() -> dict[str, str]:
    return {e["id"]: registry_shadow_host(e.get("host") or e.get("url") or "") for e in registry_shadow.entries()}


def _matches(host: str, domains) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def _domains(selection, side: str, hosts: dict[str, str]) -> set[str]:
    if side == "today":
        found = {registry_shadow_host(u) for u in selection.today_pages} | set(selection.today_domains)
        if selection.today_connector:
            found.add(hosts.get(registry_shadow._CONNECTOR_IDS.get(selection.today_connector, ""), ""))
    else:
        found = ({registry_shadow_host(u) for u in selection.fixed_pages} | set(selection.search_domains)
                 | {hosts.get(c, "") for c in selection.connectors})
    return {d for d in found if d and "." in d}


def test_registry_shadow_report():
    hosts = _connector_hosts()
    cases = json.load(open(EVALS / "gold_retrieval_set.json"))["cases"]
    totals = defaultdict(Counter)
    tiers, by_country = Counter(), defaultdict(Counter)
    examples = defaultdict(list)
    for case in cases:
        gold = [p for p in case["parts"] if p.get("needs_official")]
        if not gold:
            continue
        split = _split(case)
        chosen = registry_shadow.selections(build_task_contract(case["question"]))
        publisher = {d for p in gold for d in p.get("publisher_domains", [])}
        must_not = {d for p in gold for d in p.get("must_not_domains", [])} - publisher
        country = "+".join(sorted({c for p in gold for c in p.get("countries", [])})) or "NONE"
        t = totals[split]
        t["questions"] += 1
        if not chosen:
            t["no_official_part_recorded"] += 1
            continue
        for s in chosen:
            tiers[s.tier] += 1
            by_country[country][s.tier] += 1
            t["parts"] += 1
            t["pages_agree"] += s.pages_agree
            t["connector_agrees"] += s.connector_agrees
            if s.period_unconfirmed:
                t["parts_period_unconfirmed"] += 1
        for side in ("today", "registry"):
            domains = set().union(*(_domains(s, side, hosts) for s in chosen))
            hit = any(_matches(d, publisher) for d in domains) if publisher else None
            leak = sorted(d for d in domains if _matches(d, must_not))
            if hit is not None:
                t[f"{side}_publisher_hit"] += hit
                t["questions_with_publisher"] += side == "today"
            t[f"{side}_leak"] += bool(leak)
            if side == "registry" and len(examples[split]) < 15 and (leak or hit is False):
                examples[split].append({"id": case["id"], "question": case["question"][:160], "leak": leak[:5],
                                        "publisher_hit": hit, "tiers": [s.tier for s in chosen]})
    report = {"totals": {k: dict(v) for k, v in totals.items()}, "tiers": dict(tiers),
              "tiers_by_country": {k: dict(v) for k, v in sorted(by_country.items())}, "registry_misses": examples}
    out = os.environ.get("REGISTRY_REPORT")
    if out:
        Path(out).write_text(json.dumps(report, indent=2))
    print(json.dumps(report["totals"], indent=2))
    assert totals, "gold set produced no questions"
