"""WF-01: the platform release verdict, derived server-side from the gates.

Each gate is SATISFIED, PENDING, BLOCKED or NOT_RUN; nothing else counts and
missing evidence is NOT_RUN, never SATISFIED. The verdict is GO only when
every gate is SATISFIED, and otherwise NO_GO with each gate's reason.

  authority     no unresolved identifier collision, no cited document
                missing from the repository (decision D8)
  ownership     the gap allocation ratified, not only adopted (D1)
  qa_pack       the 72-case manifest and fixtures F0-F8 ratified (D5)
  asbuilt       the latest manifest is of a clean commit in staging, every
                requirement MAPPED, and verified by someone else (A2)
  runtime_qa    every planned observation of a qualifying run adjudicated,
                every case PASSED (A3; P0 cases need all five repetitions)
  signing       records are signed (KRITON_GOVERNANCE_SIGNING_KEY)

Recording a verdict appends it; promotion of a governance-tenant release
reads the computed verdict at that moment (releases.transition).
"""
from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.domains.admin_governance import authority, gap_ownership
from app.domains.admin_governance.governance_access import canonical_sha256
from app.domains.admin_governance.governance_models import ReleaseVerdict
from app.domains.evaluation import qa_ledger
from app.domains.operations import asbuilt

GATE_STATES = ("SATISFIED", "PENDING", "BLOCKED", "NOT_RUN")


def _gate(state: str, reason: str, **evidence) -> dict:
    assert state in GATE_STATES
    return {"state": state, "reason": reason, "evidence": evidence}


async def _authority(db: AsyncSession) -> dict:
    s = await authority.summary(db)
    if not s["documents"]:
        return _gate("NOT_RUN", "The authority register has not been imported.")
    unavailable = s["states"].get("EVIDENCE_UNAVAILABLE_IN_REPO", 0)
    if s["unresolved_collisions"] or unavailable:
        return _gate("BLOCKED", f"{len(s['unresolved_collisions'])} unresolved identifier collision(s) "
                     f"({', '.join(s['unresolved_collisions'])}); {unavailable} cited document(s) not in the repository.",
                     **s)
    return _gate("SATISFIED", "Every identifier resolves to one held document.", **s)


async def _ownership(db: AsyncSession) -> dict:
    current = await gap_ownership.current(db)
    if current["status"] == "NOT_ADOPTED":
        return _gate("NOT_RUN", "The gap allocation has not been adopted.", **current)
    if current["status"] != "RATIFIED":
        return _gate("PENDING", "The gap allocation is adopted but not ratified.", **current)
    if current["content_sha256"] != current["proposed_sha256"]:
        return _gate("PENDING", "registry/gap_ownership.json changed after ratification.", **current)
    return _gate("SATISFIED", "The gap allocation is ratified.", **current)


def _qa_pack() -> dict:
    pack = json.loads(qa_ledger.PACK.read_text())
    fixtures = {k: m["status"] for k, m in qa_ledger.fixture_manifests().items()}
    unratified = sorted(k for k, status in fixtures.items() if status != "RATIFIED")
    problems = []
    if pack.get("status") != "RATIFIED" or not pack.get("release_evidence"):
        problems.append(f"the QA manifest is {pack.get('status')}; QA Automation must ratify it as the baseline (D5)")
    if len(fixtures) != 9 or unratified:
        problems.append(f"fixtures {unratified or 'F0-F8'} are not ratified (Document 01 §3: signed or checksummed, "
                        "approved by the bank's owners)")
    if problems:
        reason = "; ".join(problems)
        return _gate("BLOCKED", reason[0].upper() + reason[1:] + ".", status=pack.get("status"), fixtures=fixtures)
    return _gate("SATISFIED", "The QA manifest and fixtures F0-F8 are ratified.", status=pack["status"], fixtures=fixtures)


async def _asbuilt(db: AsyncSession) -> dict:
    latest = await asbuilt.latest(db)
    if latest is None:
        return _gate("NOT_RUN", "No as-built manifest has been recorded.")
    unmapped = [m["requirement_id"] for m in latest["mappings"] if m["status"] != "MAPPED"]
    problems = []
    if not latest["tree_clean"] or not latest["commit_sha"]:
        problems.append("built from an uncommitted tree")
    if latest["environment"] != "staging":
        problems.append(f"environment is {latest['environment']}, not staging")
    if unmapped:
        problems.append(f"{len(unmapped)} requirement(s) UNMAPPED")
    evidence = {"manifest_id": latest["id"], "commit_sha": latest["commit_sha"], "environment": latest["environment"],
                "verification": latest["verification"], "unmapped": unmapped}
    if problems:
        return _gate("BLOCKED", "; ".join(problems) + ".", **evidence)
    if latest["verification"] != "VERIFIED":
        return _gate("PENDING" if latest["verification"] == "NOT_RUN" else "BLOCKED",
                     f"Independent verification is {latest['verification']}.", **evidence)
    return _gate("SATISFIED", "A verified manifest of a clean staging commit.", **evidence)


async def _runtime_qa(db: AsyncSession) -> dict:
    s = await qa_ledger.summary(db)
    if not s["pack_sha256"]:
        return _gate("NOT_RUN", "The QA pack has not been imported.")
    evidence = {k: s[k] for k in ("planned_observations", "observation_status", "case_counts", "qualifying_runs",
                                  "p0_passed", "p0_total")}
    if not s["qualifying_runs"]:
        return _gate("NOT_RUN", "No qualifying run (staging, clean committed build, connected adapter).", **evidence)
    passed = s["case_counts"].get("PASSED", 0)
    if passed == s["cases"]:
        return _gate("SATISFIED", f"All {s['cases']} cases passed, adjudicated.", **evidence)
    if s["case_counts"].get("FAILED") or s["case_counts"].get("BLOCKED"):
        return _gate("BLOCKED", f"{passed}/{s['cases']} cases passed; {s['case_counts'].get('FAILED', 0)} failed, "
                     f"{s['case_counts'].get('BLOCKED', 0)} blocked.", **evidence)
    return _gate("PENDING", f"{passed}/{s['cases']} cases passed; the rest are not run or not adjudicated.", **evidence)


def _signing() -> dict:
    if not get_settings().KRITON_GOVERNANCE_SIGNING_KEY:
        return _gate("BLOCKED", "No signing key is configured: records are UNSIGNED_NO_KEY.")
    return _gate("SATISFIED", "Records are signed.")


async def compute(db: AsyncSession) -> dict:
    gates = {"authority": await _authority(db), "ownership": await _ownership(db), "qa_pack": _qa_pack(),
             "asbuilt": await _asbuilt(db), "runtime_qa": await _runtime_qa(db), "signing": _signing()}
    verdict = "GO" if all(g["state"] == "SATISFIED" for g in gates.values()) else "NO_GO"
    return {"scope": "platform", "verdict": verdict, "gates": gates, "evidence_sha256": canonical_sha256(gates)}


async def record(db: AsyncSession, actor, key: str) -> dict:
    replay = (await db.execute(select(ReleaseVerdict).where(ReleaseVerdict.idempotency_key == key))).scalar_one_or_none()
    if replay is not None:
        return {"id": replay.id, "verdict": replay.verdict, "gates": replay.gates, "evidence_sha256": replay.evidence_sha256}
    computed = await compute(db)
    row = ReleaseVerdict(scope="platform", verdict=computed["verdict"], gates=computed["gates"],
                         evidence_sha256=computed["evidence_sha256"], requested_by=actor.id, idempotency_key=key)
    db.add(row)
    await db.commit()
    return {"id": row.id, **computed}
