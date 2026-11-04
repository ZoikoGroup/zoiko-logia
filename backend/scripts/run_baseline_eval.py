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
    .venv/bin/python scripts/run_baseline_eval.py --only accounting  # reviewed accounting cases: figures and treatment

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
                              ("regression", "session_regression.json"),
                              ("accounting", "accounting_review.json")):
        if only == dataset:
            for case in json.loads((EVALS / filename).read_text())["cases"]:
                cases.append({**case, "source": dataset})
    if only == "gold":
        cases += _gold_cases()
    if only in ("existing", "everything"):
        # The 206 cases that predate the intelligence set, reported as one group.
        for dataset in ("baseline", "agent", "uk_vat", "uk_vat_holdout", "india_gst", "regression"):
            cases += [{**case, "group": "existing"} for case in load_cases(dataset)]
    if only in ("intelligence", "everything", "shadow_eval"):
        for case in json.loads((EVALS / "intelligence_questions.json").read_text())["cases"]:
            cases.append({**case, "source": "intelligence", "group": "intelligence"})
    # Intent planner shadow evaluation (build order step A): the labelled
    # intelligence set plus planner-specific cases, reported as their own group.
    if only in ("shadow_eval_v2", "shadow_eval_v3"):
        # Versioned copies with corrected expectations (see their "changes").
        name = "intelligence_questions_v2.json" if only == "shadow_eval_v2" else "intelligence_questions_v3.json"
        for case in json.loads((EVALS / name).read_text())["cases"]:
            cases.append({**case, "source": "intelligence", "group": "intelligence"})
    if only in ("planner_shadow", "shadow_eval", "shadow_eval_v2", "shadow_eval_v3"):
        for case in json.loads((EVALS / "planner_shadow_questions.json").read_text())["cases"]:
            cases.append({**case, "source": "planner_shadow", "group": "planner_shadow"})
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


RUN_TAG = os.getenv("EVAL_RUN_TAG", "")


def ask(client: httpx.Client, query: str, history: list[dict], *, case_id: str = "",
        document_ids: list[str] | None = None) -> dict:
    body = {"query": query, "conversation_history": history[-12:],
            # Every evaluation request is identifiable in the audit trail.
            "conversation_id": f"eval-{RUN_TAG or 'run'}-{case_id}"[:120]}
    if document_ids:
        body.update(document_ids=document_ids, source_scope="DOCUMENTS_ONLY")
    try:
        response = client.post("/orchestration/ask", json=body)
    except httpx.HTTPError as exc:  # one dropped connection fails one case, not the run
        return {"_http_error": f"{type(exc).__name__}: {exc}"}
    if response.status_code == 401:
        return {"_http_error": "HTTP 401: token expired", "_unauthorized": True}
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


SCORING_VERSION = "v1"


def _normalised(text: str) -> str:
    """Compare what a reader sees: "21{,}589.25" in LaTeX is 21,589.25, and the
    model's narrow no-break spaces and non-breaking hyphens ("IFRS\u202f15",
    "right\u2011of\u2011use") are ordinary ones. Without this, four correct
    answers failed the first baseline."""
    text = text.replace("{,}", ",").replace("\\%", "%")
    if SCORING_VERSION == "v2":
        # "192 000" (thousands grouped with spaces) is 192,000; v1 missed a
        # correct answer written that way (int-doc-inconsistent).
        text = re.sub(r"(?<=\d)[ \u00a0\u2009\u202f](?=\d{3}(?!\d))", ",", text)
    text = re.sub(r"[\u00a0\u2007\u2009\u202f]", " ", text)
    text = re.sub(r"(\d) +%", r"\1%", text)  # "5 %" is 5%
    # Markdown emphasis is not content: "did **not** modify" is "did not modify".
    text = re.sub(r"\*\*|__", "", text)
    text = re.sub(r"[\u2010\u2011\u2012\u2013]", "-", text)
    # "time-of-supply" answers "time of supply".
    return re.sub(r"(?<=[A-Za-z])-(?=[A-Za-z])", " ", text)


_CHART_ALIASES = {"donut": "pie", "doughnut": "pie", "area": "line", "column": "bar", "grouped_bar": "bar",
                  "stacked_bar": "bar", "kpi": "kpi", "gauge": "kpi"}


def chart_types(result: dict) -> set[str]:
    """Chart types the answer carries: a server visualization, verified
    charts, or a ```chart block — lower-cased, with synonyms folded."""
    answer = result.get("answer") or {}
    found: list[str] = []
    for spec in [result.get("visualization"), answer.get("visualization"), *(answer.get("verified_charts") or [])]:
        if isinstance(spec, dict) and spec.get("type"):
            found.append(str(spec["type"]))
    for block in re.findall(r"```chart\s*\n(.*?)```", answer.get("text") or "", re.S):
        try:
            found.append(str(json.loads(block).get("type", "chart")))
        except (ValueError, AttributeError):
            found.append("chart")
    return {_CHART_ALIASES.get(kind.lower(), kind.lower()) for kind in found if kind.lower() != "table"}


def rule_intent(case: dict, result: dict) -> str:
    """What the CURRENT rules decided this request was, read from the route,
    plan and tools — the comparison point for the shadow planner (A)."""
    answer_text = ((result.get("answer") or {}).get("text") or "")
    route, outcome = result.get("route"), result.get("outcome")
    tools = set(result.get("_tools_used") or [])
    if OFF_DOMAIN_MARKER in _reply_text(result).lower() or route in ("SECURITY_INCIDENT", "REJECTED"):
        return "off_domain"
    if outcome == "clarification_required" or route == "CLARIFICATION":
        return "clarification"
    if answer_text.startswith("I checked "):
        return "review"
    if case.get("attach"):
        return "document_analysis"
    if tools & _DATA_TOOLS:
        return "live_data"
    if "render_chart" in tools or chart_types(result):
        return "visualization"
    formulas = ((result.get("calculation") or {}).get("formula_ids") or [])
    if "gross_profit_reconciliation" in formulas:
        return "reconciliation"
    if any(f.startswith("vat") for f in formulas):
        return "tax_calculation"
    if route == "CALCULATION" or "calculate" in tools:
        return "calculation"
    if "professional rule or authority named" in (result.get("_plan_reasons") or []):
        return "research_standard"
    return "explanation"


def audit_facts(query_id: str) -> dict:
    """Tools used, the plan, per-stage timings and tokens for one request,
    read (only) from the audit trail."""
    if not query_id:
        return {}
    from dotenv import load_dotenv
    load_dotenv(BACKEND / ".env")
    from sqlalchemy import text
    from app.core.database import engine
    with engine.connect() as db:
        rows = db.execute(text(
            "SELECT event_name, payload::text FROM audit_events WHERE subject_id = :q AND event_name IN "
            "('agent_tool_called', 'agent_plan_proposed', 'response_returned', 'agent_completed')"), {"q": query_id}).all()
    facts: dict = {"_tools_used": [], "_plan_reasons": [], "_stage_seconds": {}, "_tokens": 0, "_planned_tools": []}
    for name, payload_text in rows:
        payload = json.loads(payload_text)
        if name == "agent_tool_called":
            facts["_tools_used"].append(payload.get("tool"))
        elif name == "agent_plan_proposed":
            facts["_plan_reasons"] = payload.get("reasons") or []
            facts["_planned_tools"] = payload.get("planned_tools") or []
        elif name == "response_returned":
            facts["_stage_seconds"] = {stage: round(value.get("duration_ms", 0) / 1000, 2)
                                       for stage, value in (payload.get("stage_metrics") or {}).items()
                                       if isinstance(value, dict)}
        elif name == "agent_completed":
            facts["_tokens"] += int(payload.get("tokens_used") or 0)
    return facts


def upload_fixture(client: httpx.Client, name: str, cache: dict) -> str:
    if name not in cache:
        path = EVALS / "fixtures" / name
        response = client.post("/kriton-workspace/attachments", files={"file": (name, path.read_bytes(), "text/csv")})
        response.raise_for_status()
        cache[name] = response.json()["document_id"]
    return cache[name]


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
    if case.get("no_accounting_findings"):
        # The treatment, not only the figures: a VAT example passed every
        # content check with its accounting wrong (24 Oct 2026).
        from app.orchestration.accounting_validation import accounting_findings
        found = sorted({finding.rule for finding in accounting_findings(_reply_text(result))})
        if found:
            failures.append(f"treatment: {', '.join(found)}")
    if case.get("no_evidence_findings", case.get("source") == "accounting"):
        # What the released answer's own evidence check found unsupported
        # (verification_service.evidence_findings): a citation is not proof.
        from app.orchestration.verification_service import EVIDENCE_NOTE_PREFIX
        flagged = [item for item in answer.get("limitations") or [] if item.startswith(EVIDENCE_NOTE_PREFIX)]
        if flagged:
            failures.append("evidence: " + flagged[0][:200])
    for phrase in case.get("expect_missing_inputs", []):
        if phrase.lower() not in lowered:
            failures.append(f"missing_inputs: expected Kriton to ask about {phrase!r}")
    used = set(result.get("_tools_used") or [])
    for tool in case.get("expect_tools", []) if case.get("source") == "intelligence" else []:
        if tool not in used:
            failures.append(f"tools: expected {tool} to be used, used {sorted(used) or 'none'}")
    for tool in case.get("forbid_tools", []):
        if tool in used:
            failures.append(f"tools: {tool} should not be needed")
    visual = case.get("expect_visual")
    if isinstance(visual, str):
        charts = chart_types(result)
        if visual in ("none", "table_or_none") and charts:
            failures.append(f"visual: expected no chart, got {sorted(charts)}")
        if visual == "table" and "|" not in (answer.get("text") or ""):
            failures.append("visual: expected a table")
        if visual.startswith("chart"):
            wanted = set(visual.split(":", 1)[1].split("_or_")) if ":" in visual else set()
            if not charts:
                failures.append(f"visual: expected a {visual.split(':')[-1]} chart, got none")
            elif wanted and not (charts & wanted):
                failures.append(f"visual: expected {sorted(wanted)}, got {sorted(charts)}")
    citations = answer.get("citations") or []
    if case.get("expect_citations") is True and outcome == "answered" and not citations:
        failures.append("citations: expected sources, got none")
    if case.get("expect_citations") is False and citations:
        failures.append(f"citations: expected none, got {len(citations)}")
    # A chart or diagram must actually be attached: a ```chart block in the
    # answer, or a server-built visualization.
    if case.get("expect_visual") is True and not (
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


def run(cases: list[dict], *, start_at: int = 1, progress_file: Path | None = None) -> list[dict]:
    # A Supabase access token lasts about an hour; one sign-in for a 2.5-hour
    # run turned every later case into "401 Could not validate credentials"
    # (baseline-e, 15 Oct: cases 123-238). Sign in again on a 401 and retry.
    results = []
    with httpx.Client(base_url=API, headers={"Authorization": f"Bearer {sign_in()}"}, timeout=240) as client:

        def reauth() -> None:
            client.headers["Authorization"] = f"Bearer {sign_in()}"
            print("      signed in again (token expired)", flush=True)

        def ask_signed(query, history, **kwargs):
            answer = ask(client, query, history, **kwargs)
            if answer.get("_unauthorized"):
                reauth()
                answer = ask(client, query, history, **kwargs)
            return answer

        # The endpoint takes a JSON body (every field optional); no body is a 422.
        provision = client.post("/auth/provision", json={})
        provision.raise_for_status()
        expected_tenant = os.getenv("EVAL_TENANT_ID")
        if expected_tenant:
            identity = client.get("/auth/me")
            identity.raise_for_status()
            if identity.json().get("tenant_id") != expected_tenant:
                raise RuntimeError("Evaluation account does not belong to EVAL_TENANT_ID")
        uploads: dict[str, str] = {}
        for index, case in enumerate(cases, start=1):
            if index < start_at:
                continue
            history: list[dict] = []
            document_ids = None
            if case.get("attach"):
                try:
                    try:
                        document_ids = [upload_fixture(client, case["attach"], uploads)]
                    except httpx.HTTPStatusError as exc:
                        if exc.response.status_code != 401:
                            raise
                        reauth()
                        document_ids = [upload_fixture(client, case["attach"], uploads)]
                except Exception as exc:  # noqa: BLE001 — one failed upload fails one case, not the run
                    print(f"      upload failed: {type(exc).__name__}", flush=True)
                    document_ids = []
            for turn in case.get("turns", []):
                earlier = ask_signed(turn, history, case_id=case["id"])
                history += [{"role": "user", "content": turn},
                            {"role": "assistant", "content": (_reply_text(earlier).strip() or "(no answer)")[:4000]}]
                time.sleep(PAUSE_SECONDS)
            started = time.monotonic()
            result = (ask_signed(case["question"], history, case_id=case["id"], document_ids=document_ids)
                      if document_ids != [] else {"_http_error": "fixture upload failed"})
            for wait in OUTAGE_BACKOFF_SECONDS:
                if not _is_outage(result):
                    break
                print(f"      service unavailable ({result['_http_error'][:60]}); retrying in {wait}s", flush=True)
                time.sleep(wait)
                started = time.monotonic()
                result = ask_signed(case["question"], history, case_id=case["id"], document_ids=document_ids)
            seconds = round(time.monotonic() - started, 1)
            try:
                result.update(audit_facts(result.get("query_id", "")))
            except Exception as exc:  # noqa: BLE001 — a missing trail must not stop the run
                print(f"      audit lookup failed: {type(exc).__name__}", flush=True)
            failures = score(case, result)
            from app.domains.evaluation.pipeline_metrics import measure
            metrics = measure(case, result, failures)
            failures += [f"{name}: curated expectation failed" for name, passed in metrics.items() if not passed]
            results.append({
                "id": case["id"], "source": case["source"], "group": case.get("group"), "category": case["category"],
                "question": case["question"], "passed": not failures, "failures": failures,
                "metrics": metrics,
                "outcome": result.get("outcome"), "route": result.get("route"), "seconds": seconds,
                "query_id": result.get("query_id"),
                "expect_intent": case.get("expect_intent"), "rule_intent": rule_intent(case, result),
                "tools_used": result.get("_tools_used") or [], "planned_tools": result.get("_planned_tools") or [],
                "stage_seconds": result.get("_stage_seconds") or {}, "tokens": result.get("_tokens") or 0,
                "chart_types": sorted(chart_types(result)),
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
            if progress_file is not None:
                # Saved as each case finishes, so a crash keeps the finished work.
                with progress_file.open("a") as handle:
                    handle.write(json.dumps(results[-1], ensure_ascii=False) + "\n")
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
    by_source: dict[str, list[dict]] = defaultdict(list)
    for result in results:
        by_source[result.get("group") or result["source"]].append(result)
    if len(by_source) > 1 or "intelligence" in by_source:
        lines += ["", "| Group | Passed | Total | Rate |", "|---|---|---|---|"]
        for source in sorted(by_source):
            rows = by_source[source]
            ok = sum(r["passed"] for r in rows)
            lines.append(f"| {source} | {ok} | {len(rows)} | {100 * ok / len(rows):.0f}% |")
        lines.append(f"| **combined** | {passed} | {len(results)} | {100 * passed / max(len(results), 1):.0f}% |")
    labelled = [r for r in results if r.get("expect_intent")]
    if labelled:
        agree = sum(r["expect_intent"] == r["rule_intent"] for r in labelled)
        lines += ["", f"Intent agreement (current rules vs labels, measured not pass/fail): {agree}/{len(labelled)} "
                      f"({100 * agree / len(labelled):.0f}%)."]
        confusions = Counter(f"{r['expect_intent']} → {r['rule_intent']}" for r in labelled if r["expect_intent"] != r["rule_intent"])
        lines += [f"- {pair}: {count}" for pair, count in confusions.most_common(8)]
    for kind in ("missing_inputs", "tools", "visual", "calculation", "content", "outcome"):
        checked = [r for r in results if any(f.startswith(kind + ":") for f in r["failures"])]
        if checked:
            lines.append(f"Failing {kind} checks: {len(checked)} case(s).")
    stage_values: dict[str, list[float]] = defaultdict(list)
    for result in results:
        for stage, value in (result.get("stage_seconds") or {}).items():
            stage_values[stage].append(value)
    if stage_values:
        lines += ["", "| Stage | Median s | Max s | n |", "|---|---|---|---|"]
        for stage, values in sorted(stage_values.items(), key=lambda kv: -sorted(kv[1])[len(kv[1]) // 2]):
            values.sort()
            if values[len(values) // 2] >= 0.3:
                lines.append(f"| {stage} | {values[len(values) // 2]} | {values[-1]} | {len(values)} |")
    tokens = sum(r.get("tokens") or 0 for r in results)
    if tokens:
        lines += ["", f"Agent tokens used: {tokens:,}."]
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
    parser.add_argument("--start-at", type=int, default=1, help="resume: skip cases before this 1-based index")
    parser.add_argument("--merge", nargs="*", help="earlier results JSON to include in the report (resumed runs)")
    parser.add_argument("--label", default="baseline", help="report file prefix, e.g. uk-vat-before")
    parser.add_argument("--scoring", choices=["v1", "v2"], default="v1",
                        help="v2 also reads space-grouped thousands (\"192 000\") as numbers")
    parser.add_argument("--only", choices=["baseline", "agent", "uk_vat", "uk_vat_holdout", "india_gst", "regression", "gold", "accounting",
                                           "existing", "intelligence", "everything", "planner_shadow", "shadow_eval", "shadow_eval_v2", "shadow_eval_v3"],
                        help="run one dataset (existing = all 206; everything = existing + intelligence)")
    args = parser.parse_args()
    global SCORING_VERSION
    SCORING_VERSION = args.scoring
    cases = load_cases(args.only)
    if args.ids:
        cases = [case for case in cases if case["id"] in set(args.ids)]
    if not cases:
        sys.exit("No cases selected.")
    REPORTS.mkdir(parents=True, exist_ok=True)
    progress = REPORTS / f"{args.label}.progress.jsonl"
    results = run(cases, start_at=args.start_at, progress_file=progress)
    for earlier in args.merge or []:
        results = json.loads(Path(earlier).read_text()) + results
    report = write_reports(results, label=args.label)
    print(f"\nReport: {report}")


if __name__ == "__main__":
    main()
