"""Phase 0 baseline: run evaluation questions through the full Ask Kriton HTTP
pipeline (auth, tenant isolation, retrieval, composition, validation, audit)
and record accuracy by failure category.

    cd backend
    .venv/bin/python scripts/run_baseline_eval.py                 # all cases
    .venv/bin/python scripts/run_baseline_eval.py --ids calc-emi-40l tax-vat-sign-off
    .venv/bin/python scripts/run_baseline_eval.py --only baseline # skip the agent cases
    .venv/bin/python scripts/run_baseline_eval.py --only uk_vat   # knowledge-base set (not in the default run)
    .venv/bin/python scripts/run_baseline_eval.py --only uk_vat_holdout  # held out: never tuned against
    .venv/bin/python scripts/run_baseline_eval.py --only gold     # reviewer-approved/corrected answers
    .venv/bin/python scripts/run_baseline_eval.py --only regression  # every question reported in live testing

Needs the backend running (BASELINE_API_URL, default http://127.0.0.1:8010)
and signs in as the seeded demo user (scripts/seed_dev_user.py), so eval
traffic and its audit records stay in the demo tenant, not a real one.
Costs model tokens and search credits. Reports go to evals/reports/.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import httpx

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
EVALS = BACKEND / "evals"
REPORTS = EVALS / "reports"
API = os.getenv("BASELINE_API_URL", "http://127.0.0.1:8010").rstrip("/") + "/api/v1"
DEMO_EMAIL = os.getenv("EVAL_EMAIL", "dashboard@zoikologia.com")
DEMO_PASSWORD = os.getenv("EVAL_PASSWORD", "")
OFF_DOMAIN_MARKER = "designed to answer questions related to accounting"
PAUSE_SECONDS = 3.0  # Groq's per-minute token ceiling, not politeness
# A network outage (DNS failure, database unreachable) answers every request
# with 5xx in under a second; without a pause, one outage failed dozens of
# cases in a row. Each such case is retried after these waits.
OUTAGE_BACKOFF_SECONDS = (30, 60, 120)

# The agent cases' own categories, mapped onto the failure classes the
# baseline reports.
_AGENT_CATEGORY = {
    "fx": "retrieval", "economic": "retrieval", "market": "retrieval", "calculation": "calculation",
    "conceptual": "accuracy", "chart": "accuracy", "off_domain": "safety", "injection": "safety",
}
_DATA_TOOLS = {"get_exchange_rate", "get_economic_indicator", "get_market_data"}


def _frontend_env() -> dict[str, str]:
    path = BACKEND.parent / "frontend" / ".env.local"
    text = path.read_text() if path.exists() else ""
    values = {k: v.strip() for k, v in re.findall(r"^(NEXT_PUBLIC_SUPABASE_\w+)=(.+)$", text, re.M)}
    return {**values, **{k: os.environ[k] for k in ("NEXT_PUBLIC_SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_ANON_KEY") if os.getenv(k)}}


def sign_in() -> str:
    env = _frontend_env()
    if not DEMO_PASSWORD:
        raise RuntimeError("EVAL_PASSWORD must be set for the evaluation account")
    for attempt in range(3):  # transient TLS/connection resets happen
        try:
            response = httpx.post(
                f"{env['NEXT_PUBLIC_SUPABASE_URL']}/auth/v1/token?grant_type=password",
                headers={"apikey": env["NEXT_PUBLIC_SUPABASE_ANON_KEY"]},
                json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}, timeout=20,
            )
            response.raise_for_status()
            return response.json()["access_token"]
        except httpx.HTTPError:
            if attempt == 2:
                raise
            time.sleep(3)
    raise RuntimeError("unreachable")


def load_cases(only: str | None) -> list[dict]:
    cases: list[dict] = []
    if only in (None, "baseline"):
        for case in json.loads((EVALS / "baseline_questions.json").read_text())["cases"]:
            cases.append({**case, "source": "baseline"})
    # Knowledge-base sets, run on request only (not in the default run).
    for dataset, filename in (("uk_vat", "uk_vat_questions.json"), ("uk_vat_holdout", "uk_vat_holdout.json"),
                              ("india_gst", "india_gst_questions.json"),
                              ("regression", "session_regression.json")):
        if only == dataset:
            for case in json.loads((EVALS / filename).read_text())["cases"]:
                cases.append({**case, "source": dataset})
    if only == "gold":
        cases += _gold_cases()
    if only in (None, "agent"):
        for case in json.loads((EVALS / "agent_questions.json").read_text())["cases"]:
            converted = {
                "id": case["id"], "source": "agent", "question": case["question"],
                "category": _AGENT_CATEGORY.get(case.get("category"), "accuracy"),
                "must_contain": case.get("must_contain", []),
                "must_not_contain": case.get("must_not_contain", []),
            }
            if case.get("refusal"):
                converted["off_domain_refusal"] = True
            elif _DATA_TOOLS & set(case.get("expect_tools", [])):
                converted["expect_citations"] = True
            cases.append(converted)
    return cases


def _gold_cases() -> list[dict]:
    """Reviewed answers (app/orchestration/review.py): each approved or
    corrected review case is a question with the facts its answer must state."""
    sys.path.insert(0, str(BACKEND))
    from dotenv import load_dotenv

    load_dotenv(BACKEND / ".env")
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.domains.evaluation.models import BenchmarkCase
    from app.orchestration.review import GOLD_DATASET_ID

    tenant_id = os.getenv("EVAL_TENANT_ID", "").strip()
    if not tenant_id:
        raise RuntimeError("EVAL_TENANT_ID is required; tenant-private gold cases cannot be evaluated under another account")
    with SessionLocal() as db:
        legacy = db.execute(select(BenchmarkCase.id).where(BenchmarkCase.dataset_id == GOLD_DATASET_ID)).first()
        if legacy:
            raise RuntimeError("Legacy unscoped gold cases require tenant assignment and reviewer validation before release")
        rows = db.execute(select(BenchmarkCase).where(
            BenchmarkCase.dataset_id == f"{GOLD_DATASET_ID}:{tenant_id}", BenchmarkCase.tenant_id == tenant_id,
        )).scalars().all()
    invalid = [row.id for row in rows if not row.key_facts]
    if invalid:
        raise RuntimeError("Gold cases missing required key facts: " + ", ".join(invalid))
    return [
        {
            "id": row.id, "source": "gold", "category": row.category, "question": row.query_text,
            "outcome": "answered", "must_contain": list(row.key_facts or []),
        }
        for row in rows
    ]


def ask(client: httpx.Client, query: str, history: list[dict]) -> dict:
    try:
        response = client.post("/orchestration/ask", json={
            "query": query, "conversation_history": history[-12:],
        })
    except httpx.HTTPError as exc:  # one dropped connection fails one case, not the run
        return {"_http_error": f"{type(exc).__name__}: {exc}"}
    if response.status_code != 200:
        return {"_http_error": f"HTTP {response.status_code}: {response.text[:200]}"}
    return response.json()


def _is_outage(result: dict) -> bool:
    """Infrastructure failure rather than an answer: a connection error or a
    5xx from the service (a timeout's 504 included)."""
    error = result.get("_http_error", "")
    return bool(error) and (not error.startswith("HTTP ") or error.startswith("HTTP 5"))


def _reply_text(result: dict) -> str:
    answer = result.get("answer") or {}
    action = result.get("next_action") or {}
    return f"{answer.get('text') or ''}\n{action.get('message') or ''}"


def _normalised(text: str) -> str:
    """Compare what a reader sees: "21{,}589.25" in LaTeX is 21,589.25, and the
    model's narrow no-break spaces and non-breaking hyphens ("IFRS\u202f15",
    "right\u2011of\u2011use") are ordinary ones. Without this, four correct
    answers failed the first baseline."""
    text = text.replace("{,}", ",").replace("\\%", "%")
    text = re.sub(r"[\u00a0\u2007\u2009\u202f]", " ", text)
    text = re.sub(r"(\d) +%", r"\1%", text)  # "5 %" is 5%
    # Markdown emphasis is not content: "did **not** modify" is "did not modify".
    text = re.sub(r"\*\*|__", "", text)
    text = re.sub(r"[\u2010\u2011\u2012\u2013]", "-", text)
    # "time-of-supply" answers "time of supply".
    return re.sub(r"(?<=[A-Za-z])-(?=[A-Za-z])", " ", text)


def score(case: dict, result: dict) -> list[str]:
    """Each failure is prefixed with its check type, used for the breakdown."""
    if "_http_error" in result:
        return [f"error: {result['_http_error']}"]
    failures: list[str] = []
    text = _normalised(_reply_text(result))
    lowered = text.lower()
    answer = result.get("answer") or {}
    outcome = result.get("outcome")

    if case.get("off_domain_refusal"):
        if OFF_DOMAIN_MARKER not in lowered:
            failures.append("outcome: expected the off-domain refusal")
    elif case.get("outcome") and outcome != case["outcome"]:
        failures.append(f"outcome: expected {case['outcome']}, got {outcome}")
    for needle in case.get("must_contain", []):
        if _normalised(needle).lower() not in lowered:
            failures.append(f"content: missing {needle!r}")
    any_of = case.get("must_contain_any", [])
    if any_of and not any(_normalised(needle).lower() in lowered for needle in any_of):
        failures.append(f"content: missing any of {any_of}")
    for alternatives in case.get('must_contain_groups', []):
        if not any(_normalised(needle).lower() in lowered for needle in alternatives):
            failures.append(f'content: missing required topic (any of {alternatives})')
    raw_lowered = _reply_text(result).lower()
    for needle in case.get("must_not_contain", []):
        # Raw text first: formatting needles ("\n****", "【") are what the
        # check is about, and normalising strips them to nothing.
        normalised_needle = _normalised(needle).lower()
        if needle.lower() in raw_lowered or (normalised_needle.strip() and normalised_needle in lowered):
            failures.append(f"forbidden: contains {needle!r}")
    citations = answer.get("citations") or []
    if case.get("expect_citations") is True and outcome == "answered" and not citations:
        failures.append("citations: expected sources, got none")
    if case.get("expect_citations") is False and citations:
        failures.append(f"citations: expected none, got {len(citations)}")
    # A chart or diagram must actually be attached: a ```chart block in the
    # answer, or a server-built visualization.
    if case.get("expect_visual") and not (
        "```chart" in (answer.get("text") or "") or result.get("visualization") or answer.get("visualization")
    ):
        failures.append("visual: expected a chart or diagram, got none")
    if case.get("limitation_contains") and not any(
        case["limitation_contains"] in limitation for limitation in answer.get("limitations") or []
    ):
        failures.append(f"content: missing limitation {case['limitation_contains']!r}")
    verified = (answer.get("calculation_result") or {}).get("output_value")
    if case.get("verified_value_not") and verified == case["verified_value_not"]:
        failures.append(f"calculation: wrong verified value {verified}")
    return failures


def run(cases: list[dict]) -> list[dict]:
    token = sign_in()
    results = []
    with httpx.Client(base_url=API, headers={"Authorization": f"Bearer {token}"}, timeout=240) as client:
        # The endpoint takes a JSON body (every field optional); no body is a 422.
        provision = client.post("/auth/provision", json={})
        provision.raise_for_status()
        expected_tenant = os.getenv("EVAL_TENANT_ID")
        if expected_tenant:
            identity = client.get("/auth/me")
            identity.raise_for_status()
            if identity.json().get("tenant_id") != expected_tenant:
                raise RuntimeError("Evaluation account does not belong to EVAL_TENANT_ID")
        for index, case in enumerate(cases, start=1):
            history: list[dict] = []
            for turn in case.get("turns", []):
                earlier = ask(client, turn, history)
                history += [{"role": "user", "content": turn},
                            {"role": "assistant", "content": (_reply_text(earlier).strip() or "(no answer)")[:4000]}]
                time.sleep(PAUSE_SECONDS)
            started = time.monotonic()
            result = ask(client, case["question"], history)
            for wait in OUTAGE_BACKOFF_SECONDS:
                if not _is_outage(result):
                    break
                print(f"      service unavailable ({result['_http_error'][:60]}); retrying in {wait}s", flush=True)
                time.sleep(wait)
                started = time.monotonic()
                result = ask(client, case["question"], history)
            seconds = round(time.monotonic() - started, 1)
            failures = score(case, result)
            from app.domains.evaluation.pipeline_metrics import measure
            metrics = measure(case, result, failures)
            failures += [f"{name}: curated expectation failed" for name, passed in metrics.items() if not passed]
            results.append({
                "id": case["id"], "source": case["source"], "category": case["category"],
                "question": case["question"], "passed": not failures, "failures": failures,
                "metrics": metrics,
                "outcome": result.get("outcome"), "route": result.get("route"), "seconds": seconds,
                "citations": len((result.get("answer") or {}).get("citations") or []),
                # Answers citing the governed knowledge base, as opposed to
                # web search or the model's memory.
                "governed_citations": sum(
                    citation.get("provider") == "Governed source register"
                    for citation in (result.get("answer") or {}).get("citations") or []
                ),
                "answer_preview": _reply_text(result).strip()[:600],
                # The whole answer: a forbidden phrase past the preview could
                # not be checked by hand in the first runs.
                "answer_text": _reply_text(result).strip(),
                "note": case.get("note"),
            })
            mark = "PASS" if not failures else "FAIL"
            print(f"[{index:3d}/{len(cases)}] {mark} {seconds:5.1f}s {case['id']}"
                  + ("" if not failures else f"  — {'; '.join(failures)}"), flush=True)
            time.sleep(PAUSE_SECONDS)
    return results


def write_reports(results: list[dict], label: str = "baseline") -> Path:
    REPORTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (REPORTS / f"{label}-{stamp}.json").write_text(json.dumps(results, indent=2, ensure_ascii=False))

    by_category: dict[str, list[dict]] = defaultdict(list)
    for result in results:
        by_category[result["category"]].append(result)
    failure_types = Counter(f.split(":", 1)[0] for r in results for f in r["failures"])
    passed = sum(r["passed"] for r in results)
    lines = [
        f"# Kriton evaluation ({label}) — {stamp}", "",
        f"**Overall: {passed}/{len(results)} passed ({100 * passed / max(len(results), 1):.0f}%)**", "",
        "| Category | Passed | Total | Rate |", "|---|---|---|---|",
    ]
    for category in sorted(by_category):
        rows = by_category[category]
        ok = sum(r["passed"] for r in rows)
        lines.append(f"| {category} | {ok} | {len(rows)} | {100 * ok / len(rows):.0f}% |")
    lines += ["", "| Failure type | Count |", "|---|---|"]
    lines += [f"| {kind} | {count} |" for kind, count in failure_types.most_common()]
    governed = sum(1 for r in results if r.get("governed_citations"))
    lines += ["", f"Answers citing the governed knowledge base: {governed}/{len(results)}."]
    seconds = sorted(r["seconds"] for r in results)
    if seconds:
        lines += ["", f"Response time: median {seconds[len(seconds) // 2]}s, slowest {seconds[-1]}s.", ""]
    lines += ["## Failures", ""]
    for result in results:
        if result["passed"]:
            continue
        lines.append(f"- **{result['id']}** ({result['category']}): {'; '.join(result['failures'])}")
        lines.append(f"  - Q: {result['question']}")
        if result.get("note"):
            lines.append(f"  - Note: {result['note']}")
    report = REPORTS / f"{label}-{stamp}.md"
    report.write_text("\n".join(lines) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--ids", nargs="*", help="run only these case ids")
    parser.add_argument("--label", default="baseline", help="report file prefix, e.g. uk-vat-before")
    parser.add_argument("--only", choices=["baseline", "agent", "uk_vat", "uk_vat_holdout", "india_gst", "regression", "gold"], help="run one dataset")
    args = parser.parse_args()
    cases = load_cases(args.only)
    if args.ids:
        cases = [case for case in cases if case["id"] in set(args.ids)]
    if not cases:
        sys.exit("No cases selected.")
    report = write_reports(run(cases), label=args.label)
    print(f"\nReport: {report}")


if __name__ == "__main__":
    main()
