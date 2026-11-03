"""WF-01 A3: the runtime QA ledger and its HTTP adapter.

  import_pack       the 72 cases and the 292 planned observations (NOT_RUN)
  adapter_readiness CONNECTED only when the configured deployed API answers
                    its health check and accepts the configured service-account
                    API key; otherwise MISSING or UNVERIFIED
  create_run        refuses an unpinned configuration; a run is qualifying
                    only in staging, on a committed build whose clean as-built
                    manifest matches the pinned SHA, through a CONNECTED adapter
  provision_fixtures uploads the checksummed F0-F8 files each case needs
                    (evals/qa_fixtures, case_inputs.json) to the target, F7's
                    private file into a second tenant; a type the target does
                    not accept is recorded UNSUPPORTED, never converted
  execute           sends each case's ASK, less its bracketed tester action,
                    over HTTP as a client would, with its provisioned
                    attachments (and scripted turns, for L02); a case whose
                    fixture is not provisioned, or whose execution the adapter
                    cannot perform, is recorded BLOCKED with the reason
  evaluator_output  the bank's per-observation record (Document 01 §4)
  adjudicate        an independent verdict (not the run's starter), bound to
                    the observation's hashes
  summary           NOT_RUN unless observed; INCONCLUSIVE until adjudicated;
                    PASSED for a case only when every planned repetition in a
                    qualifying run was adjudicated PASSED
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.domains.admin_governance.governance_access import canonical_sha256, governance_error, sign
from app.domains.identity.governance import API_KEY_PREFIX
from app.domains.evaluation.qa_models import (
    QaAdjudication, QaBaseline, QaCase, QaFixtureProvision, QaObservation, QaRun,
)

PACK = Path(__file__).resolve().parents[3] / "evals" / "qa_pack_72_manifest.DRAFT.json"
FIXTURES = Path(__file__).resolve().parents[3] / "evals" / "qa_fixtures"
PINNED_FIELDS = ("release_sha", "environment", "model", "retriever", "prompt_version", "policy_version", "region",
                 "oracle_version", "adapter_id")
ASK_PATH = "/api/v1/orchestration/ask"     # the route a client calls; tests check the app serves it
UPLOAD_PATH = "/api/v1/kriton-workspace/attachments"
UPLOADABLE = {".pdf", ".docx", ".xlsx", ".pptx", ".csv"}   # what UPLOAD_PATH accepts (kriton_workspace/router.py)
TENANT_B_FILES = {"F7/TENANT-B-PRIVATE.csv"}                # seeded in the second tenant, never attached
_UPLOAD = re.compile(r"\[(?:upload|attach)[^\]]*\]", re.I)
_TESTER_ACTION = re.compile(r"\[[^\]]*\]\s*")


def pack_sha(pack: dict) -> str:
    return canonical_sha256([{k: c[k] for k in ("case_id", "priority", "text_sha256")} for c in pack["cases"]])


def ask_text(case_text: str) -> str:
    """The ASK line exactly, less its bracketed tester actions: "Brackets
    denote an action performed by the tester, not literal prompt text"
    (Document 01 §5). The action itself is performed through case_inputs."""
    for line in case_text.splitlines():
        if line.startswith("ASK "):
            return _TESTER_ACTION.sub("", line[4:]).strip()
    return ""


def fixture_manifests() -> dict[str, dict]:
    if not FIXTURES.exists():
        return {}
    return {p.parent.name: json.loads(p.read_text()) for p in sorted(FIXTURES.glob("F*/MANIFEST.json"))}


def case_inputs() -> dict[str, dict]:
    path = FIXTURES / "case_inputs.json"
    return json.loads(path.read_text())["cases"] if path.exists() else {}


def _file_index() -> dict[str, dict]:
    """"F2/NB-STATEMENTS.pdf" -> its manifest entry, with the file's current
    checksum: a file that no longer matches its manifest is not usable."""
    out = {}
    for fixture, manifest in fixture_manifests().items():
        for f in manifest["files"]:
            path = FIXTURES / fixture / f["name"]
            actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
            out[f"{fixture}/{f['name']}"] = {**f, "fixture_id": fixture, "status": manifest["status"],
                                             "intact": actual == f["sha256"]}
    return out


def _required_files() -> set[str]:
    needed = set(TENANT_B_FILES)
    for entry in case_inputs().values():
        needed |= set(entry.get("attach", []))
    return needed


async def _provisions(db: AsyncSession, base_url: str) -> dict[tuple[str, str], QaFixtureProvision]:
    """Latest PROVISIONED/UNSUPPORTED record per (file ref, sha256) at this target."""
    rows = (await db.execute(select(QaFixtureProvision).where(QaFixtureProvision.base_url == base_url)
                             .order_by(QaFixtureProvision.created_at))).scalars()
    out = {}
    for row in rows:
        if row.status in ("PROVISIONED", "UNSUPPORTED"):
            out[(f"{row.fixture_id}/{row.file_name}", row.file_sha256)] = row
    return out


async def fixtures_status(db: AsyncSession) -> dict:
    base = get_settings().KRITON_QA_ADAPTER_BASE_URL.rstrip("/")
    provisions = await _provisions(db, base) if base else {}
    required = _required_files()
    files = []
    for ref, f in sorted(_file_index().items()):
        p = provisions.get((ref, f["sha256"]))
        # A file no case uses (the JSON copies) is never uploaded: not a gap.
        provision = p.status if p else ("NOT_PROVISIONED" if ref in required else "NOT_REQUIRED")
        files.append({"ref": ref, "fixture_id": f["fixture_id"], "sha256": f["sha256"], "intact": f["intact"],
                      "uploadable": f["uploadable"], "used_by": f["used_by"], "manifest_status": f["status"],
                      "tenant_slot": "B" if ref in TENANT_B_FILES else "A",
                      "provision": provision, "document_id": p.document_id if p else None})
    manifests = fixture_manifests()
    return {"target": base or None, "fixtures": {k: {"status": m["status"], "signature": m["signature"],
                                                     "specification": m["specification"], "derivations": m["derivations"]}
                                                 for k, m in manifests.items()},
            "files": files}


async def provision_fixtures(db: AsyncSession, actor, *, client: httpx.AsyncClient | None = None) -> dict:
    """Upload every fixture file a case needs to the configured target, once
    per (file, checksum, target). Tenant-A files go with the QA service
    account; F7's private file with the tenant-B account. Refuses a file whose
    bytes no longer match its manifest."""
    settings = get_settings()
    base = settings.KRITON_QA_ADAPTER_BASE_URL.rstrip("/")
    keys = {"A": settings.KRITON_QA_ADAPTER_API_KEY, "B": settings.KRITON_QA_ADAPTER_TENANT_B_API_KEY}
    readiness = await adapter_readiness(client)
    if readiness["readiness"] != "CONNECTED":
        raise governance_error("ADAPTER_NOT_CONNECTED", f"Adapter {readiness['readiness']}: {readiness.get('reason', '')}.", 409)
    index, existing = _file_index(), await _provisions(db, base)
    owns = client is None
    client = client or httpx.AsyncClient(timeout=300)
    result = {"PROVISIONED": [], "ALREADY": [], "UNSUPPORTED": [], "FAILED": [], "SKIPPED": []}
    try:
        for ref in sorted(_required_files()):
            f = index.get(ref)
            if f is None or not f["intact"]:
                raise governance_error("FIXTURE_CHECKSUM_MISMATCH", f"{ref} is missing or does not match its manifest.", 409)
            if (ref, f["sha256"]) in existing:
                result["ALREADY"].append(ref)
                continue
            slot = "B" if ref in TENANT_B_FILES else "A"
            row = dict(fixture_id=f["fixture_id"], file_name=f["name"], file_sha256=f["sha256"],
                       environment=settings.KRITON_ENVIRONMENT, base_url=base, tenant_slot=slot, provisioned_by=actor.id)
            if Path(f["name"]).suffix not in UPLOADABLE:
                db.add(QaFixtureProvision(**row, status="UNSUPPORTED",
                                          reason=f"the target accepts {sorted(UPLOADABLE)} attachments only"))
                result["UNSUPPORTED"].append(ref)
                continue
            if not keys[slot]:
                result["SKIPPED"].append(f"{ref} (no tenant-{slot} service-account key configured)")
                continue
            data = (FIXTURES / f["fixture_id"] / f["name"]).read_bytes()
            try:
                response = await client.post(f"{base}{UPLOAD_PATH}", files={"file": (f["name"], data)},
                                              headers={"Authorization": f"Bearer {keys[slot]}"})
                body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
            except httpx.HTTPError as exc:
                response, body = None, {"detail": type(exc).__name__}
            if response is not None and response.status_code == 200 and body.get("document_id"):
                db.add(QaFixtureProvision(**row, status="PROVISIONED", document_id=body["document_id"],
                                          reason=f"target status {body.get('status', '')}"))
                result["PROVISIONED"].append(ref)
            else:
                db.add(QaFixtureProvision(**row, status="FAILED", reason=f"HTTP {getattr(response, 'status_code', '-')}: "
                                                                          f"{str(body.get('detail', ''))[:300]}"))
                result["FAILED"].append(ref)
            await db.commit()
    finally:
        if owns:
            await client.aclose()
    await db.commit()
    return {"target": base, **result}


async def import_pack(db: AsyncSession, pack: dict | None = None) -> dict:
    pack = pack or json.loads(PACK.read_text())
    sha = pack_sha(pack)
    if (await db.execute(select(QaCase).where(QaCase.pack_sha256 == sha))).scalars().first() is not None:
        return {"pack_sha256": sha, "imported": False, "status": pack.get("status")}
    for case in pack["cases"]:
        db.add(QaCase(pack_sha256=sha, case_id=case["case_id"], suite=case["suite"], title=case["title"],
                      priority=case["priority"], fixture=case["fixture"], text=case["text"], text_sha256=case["text_sha256"],
                      planned_repetitions=case["planned_repetitions"], requires_upload=bool(_UPLOAD.search(case["text"]))))
        for repetition in range(1, case["planned_repetitions"] + 1):
            db.add(QaBaseline(pack_sha256=sha, case_id=case["case_id"], repetition=repetition, status="NOT_RUN"))
    await db.commit()
    return {"pack_sha256": sha, "imported": True, "status": pack.get("status")}


async def adapter_readiness(client: httpx.AsyncClient | None = None) -> dict:
    settings = get_settings()
    base, key = settings.KRITON_QA_ADAPTER_BASE_URL.rstrip("/"), settings.KRITON_QA_ADAPTER_API_KEY
    if not base or not key:
        return {"readiness": "MISSING", "reason": "KRITON_QA_ADAPTER_BASE_URL and KRITON_QA_ADAPTER_API_KEY are not configured"}
    if not key.startswith(API_KEY_PREFIX):
        return {"readiness": "UNVERIFIED", "reason": "KRITON_QA_ADAPTER_API_KEY is not a service-account API key"}
    owns = client is None
    client = client or httpx.AsyncClient(timeout=15)
    try:
        health = await client.get(f"{base}/health/version")
        me = await client.get(f"{base}/api/v1/auth/me", headers={"Authorization": f"Bearer {key}"})
        if health.status_code == 200 and me.status_code == 200:
            identity, build = me.json(), health.json()
            return {"readiness": "CONNECTED", "base_url": base, "service_account_id": identity.get("id"),
                    "role": identity.get("role"), "tenant_id": identity.get("tenant_id"), "build": build}
        return {"readiness": "UNVERIFIED", "reason": f"health {health.status_code}, identity {me.status_code}"}
    except httpx.HTTPError as exc:
        return {"readiness": "UNVERIFIED", "reason": f"{type(exc).__name__}"}
    finally:
        if owns:
            await client.aclose()


async def create_run(db: AsyncSession, actor, pinned: dict, key: str, *, readiness: dict) -> dict:
    replay = (await db.execute(select(QaRun).where(QaRun.idempotency_key == key))).scalar_one_or_none()
    if replay is not None:
        return _run_public(replay)
    missing = [f for f in PINNED_FIELDS if not str(pinned.get(f) or "").strip()]
    if missing:
        raise governance_error("UNPINNED_CONFIGURATION", f"Pin every field before running: missing {missing}.", 422)
    case = (await db.execute(select(QaCase).order_by(QaCase.created_at.desc()))).scalars().first()
    if case is None:
        raise governance_error("PACK_NOT_IMPORTED", "Import the QA pack first.", 409)
    from app.domains.operations.asbuilt_models import AsBuiltManifest
    manifest = (await db.execute(select(AsBuiltManifest).where(AsBuiltManifest.commit_sha == pinned["release_sha"])
                                 .order_by(AsBuiltManifest.created_at.desc()))).scalars().first()
    qualifying = (pinned["environment"] == "staging" == get_settings().KRITON_ENVIRONMENT and readiness["readiness"] == "CONNECTED"
                  and manifest is not None and manifest.tree_clean)
    # The bank freezes the input-file hashes with the run (Document 01 §4).
    pinned = {**pinned, "fixture_manifest_sha256": canonical_sha256(
        {k: [f["sha256"] for f in m["files"]] for k, m in fixture_manifests().items()})}
    row = QaRun(pack_sha256=case.pack_sha256, pinned=pinned, pinned_sha256=canonical_sha256(pinned),
                environment=pinned["environment"], qualifying=qualifying, adapter_readiness=readiness["readiness"],
                started_by=actor.id, idempotency_key=key)
    db.add(row)
    await db.commit()
    return _run_public(row)


def _run_public(row: QaRun) -> dict:
    return {"id": row.id, "pack_sha256": row.pack_sha256, "environment": row.environment, "qualifying": row.qualifying,
            "adapter_readiness": row.adapter_readiness, "pinned_sha256": row.pinned_sha256, "started_by": row.started_by,
            "pinned": row.pinned}


async def list_runs(db: AsyncSession) -> list[dict]:
    rows = (await db.execute(select(QaRun).order_by(QaRun.created_at.desc()))).scalars()
    return [{**_run_public(r), "created_at": r.created_at.isoformat()} for r in rows]


def _blocked_reason(entry: dict, index: dict, provisions: dict) -> tuple[str, list[dict]]:
    """("", attachments) when the case can be sent; otherwise the reason it is BLOCKED."""
    if entry.get("unsupported"):
        return f"execution capability missing: {entry['unsupported']}", []
    attachments, missing, unsupported = [], [], []
    refs = list(entry.get("attach", [])) + (sorted(TENANT_B_FILES) if entry.get("tenant_b_seed") else [])
    for ref in refs:
        f = index.get(ref)
        if f is None or not f["intact"]:
            return f"fixture file {ref} missing or does not match its manifest", []
        if Path(ref).suffix not in UPLOADABLE:
            unsupported.append(ref)
            continue
        p = provisions.get((ref, f["sha256"]))
        if p is None or p.status != "PROVISIONED":
            missing.append(ref)
        elif ref not in TENANT_B_FILES:
            attachments.append({"ref": ref, "sha256": f["sha256"], "document_id": p.document_id})
    if unsupported:
        return f"the target does not accept these uploads: {unsupported}", []
    if missing:
        return f"fixture not provisioned in this environment: {missing}", []
    return "", attachments


async def _ask(client, base, key, body):
    response = await client.post(f"{base}{ASK_PATH}", json=body,
                                 headers={"Authorization": f"Bearer {key}", "Idempotency-Key": body["request_id"]})
    payload = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
    answer = ((payload.get("answer") or {}).get("text") or (payload.get("next_action") or {}).get("message") or "")
    return response, payload, answer


async def execute(db: AsyncSession, run_id: str, *, case_ids: list[str] | None = None, limit: int = 10,
                  client: httpx.AsyncClient | None = None) -> dict:
    run = (await db.execute(select(QaRun).where(QaRun.id == run_id))).scalar_one_or_none()
    if run is None:
        raise governance_error("UNKNOWN_RUN", "No such run.", 404)
    readiness = await adapter_readiness(client)
    if readiness["readiness"] != "CONNECTED":
        raise governance_error("ADAPTER_NOT_CONNECTED", f"Adapter {readiness['readiness']}: {readiness.get('reason', '')}. "
                               "Observations stay NOT_RUN.", 409)
    done = {(o.case_id, o.repetition) for o in (await db.execute(select(QaObservation).where(QaObservation.run_id == run_id))).scalars()}
    cases = list((await db.execute(select(QaCase).where(QaCase.pack_sha256 == run.pack_sha256).order_by(QaCase.case_id))).scalars())
    if case_ids:
        cases = [c for c in cases if c.case_id in set(case_ids)]
    settings = get_settings()
    base, key = settings.KRITON_QA_ADAPTER_BASE_URL.rstrip("/"), settings.KRITON_QA_ADAPTER_API_KEY
    inputs, index, provisions = case_inputs(), _file_index(), await _provisions(db, base)
    owns = client is None
    client = client or httpx.AsyncClient(timeout=150)
    recorded = {"EXECUTED": 0, "BLOCKED": 0, "FAILED_TO_EXECUTE": 0}
    try:
        for case in cases:
            entry = inputs.get(case.case_id, {"attach": [], "fixtures": []})
            for repetition in range(1, case.planned_repetitions + 1):
                if (case.case_id, repetition) in done or sum(recorded.values()) >= limit:
                    continue
                prompt = ask_text(case.text)
                reason, attachments = _blocked_reason(entry, index, provisions)
                fixture_hash = canonical_sha256(sorted(a["sha256"] for a in attachments)) if attachments else None
                if reason:
                    db.add(QaObservation(run_id=run_id, case_id=case.case_id, repetition=repetition, state="BLOCKED",
                                         reason=reason, request_sha256=hashlib.sha256(prompt.encode()).hexdigest()))
                    recorded["BLOCKED"] += 1
                    await db.commit()
                    continue
                turns = entry.get("turns") or [prompt]
                conversation = f"qa-{run_id}-{case.case_id}-{repetition}"
                history, turn_trace, started = [], [], time.monotonic()
                body = {}
                try:
                    for n, turn in enumerate(turns, start=1):
                        body = {"query": turn, "conversation_id": conversation,
                                "request_id": f"qa:{run_id}:{case.case_id}:{repetition}:{n}",
                                "document_ids": [a["document_id"] for a in attachments],
                                "conversation_history": history[-12:],
                                **({"previous_query": turns[n - 2]} if n > 1 else {})}
                        response, payload, answer = await _ask(client, base, key, body)
                        turn_trace.append({"turn": n, "http_status": response.status_code, "query_id": payload.get("query_id")})
                        if response.status_code != 200:
                            break
                        history += [{"role": "user", "content": turn}, {"role": "assistant", "content": answer or "-"}]
                    trace = {"http_status": response.status_code, "query_id": payload.get("query_id"),
                             "outcome": payload.get("outcome"), "route": payload.get("route"),
                             "citations": [c.get("url") or c.get("source_id")
                                           for c in ((payload.get("answer") or {}).get("citations") or [])][:10],
                             "attachments": attachments, "fixture_hash": fixture_hash, "turns": turn_trace,
                             "role": readiness.get("role"), "seconds": round(time.monotonic() - started, 2)}
                    state = "EXECUTED" if response.status_code == 200 else "FAILED_TO_EXECUTE"
                    checks = {"http_ok": response.status_code == 200, "answered_or_asked": bool(answer.strip()),
                              "outcome": payload.get("outcome"), "citations": len(trace["citations"]),
                              # A deployment with no model provider answers with the gateway's mock:
                              # flagged so no adjudicator mistakes it for a model answer.
                              "mock_completion": answer.lstrip().startswith("[mock completion]")}
                    db.add(QaObservation(run_id=run_id, case_id=case.case_id, repetition=repetition, state=state,
                                         reason="" if state == "EXECUTED" else f"HTTP {response.status_code}: {str(payload.get('detail', ''))[:300]}",
                                         request_sha256=canonical_sha256({"turns": turns, "attachments": attachments}),
                                         output_sha256=hashlib.sha256(answer.encode()).hexdigest(),
                                         output_excerpt=answer[:2000], trace=trace, automated_checks=checks))
                    recorded[state] += 1
                except httpx.HTTPError as exc:
                    db.add(QaObservation(run_id=run_id, case_id=case.case_id, repetition=repetition, state="FAILED_TO_EXECUTE",
                                         reason=type(exc).__name__, request_sha256=canonical_sha256(body)))
                    recorded["FAILED_TO_EXECUTE"] += 1
                await db.commit()
    finally:
        if owns:
            await client.aclose()
    await db.commit()
    return {"run_id": run_id, "recorded": recorded}


async def adjudicate(db: AsyncSession, actor, observation_id: str, *, verdict: str, oracle_version: str, reason: str,
                     key: str) -> dict:
    replay = (await db.execute(select(QaAdjudication).where(QaAdjudication.idempotency_key == key))).scalar_one_or_none()
    if replay is not None:
        return {"id": replay.id, "verdict": replay.verdict, "signature_status": replay.signature_status}
    observation = (await db.execute(select(QaObservation).where(QaObservation.id == observation_id))).scalar_one_or_none()
    if observation is None:
        raise governance_error("UNKNOWN_OBSERVATION", "No such observation.", 404)
    run = (await db.execute(select(QaRun).where(QaRun.id == observation.run_id))).scalar_one()
    if run.started_by == actor.id:
        raise governance_error("INDEPENDENCE_REQUIRED", "The person who started a run cannot adjudicate it.", 403)
    if observation.state != "EXECUTED":
        raise governance_error("EVIDENCE_NOT_RUN", f"An observation in state {observation.state} cannot be adjudicated.")
    if verdict not in ("PASSED", "FAILED", "INCONCLUSIVE") or not oracle_version.strip():
        raise governance_error("INVALID_ADJUDICATION", "verdict is PASSED, FAILED or INCONCLUSIVE, with an oracle version.", 422)
    observation_sha = canonical_sha256({"id": observation.id, "request": observation.request_sha256,
                                        "output": observation.output_sha256, "trace": observation.trace})
    _, signature_status = sign(observation_sha)
    row = QaAdjudication(observation_id=observation_id, verdict=verdict, oracle_version=oracle_version, reason=reason,
                         adjudicator_id=actor.id, observation_sha256=observation_sha, signature_status=signature_status,
                         idempotency_key=key)
    db.add(row)
    await db.commit()
    return {"id": row.id, "verdict": verdict, "signature_status": signature_status}


async def summary(db: AsyncSession) -> dict:
    """Case and observation status across every run of the latest pack.
    Only a qualifying run's adjudicated PASSED observations can pass a case."""
    latest = (await db.execute(select(QaCase).order_by(QaCase.created_at.desc()))).scalars().first()
    if latest is None:
        return {"pack_sha256": None, "cases": 0, "planned_observations": 0, "case_status": {}, "observation_status": {}}
    sha = latest.pack_sha256
    cases = list((await db.execute(select(QaCase).where(QaCase.pack_sha256 == sha))).scalars())
    planned = (await db.execute(select(func.count()).select_from(QaBaseline).where(QaBaseline.pack_sha256 == sha))).scalar()
    runs = {r.id: r for r in (await db.execute(select(QaRun).where(QaRun.pack_sha256 == sha))).scalars()}
    observations = list((await db.execute(select(QaObservation).where(QaObservation.run_id.in_(list(runs) or [""])))).scalars())
    adjudications: dict[str, str] = {}
    for adj in (await db.execute(select(QaAdjudication).order_by(QaAdjudication.created_at))).scalars():
        adjudications[adj.observation_id] = adj.verdict
    observation_status: dict[str, int] = {}
    case_status: dict[str, str] = {}
    for case in cases:
        mine = [o for o in observations if o.case_id == case.case_id]
        qualifying = [o for o in mine if runs[o.run_id].qualifying]
        def verdict_of(o):
            if o.state != "EXECUTED":
                # FAILED_TO_EXECUTE is an infrastructure outcome, not evidence about the answer.
                return "BLOCKED" if o.state == "BLOCKED" else "INCONCLUSIVE"
            return adjudications.get(o.id, "INCONCLUSIVE")
        if not mine:
            case_status[case.case_id] = "NOT_RUN"
        else:
            verdicts = {r: verdict_of(o) for o in qualifying for r in [o.repetition]}
            if len(verdicts) == case.planned_repetitions and set(verdicts.values()) == {"PASSED"}:
                case_status[case.case_id] = "PASSED"
            elif any(verdict_of(o) == "FAILED" for o in mine):
                case_status[case.case_id] = "FAILED"
            elif any(o.state == "BLOCKED" for o in mine):
                case_status[case.case_id] = "BLOCKED"
            else:
                case_status[case.case_id] = "INCONCLUSIVE"
    for key in ("NOT_RUN", "EXECUTED", "BLOCKED", "FAILED_TO_EXECUTE"):
        observation_status[key] = 0
    observed = {(o.case_id, o.repetition) for o in observations}
    observation_status["NOT_RUN"] = planned - len(observed)
    for o in observations:
        observation_status[o.state] = observation_status.get(o.state, 0) + 1
    counts: dict[str, int] = {}
    for value in case_status.values():
        counts[value] = counts.get(value, 0) + 1
    return {"pack_sha256": sha, "cases": len(cases), "planned_observations": planned, "case_counts": counts,
            "observation_status": observation_status, "qualifying_runs": sum(r.qualifying for r in runs.values()),
            "p0_passed": sum(case_status[c.case_id] == "PASSED" for c in cases if c.priority == "P0"),
            "p0_total": sum(c.priority == "P0" for c in cases), "case_status": case_status}


async def observations(db: AsyncSession, run_id: str) -> list[dict]:
    adjudicated = {a.observation_id: a.verdict for a in (await db.execute(select(QaAdjudication))).scalars()}
    rows = (await db.execute(select(QaObservation).where(QaObservation.run_id == run_id)
                             .order_by(QaObservation.case_id, QaObservation.repetition))).scalars()
    return [{"id": o.id, "case_id": o.case_id, "repetition": o.repetition, "state": o.state, "reason": o.reason,
             "output_excerpt": o.output_excerpt, "trace": o.trace, "automated_checks": o.automated_checks,
             "adjudication": adjudicated.get(o.id, "NOT_ADJUDICATED")} for o in rows]


async def evaluator_output(db: AsyncSession, run_id: str) -> list[dict]:
    """Document 01 §4: {run_id, case_id, fixture_hash, model_version,
    source_snapshot, numeric_checks, cite_checks, tool_trace_id, role, status,
    failure_reason, owner, retest_id}. Numeric and citation checks need an
    adjudicator's oracle: NOT_RUN here. Status is the adjudicated disposition;
    an executed, unadjudicated observation is PENDING_ADJUDICATION, never PASS."""
    run = (await db.execute(select(QaRun).where(QaRun.id == run_id))).scalar_one_or_none()
    if run is None:
        raise governance_error("UNKNOWN_RUN", "No such run.", 404)
    verdicts = {a.observation_id: a for a in (await db.execute(select(QaAdjudication).order_by(QaAdjudication.created_at))).scalars()}
    disposition = {"PASSED": "PASS", "FAILED": "FAIL", "INCONCLUSIVE": "INCONCLUSIVE"}
    out = []
    for o in (await db.execute(select(QaObservation).where(QaObservation.run_id == run_id)
                               .order_by(QaObservation.case_id, QaObservation.repetition))).scalars():
        adjudication = verdicts.get(o.id)
        if o.state == "BLOCKED":
            status = "BLOCKED"
        elif o.state != "EXECUTED":
            status = "NOT RUN"
        else:
            status = disposition[adjudication.verdict] if adjudication else "PENDING_ADJUDICATION"
        trace = o.trace or {}
        out.append({"run_id": run_id, "case_id": o.case_id, "repetition": o.repetition,
                    "fixture_hash": trace.get("fixture_hash"), "model_version": run.pinned.get("model"),
                    "source_snapshot": run.pinned.get("retriever"), "numeric_checks": "NOT_RUN", "cite_checks": "NOT_RUN",
                    "tool_trace_id": trace.get("query_id"), "role": trace.get("role"), "status": status,
                    "failure_reason": o.reason or (adjudication.reason if adjudication and adjudication.verdict != "PASSED" else ""),
                    "owner": None, "retest_id": None,
                    "signature_status": adjudication.signature_status if adjudication else "NOT_RUN"})
    return out
