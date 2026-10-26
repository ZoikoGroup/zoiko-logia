"""Financial Statements Workspace (ZoikoLogia Document 02, ZL-FSR-WF-002,
screen FR-WF-001).

One canonical screen over the three engines, composed read-only:
  Document 04 trial-balance intake (source package, mappings, findings),
  Document 03 framework resolution (scope, framework, effective rules),
  Document 05 report package (statements, checks, notes, sign-offs).

It adds no accounting of its own. It answers the user promise (§1): which
standards and dates apply, where every figure came from, what is wrong or
uncertain, what evidence and approvals are needed, and what can be exported
now and with which status. Findings from all three engines meet in one
validation rail with the §7.2 severities. The §7.1 state machine and the
release label are derived, never asserted: "compliant" is not a word this
screen produces. A prompt or request to publish is refused and logged
(WF-11); publishing and filing belong to Documents 06 and 07.
"""
from __future__ import annotations

import hashlib
import json

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.audit_ledger.event_envelope import record_event_async

from . import packages, resolutions, store
from .mapping import LINES
from .store import NotFound, Refused

HARD_STOP, MATERIAL_REVIEW, INFORMATION = "HARD_STOP", "MATERIAL_REVIEW", "INFORMATION"
_FROM_04 = {"HARD_STOP": HARD_STOP, "REVIEW": MATERIAL_REVIEW, "INFO": INFORMATION}
_FROM_05 = {"P0": HARD_STOP, "P1": HARD_STOP, "P2": MATERIAL_REVIEW, "P3": INFORMATION}
_MISLEADING = ("X-01", "X-02", "X-04")          # a draft that fails these would be materially misleading (§4)
RELEASE_LABEL = {"INCOMPLETE_SCOPE": "BLOCKED", "SOURCE_INTAKE": "BLOCKED", "DRAFT_BLOCKED": "BLOCKED",
                 "PREPARER_READY": "DRAFT", "IN_REVIEW": "IN REVIEW", "APPROVED_FOR_ISSUE": "APPROVED",
                 "PUBLISHED": "PUBLISHED"}
REVIEW_SEQUENCE = (("preparer", "Preparer"), ("technical_reviewer", "Reviewer"), ("disclosure_owner", "Disclosure owner"),
                   ("issuer", "Approver"), ("publisher", "Publisher"))


def _item(source: str, severity: str, code: str, message: str, rule: str, action: str, refs=()) -> dict:
    return {"source": source, "severity": severity, "code": code, "message": message, "rule": rule, "action": action,
            "refs": list(refs)}


def misleading_reasons(result: dict) -> list[str]:
    """Why even a watermarked draft would mislead (§4 Preview draft)."""
    reasons = []
    if result.get("halted"):
        reasons.append(f"The package was not assembled: {result['halted'].replace('_', ' ').lower()}.")
    for a in result.get("assertions", []):
        if a["assertion_id"] in _MISLEADING and a["status"] == "FAIL":
            reasons.append(f"{a['assertion_id']} {a['title']} fails by {a['residual']}.")
    return reasons


def rail(tb: dict, resolution: dict | None, package: dict) -> list[dict]:
    """One validation rail from the three engines, de-duplicated, most severe first (§3 area 08)."""
    items = []
    for f in tb.get("findings", []):
        items.append(_item("Trial balance (Document 04)", _FROM_04.get(f["severity"], INFORMATION), f["code"],
                           f["message"], f["rule"], "Resolve in Trial balance intake.", f.get("refs", ())))
    for m in tb.get("mappings", []):
        if m["status"] != "APPROVED":
            items.append(_item("Classification (Document 04)", HARD_STOP, f"CLASSIFICATION_{m['status']}",
                               f"{m['account_name']} ({m['balance']}): {m['status'].replace('_', ' ').lower()}"
                               + (f"; evidence needed: {m['evidence_required']}" if m.get("evidence_required") else ""),
                               "SD-025", "A reviewer approves the mapping with evidence; no speculative split.",
                               (m["account_key"],)))
    if resolution is not None:
        for f in resolution["result"].get("findings", []):
            items.append(_item("Framework (Document 03)", HARD_STOP, f["code"], f["reason"], "R0–R7", f["action"]))
    result = package["result"]
    for f in result.get("findings", []):
        severity = INFORMATION if f["severity"] == "P2" and f.get("disposition") else _FROM_05[f["severity"]]
        items.append(_item("Statements (Document 05)", severity, f["code"], f["message"], f["rule"], f["action"],
                           f.get("refs", ())))
    for reason in package.get("stale_reasons", []):
        items.append(_item("Workspace (Document 02)", HARD_STOP, "STALE_PACKAGE", reason, "WF-12",
                           "Rebuild the package; earlier sign-offs no longer apply."))
    schedules = result.get("schedules") or {}
    if not schedules.get("materiality"):
        items.append(_item("Workspace (Document 02)", MATERIAL_REVIEW, "MATERIALITY_UNDOCUMENTED",
                           "No documented materiality policy is recorded for this package.", "§5.1",
                           "Record the materiality basis and amount."))
    order = {HARD_STOP: 0, MATERIAL_REVIEW: 1, INFORMATION: 2}
    seen, out = set(), []
    for item in sorted(items, key=lambda i: order[i["severity"]]):
        if (item["source"], item["code"]) not in seen:
            seen.add((item["source"], item["code"]))
            out.append(item)
    return out


def state(resolution: dict | None, package: dict) -> str:
    """§7.1, derived from the upstream records."""
    result = package["result"]
    if resolution is None or resolution["state"] != "FROZEN":
        return "INCOMPLETE_SCOPE"
    if result.get("halted") == "SOURCE_UNAPPROVED":
        return "SOURCE_INTAKE"
    if package["state"] in ("INVALIDATED", "SUPERSEDED"):
        return "DRAFT_BLOCKED"
    if package["state"] == "APPROVED":
        return "APPROVED_FOR_ISSUE"
    if "preparer" in (package.get("signoffs") or {}):
        return "IN_REVIEW"
    return "PREPARER_READY" if result.get("ready_for_signoff") else "DRAFT_BLOCKED"


async def overview(db: AsyncSession, user, package_id: str) -> dict:
    package = await packages.get(db, user, package_id)
    tb = await store.detail(db, user, package["trial_balance_id"])
    resolution = await resolutions.get(db, user, package["resolution_id"]) if package["resolution_id"] else None
    result = package["result"]
    profile = result["profile"]
    items = rail(tb, resolution, package)
    current = state(resolution, package)
    counts = {s: sum(1 for i in items if i["severity"] == s) for s in (HARD_STOP, MATERIAL_REVIEW, INFORMATION)}
    release = await packages.release_check(db, user, package_id)
    misleading = misleading_reasons(result)
    res_result = (resolution or {}).get("result") or {}
    statement_rules = {s["statement"]: s for s in res_result.get("statements", [])}
    signoffs = package.get("signoffs") or {}
    tabs = [{"statement_id": s["statement_id"], "title": s["title"], "status": s["status"],
             "requiredness": s["requiredness"],
             "omission": ({"basis": statement_rules.get(s["statement_id"], {}).get("note") or s.get("note", ""),
                           "approved_by": (resolution or {}).get("approved_by"),
                           "resolution_revision": (resolution or {}).get("revision")}
                          if s["status"] in ("EXEMPT", "NOT_APPLICABLE") else None)}
            for s in result.get("statements", [])] + [{"statement_id": "notes", "title": "Notes", "status": "ASSEMBLED",
                                                        "requiredness": "REQUIRED", "omission": None}]
    if counts[HARD_STOP]:
        banner = (f"Cannot be released: {counts[HARD_STOP]} hard stop(s) and {counts[MATERIAL_REVIEW]} review item(s) "
                  f"are open. The first is: {items[0]['message']}")
    elif current == "APPROVED_FOR_ISSUE":
        banner = "Approved by all sign-offs. Statutory release still needs every gate in the release check."
    else:
        banner = f"{counts[MATERIAL_REVIEW]} review item(s) need a reviewer's disposition before sign-off."
    return {
        "package_id": package["id"], "version": package["version"], "state": current,
        "release_status": RELEASE_LABEL[current], "banner": banner, "counts": counts, "rail": items,
        "scope": {"entity": profile.get("entity"), "scope": profile.get("scope"), "report_type": profile.get("report_type"),
                  "period_start": profile.get("period_start"), "period_end": profile.get("period_end"),
                  "jurisdiction": ((resolution or {}).get("facts") or {}).get("incorporation_jurisdiction"),
                  "resolution_id": package["resolution_id"], "resolution_state": (resolution or {}).get("state")},
        "framework": {"framework": profile.get("framework"), "edition": profile.get("edition"), "layout": profile.get("family"),
                      "rules": res_result.get("rules", []), "citations": res_result.get("citations", {}),
                      "rule_pack": res_result.get("rule_pack"), "assembly_ruleset": profile.get("ruleset")},
        "source": {"trial_balance_id": tb["id"], "filename": tb["filename"], "version": tb["version"], "sha256": tb["sha256"],
                   "imported_at": tb["created_at"], "state": tb["state"],
                   "snapshot_hash": result.get("source", {}).get("snapshot_hash"),
                   "prior_trial_balance_id": package["prior_trial_balance_id"]},
        "tabs": tabs, "statements": result.get("statements", []), "notes": result.get("notes", []),
        "assertions": result.get("assertions", []),
        "review_sequence": [{"role": role, "label": label, "signed": signoffs.get(role),
                             "available": role != "publisher"} for role, label in REVIEW_SEQUENCE],
        "export": {"draft_allowed": not misleading and package["state"] not in ("INVALIDATED", "SUPERSEDED"),
                   "draft_refusal": misleading + list(package.get("stale_reasons", [])),
                   "final_allowed": release["statutory_release_allowed"], "final_reasons": release["reasons"],
                   "publish_allowed": False,
                   "publish_reason": "Publishing and filing need the publication engine (Document 06) and release "
                                     "certification (Document 07)."},
        "answers": _answers(profile, res_result, tb, result, items, signoffs, release, misleading),
    }


def _answers(profile, res_result, tb, result, items, signoffs, release, misleading) -> list[dict]:
    rules = res_result.get("rules", [])
    missing_roles = [label for role, label in REVIEW_SEQUENCE[:4] if role not in signoffs]
    blockers = [i for i in items if i["severity"] == HARD_STOP]
    return [
        {"question": "Which standards and dates apply?",
         "answer": (f"{profile.get('framework') or 'No framework is resolved'}"
                    + (f" ({profile['edition']})" if profile.get("edition") else "")
                    + (f"; {len(rules)} effective-dated rule(s) for the period starting {profile.get('period_start')}." if rules else "."))},
        {"question": "Where did every figure come from?",
         "answer": f"{tb['filename']} v{tb['version']} (sha256 {tb['sha256'][:12]}…), approved snapshot "
                   f"{(result.get('source', {}).get('snapshot_hash') or 'none')[:19]}; open any row for its accounts, mappings and journals."},
        {"question": "What is wrong, incomplete or uncertain?",
         "answer": f"{len(blockers)} hard stop(s)" + (f", first: {blockers[0]['message']}" if blockers else "; none open.")},
        {"question": "What evidence and approvals are required?",
         "answer": ("; ".join(dict.fromkeys(i["action"] for i in blockers[:3])) or "No open evidence requests")
                   + (f". Sign-offs still needed: {', '.join(missing_roles)}." if missing_roles else ". All sign-offs recorded.")},
        {"question": "What can be exported now, and with which status?",
         "answer": "A final statutory export is allowed." if release["statutory_release_allowed"]
                   else ("No export: " + " ".join(misleading)) if misleading
                   else "A watermarked draft (DRAFT — NOT FOR STATUTORY USE) only; statutory release is blocked."},
    ]


async def provenance(db: AsyncSession, user, package_id: str, statement_id: str, line_id: str) -> dict:
    """WF-10: a statement row's lineage — accounts, mappings, journals, schedule, rule and checksums."""
    package = await packages.get(db, user, package_id)
    result = package["result"]
    statement = next((s for s in result.get("statements", []) if s["statement_id"] == statement_id), None)
    line = next((l for l in (statement or {}).get("lines", []) if l["line_id"] == line_id), None)
    if line is None:
        raise NotFound("Statement line not found.")
    tb = await store.detail(db, user, package["trial_balance_id"])
    concepts = set(line.get("concepts") or ())
    accounts = []
    for m in tb["mappings"]:
        parts = [a for a in m.get("allocations") or () if a["line_id"] in concepts]
        if m.get("line_id") in concepts or parts:
            accounts.append({"account_key": m["account_key"], "account_name": m["account_name"], "balance": m["balance"],
                             "line_id": m.get("line_id"), "allocations": parts, "status": m["status"],
                             "reviewer": m.get("reviewer"), "evidence_ref": m.get("evidence_ref", ""),
                             "basis": m.get("basis", ""), "source_row": m.get("source", "")})
    journals = [{**j, "lines": [l for l in j["lines"] if l["line_id"] in concepts]} for j in tb["journals"]
                if j["review_status"] == "APPROVED" and any(l["line_id"] in concepts for l in j["lines"])]
    support = [s for s in tb["supporting"] if any(c == {"receivables_ageing": "bs.trade_receivables",
                                                       "bank_reconciliation": "bs.cash", "inventory_listing": "bs.inventories",
                                                       "fixed_asset_register": "bs.ppe"}.get(s["kind"]) for c in concepts)]
    lineage = {"line": line, "accounts": accounts, "journals": journals}
    return {
        "statement_id": statement_id, "statement_title": statement["title"], "line": line,
        "concepts": [{"line_id": c, "label": LINES[c][0] if c in LINES else c} for c in sorted(concepts)],
        "computation": ("Sum of the approved accounts mapped to "
                        + ", ".join(LINES[c][0] for c in sorted(concepts) if c in LINES)
                        + ", plus approved journals, in presentation sign.") if concepts
                       else "A subtotal or total of the lines above, computed by the layout; no account maps to it directly.",
        "accounts": accounts, "journals": journals, "supporting": support,
        "rule": {"layout": result["profile"]["family"], "edition": result["profile"].get("edition"),
                 "ruleset": result["profile"]["ruleset"]["id"]},
        "source_file": {"filename": tb["filename"], "version": tb["version"], "sha256": tb["sha256"]},
        "snapshot_hash": result.get("source", {}).get("snapshot_hash"),
        "line_checksum": "sha256:" + hashlib.sha256(json.dumps(lineage, sort_keys=True).encode()).hexdigest(),
    }


async def publish(db: AsyncSession, user, package_id: str, note: str = "") -> None:
    """Always refused here, and logged (WF-11): no text can override a hard stop or publish."""
    package = await packages.get(db, user, package_id)
    release = await packages.release_check(db, user, package_id)
    reasons = list(release["reasons"]) + ["Publishing and filing need Documents 06 and 07, which are not in service."]
    await record_event_async(db, tenant_id=user.tenant_id, event_name="financial_statements.publish_refused",
                             emitting_service="financial_statements", actor_id=user.id,
                             subject_type="report_package", subject_id=package["id"],
                             payload={"note": note[:500], "reasons": reasons[:10]})
    await db.commit()
    raise Refused("Publish refused: " + " ".join(reasons[:5]))
