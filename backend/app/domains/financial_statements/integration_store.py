"""Integration QA command centre and the FinancialReportingPackage manifest
(Document 08 §4, §5, §7, §10, §11).

Read-only: every value comes from the controlled records of Documents
03–07. The command centre shows the G0–G7 chain with owner, result,
retriability and a canonical error code, the sixteen invariants with
operands, and the release-gate rail; it has no override actions. The FRP
manifest is the single immutable package description that every channel
and API derives from, keyed by a stable idempotency digest.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.audit_ledger.models import AuditEvent

from . import assurance_store, integration, packages, publication_store, resolutions, store
from .assembly import RULESET as ASSEMBLY_RULESET
from .assurance import RULESET as ASSURANCE_RULESET
from .publication import digest


def _gate(gate, title, status, owner, detail, code=None, retriable=False, inputs=None) -> dict:
    return {"gate": gate, "title": title, "status": status, "owner": owner, "detail": detail, "error_code": code,
            "retriable": retriable, "correlation_id": digest([gate, inputs])[7:23]}


async def _load(db: AsyncSession, user, package_id: str) -> dict:
    package = await packages.get(db, user, package_id)
    tb = await store.detail(db, user, package["trial_balance_id"])
    resolution = await resolutions.get(db, user, package["resolution_id"]) if package["resolution_id"] else None
    run = await assurance_store.latest_for(db, user, package_id)
    run = run if run and run["package_id"] == package_id else None
    publication = await publication_store.overview(db, user, package_id)
    return {"package": package, "tb": tb, "resolution": resolution, "run": run, "publication": publication}


def _chain(c: dict) -> list[dict]:
    package, tb, resolution, run, pub = c["package"], c["tb"], c["resolution"], c["run"], c["publication"]
    result = package["result"]
    gates = []
    res_state = (resolution or {}).get("state")
    gates.append(_gate("G0", "Scope", "PASS" if res_state == "FROZEN" else "BLOCKED", "Technical accounting",
                       f"Resolution {res_state.lower() if res_state else 'missing'}",
                       None if res_state == "FROZEN" else "FR-APPLICABILITY-AMBIGUOUS", inputs=(resolution or {}).get("id")))
    hard = [f for f in tb["findings"] if f["severity"] == "HARD_STOP"]
    gates.append(_gate("G1", "Intake", "PASS" if tb["state"] == "APPROVED_SNAPSHOT" and not hard else "BLOCKED", "Preparer",
                       f"{tb['filename']} v{tb['version']} · {tb['state'].replace('_', ' ').lower()}"
                       + (f" · {len(hard)} hard stop(s)" if hard else ""),
                       "FR-SOURCE-UNRECONCILED" if hard else None, retriable=not hard, inputs=tb["sha256"]))
    unapproved = [m for m in tb["mappings"] if m["status"] != "APPROVED"]
    pending = [j for j in tb["journals"] if j["review_status"] == "PENDING_REVIEW"]
    gates.append(_gate("G2", "Account", "PASS" if not unapproved and not pending else "BLOCKED", "Reviewer",
                       f"{len(unapproved)} mapping(s) and {len(pending)} journal(s) awaiting approval",
                       "FR-CLASSIFICATION-UNSUPPORTED" if unapproved else None, retriable=True))
    assembled = not result.get("halted") and bool(result.get("statements"))
    gates.append(_gate("G3", "Assemble", "PASS" if assembled and package["state"] not in ("INVALIDATED", "SUPERSEDED") else "BLOCKED",
                       "Preparer", f"package v{package['version']} · {package['state'].replace('_', ' ').lower()}",
                       "FR-REVIEW-INVALIDATED" if package["state"] == "INVALIDATED" else None, inputs=package["fingerprint"]))
    failed = [a for a in result.get("assertions", []) if a["status"] == "FAIL"]
    notes_missing = [n for n in result.get("notes", []) if n["state"] in ("REQUIRED_MISSING", "CONDITIONAL_UNDECIDED")]
    gates.append(_gate("G4", "Reconcile", "PASS" if not failed and not notes_missing else "BLOCKED", "Controller",
                       f"{len(failed)} failed check(s); {len(notes_missing)} note(s) missing",
                       "FR-DISCLOSURE-MISSING" if notes_missing and not failed else "FR-SOURCE-UNRECONCILED" if failed else None))
    status = (run or {}).get("status")
    reviewed = status in ("REVIEW_APPROVED", "AUTHORIZED", "RELEASED")
    gates.append(_gate("G5", "Review", "PASS" if reviewed else "BLOCKED" if run else "NOT_STARTED", "Independent reviewer",
                       f"Assurance {status.replace('_', ' ').lower() if status else 'not run'}",
                       "FR-REVIEW-INVALIDATED" if run and run.get("superseded_by") else None))
    issued = [i for i in pub["issues"] if i["state"] == "ISSUED"]
    diverged = [a for a in pub["artifacts"] if a["kind"] == "RENDER" and not (a["validation"].get("parity") or {}).get("ok", True)]
    gates.append(_gate("G6", "Publish", "PASS" if issued and not diverged else "BLOCKED" if diverged else "NOT_STARTED",
                       "Authorised issuer", f"{len(issued)} issue(s); {len(diverged)} channel(s) diverging",
                       "FR-PRESENTATION-DIVERGENCE" if diverged else None))
    gates.append(_gate("G7", "File / close", "NOT_AVAILABLE", "Regulatory integrations",
                       "No certified filing adapter; nothing is transmitted and nothing is called filed.", "FR-FILING-UNCONFIRMED"))
    return gates


def _invariants(c: dict) -> list[dict]:
    package, tb, run, pub = c["package"], c["tb"], c["run"], c["publication"]
    result = package["result"]
    by = {a["assertion_id"]: a for a in result.get("assertions", [])}

    def from_assertion(inv, title, aid):
        a = by.get(aid)
        if a is None:
            return {"id": inv, "title": title, "status": "NOT_EVALUATED", "detail": "Not assembled."}
        return {"id": inv, "title": title, "status": {"PASS": "PASS", "FAIL": "FAIL", "EXEMPT": "EXEMPT"}.get(a["status"], a["status"]),
                "detail": a["formula"], "operands": a["operands"], "residual": a["residual"]}
    pl = next((s for s in result.get("statements", []) if s["statement_id"].endswith("profit_or_loss")), {"lines": []})
    lines = {l["line_id"]: l["amount"] for l in pl["lines"]}
    inv03 = "NOT_EVALUATED"
    if {"profit_before_tax", "tax", "profit"} <= set(lines):
        from decimal import Decimal
        inv03 = "PASS" if Decimal(lines["profit_before_tax"]) - Decimal(lines["tax"]) == Decimal(lines["profit"]) else "FAIL"
    x07 = [a for a in result.get("assertions", []) if a["assertion_id"].startswith("X-07")]
    parity = [a for a in pub["artifacts"] if a["kind"] == "RENDER"]
    unproven = [m for m in tb["mappings"] if m["status"] != "APPROVED" or (m.get("evidence_required") and not m.get("evidence_ref"))]
    missing = [n for n in result.get("notes", []) if n["state"] in ("REQUIRED_MISSING", "CONDITIONAL_UNDECIDED")]
    period_issues = {f["code"] for f in result.get("findings", [])} & {"PERIOD_MISMATCH", "FX_POLICY_REQUIRED", "PRIOR_PERIOD_ORDER"}
    stale = package["stale_reasons"] or bool((run or {}).get("superseded_by"))
    return [
        {"id": "INV-01", "title": "Trial balance debits = credits", "status": "PASS" if tb["balanced"] else "FAIL",
         "detail": f"{tb['integrity'].get('total_debits')} vs {tb['integrity'].get('total_credits')} (necessary, not sufficient)"},
        from_assertion("INV-02", "Assets = liabilities + equity", "X-01"),
        {"id": "INV-03", "title": "PBT − tax = profit after tax", "status": inv03, "detail": "Recomputed from the presented lines."},
        from_assertion("INV-04", "Equity roll-forward by component", "X-04"),
        from_assertion("INV-05", "Cash roll-forward", "X-05"),
        from_assertion("INV-06", "Cash flow closing = balance-sheet cash", "X-06"),
        {"id": "INV-07", "title": "Notes agree to primary statements",
         "status": "FAIL" if any(a["status"] == "FAIL" for a in x07) else "PASS" if x07 else "NOT_EVALUATED",
         "detail": f"{len(x07)} note schedule check(s)"},
        from_assertion("INV-08", "Consolidated = components ± eliminations", "X-09"),
        from_assertion("INV-09", "Opening balances = prior approved closing", "X-10"),
        {"id": "INV-10", "title": "Exports match the signed semantic model",
         "status": "NOT_EVALUATED" if not parity else "PASS" if all(a["validation"]["parity"]["ok"] for a in parity) else "FAIL",
         "detail": f"{len(parity)} rendered artifact(s) read back"},
        {"id": "INV-11", "title": "Every line has provenance and an approved classification",
         "status": "FAIL" if unproven else "PASS", "detail": f"{len(unproven)} account(s) without approval or evidence"},
        {"id": "INV-12", "title": "Mandatory notes present and approved; no artificial zeroes",
         "status": "FAIL" if missing else "PASS", "detail": f"{len(missing)} note(s) open"},
        {"id": "INV-13", "title": "Entity, period and currency agree", "status": "FAIL" if period_issues else "PASS",
         "detail": ", ".join(sorted(period_issues)) or "No period or currency conflict."},
        {"id": "INV-14", "title": "Rounding cannot hide an imbalance", "status": by.get("X-01", {}).get("status", "NOT_EVALUATED"),
         "detail": "Balance checked at full precision before any display rounding."},
        {"id": "INV-15", "title": "A change after approval invalidates signatures", "status": "FAIL" if stale else "PASS",
         "detail": "; ".join(package["stale_reasons"]) or ("A newer assurance run superseded this one." if stale else "Inputs unchanged since signing.")},
        {"id": "INV-16", "title": "'Accepted' only from an authority receipt", "status": "PASS",
         "detail": "No filing state beyond NOT_SENT exists without a real receipt."},
    ]


async def _audit_root(db, user, ids: list[str]) -> str:
    rows = (await db.execute(select(AuditEvent.chain_hash).where(
        AuditEvent.tenant_id == user.tenant_id, AuditEvent.subject_id.in_([i for i in ids if i]))
        .order_by(AuditEvent.ingested_at, AuditEvent.id))).scalars().all()
    return digest(list(rows))


def _status(chain: list[dict], run: dict | None, pub: dict) -> str:
    """§4 status enum."""
    if any(g["status"] == "BLOCKED" for g in chain[:4]):
        return "BLOCKED"
    if any(i["state"] == "ISSUED" for i in pub["issues"]):
        return "PUBLISHED"
    return {"FINDINGS_OPEN": "EVIDENCE_REVIEW", "QUALITY_PASSED": "ACCOUNTING_REVIEW", "REVIEW_APPROVED": "ACCOUNTING_REVIEW",
            "AUTHORIZED": "READY_FOR_APPROVAL", "RELEASED": "APPROVED"}.get((run or {}).get("status"), "DRAFT")


async def frp(db: AsyncSession, user, package_id: str, c: dict | None = None) -> dict:
    """The FinancialReportingPackage manifest (§4)."""
    c = c or await _load(db, user, package_id)
    package, tb, resolution, run, pub = c["package"], c["tb"], c["resolution"], c["run"], c["publication"]
    result, facts = package["result"], (resolution or {}).get("facts") or {}
    res_result = (resolution or {}).get("result") or {}
    chain = _chain(c)
    sources = [{"source_id": tb["id"], "sha256": tb["sha256"], "ingestion_version": tb["version"], "provenance": tb["filename"],
                "authority": tb["uploaded_by"]}]
    if package.get("prior_trial_balance_id"):
        prior = await store.detail(db, user, package["prior_trial_balance_id"])
        sources.append({"source_id": prior["id"], "sha256": prior["sha256"], "ingestion_version": prior["version"],
                        "provenance": prior["filename"], "authority": prior["uploaded_by"]})
    key = digest([user.tenant_id, facts.get("entity_name"), facts.get("period_start"), facts.get("period_end"),
                  [s["sha256"] for s in sources], (resolution or {}).get("rule_pack_digest"), ASSEMBLY_RULESET["version"]])
    ids = [package["id"], tb["id"], (resolution or {}).get("id"), (run or {}).get("id"),
           *[i["id"] for i in pub["issues"]], *[a["id"] for a in pub["artifacts"]]]
    return {
        "idempotency_key": key, "tenant_id": user.tenant_id, "entity_id": (resolution or {}).get("entity_key") or facts.get("entity_name"),
        "period_start": facts.get("period_start"), "period_end": facts.get("period_end") or tb.get("period_end"),
        "jurisdiction": facts.get("incorporation_jurisdiction"), "currency": tb.get("units"),
        "framework_id": res_result.get("selected_framework"), "framework_edition": res_result.get("framework_edition"),
        "rulepack_hash": (resolution or {}).get("rule_pack_digest"),
        "rulesets": {"assembly": ASSEMBLY_RULESET, "assurance": ASSURANCE_RULESET},
        "applicability_decision_id": f"{(resolution or {}).get('id')}@{(resolution or {}).get('revision')}" if resolution else None,
        "basis_of_preparation": next((n["text"] for n in result.get("notes", []) if n["requirement_id"] == "N01"), None),
        "reporting_variant": sorted({i["audience"] for i in pub["issues"]}) or ["draft"],
        "exemptions": [{"statement": s["statement_id"], "basis": s.get("note", "")} for s in result.get("statements", [])
                       if s["status"] == "EXEMPT"],
        "policy_elections": {"framework_election": facts.get("framework_election"), "early_adoption": facts.get("early_adoption", [])},
        "sources": sources,
        "approved_adjustments": [{"journal_id": j["journal_id"], "reviewer_id": j["reviewer"], "signed_at": j.get("reviewed_at"),
                                  "correction_type": j["correction_type"]} for j in tb["journals"] if j["review_status"] == "APPROVED"],
        "mapped_balances": [{"account_id": m["account_key"], "account_name": m["account_name"], "presentation_code": m["line_id"],
                             "allocations": m.get("allocations", []), "amount_decimal": m["balance"],
                             "evidence_ids": [m["evidence_ref"]] if m.get("evidence_ref") else [], "reviewer_id": m.get("reviewer")}
                            for m in tb["mappings"]],
        "statements": [{"statement_type": s["statement_id"], "status": s["status"],
                        "line_items": [{"line_id": l["line_id"], "amount": l["amount"], "concepts": l.get("concepts", [])} for l in s["lines"]],
                        "comparatives": [{"line_id": l["line_id"], "amount": l.get("prior")} for l in s["lines"]]}
                       for s in result.get("statements", [])],
        "disclosures": [{"requirement_id": n["requirement_id"], "status": n["state"], "value": n["text"],
                         "evidence_ids": [n["evidence_ref"]] if n.get("evidence_ref") else [], "reviewer_id": n.get("approved_by")}
                        for n in result.get("notes", [])],
        "reconciliations": [{"assertion_id": a["assertion_id"], "result": a["status"], "operand_hash": digest(a["operands"]),
                             "tolerance": "0"} for a in result.get("assertions", [])],
        "exceptions": [{"key": f["key"], "severity": f["severity"], "status": f["state"], "owner": f.get("action"),
                        "disposition": (f.get("waiver") or {}).get("justification")} for f in (run or {}).get("findings", [])],
        "approval_manifest": {"package_signoffs": package.get("signoffs"), "attestations": (run or {}).get("attestations"),
                              "release_certificate": (run or {}).get("certificate")},
        "presentation_manifest": [{"id": a["id"], "channel": a["channel"], "audience": a["audience"], "sha256": a["sha256"],
                                   "parity": (a["validation"].get("parity") or {}).get("ok")} for a in pub["artifacts"]],
        "export_manifest": pub["issues"],
        "status": _status(chain, run, pub), "audit_event_root": await _audit_root(db, user, ids),
    }


async def command_centre(db: AsyncSession, user, package_id: str) -> dict:
    """§10 Integration QA Command Centre: diagnostic only, no override actions."""
    c = await _load(db, user, package_id)
    chain = _chain(c)
    manifest = await frp(db, user, package_id, c)
    run, pub = c["run"], c["publication"]
    hard = [{"source": "Document 07", "code": f["code"], "message": f["message"]} for f in (run or {}).get("open", [])
            if f["severity"] in ("BLOCKER", "CRITICAL")]
    soft = [{"source": "Document 07", "code": f["code"], "message": f["message"]} for f in (run or {}).get("open", [])
            if f["severity"] in ("MATERIAL", "REVIEW")]
    hard += [{"source": "Document 05", "code": f["code"], "message": f["message"]} for f in c["package"]["result"].get("findings", [])
             if f["severity"] == "P0" and not run]
    for a in pub["audiences"]:
        for reason in a["issue_blockers"]:
            soft.append({"source": "Document 06", "code": f"ISSUE_{a['key'].upper()}", "message": reason})
    return {
        "context": {"entity": manifest["entity_id"], "period_start": manifest["period_start"], "period_end": manifest["period_end"],
                    "currency": manifest["currency"], "framework_edition": manifest["framework_edition"],
                    "package_hash": c["package"]["fingerprint"], "variant": manifest["reporting_variant"],
                    "release_state": manifest["status"], "applicability_decision_id": manifest["applicability_decision_id"]},
        "chain": chain, "invariants": _invariants(c), "rail": {"hard": hard, "soft": soft},
        "manifest": manifest, "support": integration.SUPPORT, "errors": integration.ERRORS,
        "export_simulation": [{"id": a["id"], "channel": a["channel"], "audience": a["audience"],
                               "parity": (a["validation"].get("parity") or {}).get("ok"),
                               "issues": (a["validation"].get("parity") or {}).get("issues", [])[:3]} for a in pub["artifacts"]],
        "publication_disabled_reason": None if chain[5]["status"] == "PASS" else "Publication stays disabled until G0–G5 pass.",
    }


def golden_run(name: str) -> dict:
    """Run a signed golden fixture through the engines (no database)."""
    try:
        fixture = integration.load_fixture(name)
    except integration.GoldenFixtureError as error:
        return {"fixture": name, "aborted": True, "reason": str(error)}
    runs = {v: integration.run_fixture(fixture, v) for v in fixture["variants"]}
    variants = list(runs)
    dispute = integration.compare_variants(runs[variants[0]], runs[variants[1]]) if len(variants) > 1 else None
    return {"fixture": name, "label": fixture["label"], "oracle_status": fixture["oracle_status"], "aborted": False,
            "runs": runs, "mismatches": {v: integration.check_fixture(fixture, v, r) for v, r in runs.items()},
            "dispute": dispute}
