"""Answer quality across every question asked: what Kriton removed, and why.

    python scripts/answer_quality_report.py [--days 7] [--top 10]

Each answer is checked statement by statement, and what fails is removed and
recorded in the audit log. Nobody read those records across all answers, so a
pattern showed up only when a person happened to read a broken answer: in one
week, 13% of answers lost statements, and 316 of 328 were removed as
unverified, not shown wrong (24 Oct 2026). This report reads the audit log,
read-only, and shows:

  - how many answers lost statements, and how many ended partial or withheld;
  - removals by stage and reason;
  - how many Kriton could have verified itself: a rate its own knowledge base
    states, or hand-worked arithmetic the calculator would check;
  - the statements removed most often.

Read-only: the session is read-only by default and per transaction, and that
is checked before any query. Nothing is written. No model or network call
beyond the database.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]

_RATE = re.compile(r"(\d+(?:\.\d+)?)\s?%")
_ARITHMETIC = re.compile(r"\d[\d,.]*\s?%?\s*[×x*÷/+−-]\s*[£$€₹]?\d[^=\n]*=\s*[£$€₹]?\s?\d")
_WORD = re.compile(r"[a-z]{4,}")
_COMMON = {"that", "this", "with", "from", "which", "must", "rate", "have", "will", "their", "there", "these"}


def classify(excerpt: str, reason: str, knowledge: list[str]) -> str:
    """Why a removed statement could not stay, and whether Kriton itself
    could have verified it."""
    if reason == "contradicted_by_cited_source":
        return "shown wrong by a cited source"
    if _ARITHMETIC.search(excerpt):
        return "hand-worked arithmetic (the calculator could verify it)"
    rates = _RATE.findall(excerpt)
    if rates:
        words = [word for word in _WORD.findall(excerpt.lower()) if word not in _COMMON][:6]
        stated = any(any(f"{rate}%" in passage or f"{rate} %" in passage or f"{rate} per cent" in passage
                         for rate in rates) and any(word in passage for word in words) for passage in knowledge)
        return ("a rate Kriton's knowledge base states (a search would verify it)" if stated
                else "a rate the knowledge base does not state")
    if reason in ("missing_citation", "not_in_cited_evidence"):
        return "a statement with no source in hand (never searched for)"
    return "an unverified figure"


def summarise(answers: int, payloads: list[dict], knowledge: list[str], top: int = 10) -> dict:
    stages, reasons, kinds, completeness, excerpts = Counter(), Counter(), Counter(), Counter(), Counter()
    for payload in payloads:
        completeness[payload.get("completeness") or "unknown"] += 1
        for stage in payload.get("stages", []):
            stages[stage["stage"]] += stage.get("removed_count", len(stage.get("removed", [])))
            for item in stage.get("removed", []):
                reasons[item["reason_code"]] += 1
                kinds[classify(item.get("excerpt", ""), item["reason_code"], knowledge)] += 1
                excerpts[" ".join(item.get("excerpt", "").split())[:110]] += 1
    removed = sum(reasons.values())
    return {"answers": answers, "answers_with_removals": len(payloads), "statements_removed": removed,
            "completeness": dict(completeness.most_common()), "by_stage": dict(stages.most_common()),
            "by_reason": dict(reasons.most_common()), "by_kind": dict(kinds.most_common()),
            "most_removed": [(text, count) for text, count in excerpts.most_common(top) if count > 1]}


def render(report: dict, days: int) -> str:
    answers, hit, removed = report["answers"], report["answers_with_removals"], report["statements_removed"]
    lines = [f"Kriton answer quality, last {days} day(s)",
             f"  answers: {answers}; with statements removed: {hit} ({hit / max(answers, 1):.0%}); "
             f"statements removed: {removed}",
             f"  those answers ended: {report['completeness']}",
             "  removed by stage: " + ", ".join(f"{k} {v}" for k, v in report["by_stage"].items()),
             "  removed by reason: " + ", ".join(f"{k} {v}" for k, v in report["by_reason"].items()),
             "  what was removed:"]
    lines += [f"    {count:4}  ({count / max(removed, 1):.0%})  {kind}" for kind, count in report["by_kind"].items()]
    if report["most_removed"]:
        lines.append("  removed most often:")
        lines += [f"    {count:3}×  {text}" for text, count in report["most_removed"]]
    return "\n".join(lines)


def _read_only_connection(url: str):
    import psycopg2
    scheme, rest = url.split("://", 1)
    conn = psycopg2.connect("postgresql://" + rest if scheme.split("+")[0] in {"postgres", "postgresql"} else url,
                            connect_timeout=10, options="-c default_transaction_read_only=on")
    conn.set_session(readonly=True, autocommit=False)
    with conn.cursor() as cur:
        cur.execute("SHOW transaction_read_only")
        if cur.fetchone()[0] != "on":
            conn.close()
            raise SystemExit("The database session is not read-only; nothing was run.")
    return conn


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--env", type=Path, default=BACKEND / ".env")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args(argv)
    from dotenv import dotenv_values
    url = dotenv_values(args.env).get("DATABASE_URL")
    if not url or not url.startswith("postgres"):
        print("No PostgreSQL DATABASE_URL in", args.env)
        return 2
    conn = _read_only_connection(url)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM audit_events WHERE event_name = 'response_returned' "
                        "AND event_time > now() - make_interval(days => %s)", (args.days,))
            answers = cur.fetchone()[0]
            cur.execute("SELECT payload FROM audit_events WHERE event_name = 'answer_statements_removed' "
                        "AND event_time > now() - make_interval(days => %s)", (args.days,))
            payloads = [row[0] if isinstance(row[0], dict) else json.loads(row[0]) for row in cur.fetchall()]
            cur.execute("SELECT lower(p.content) FROM source_passages p JOIN source_versions v "
                        "ON v.id = p.source_version_id WHERE v.status IN ('ACTIVE', 'APPROVED') "
                        "AND v.superseded_by_version_id IS NULL AND v.revoked_at IS NULL")
            knowledge = [row[0] for row in cur.fetchall()]
        conn.rollback()
    finally:
        conn.close()
    report = summarise(answers, payloads, knowledge, args.top)
    print(json.dumps(report, indent=1) if args.json else render(report, args.days))
    return 0


if __name__ == "__main__":
    sys.exit(main())
