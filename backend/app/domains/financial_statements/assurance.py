"""Financial reporting assurance, professional review and release
certification (ZoikoLogia Document 07, ZL-FSR-ENG-007).

The assurance layer after Documents 03 (framework), 04 (source and
mapping) and 05 (assembly). It runs quality gates over a report package,
keeps a finding register with severity, assertion and risk domain, asks
for evidence by risk domain, aggregates uncorrected misstatements gross and
net against an approved materiality, and states plainly what was NOT
checked (the negative assertion report).

Kriton proposes and explains; it never authorises. Decisions, waivers and
attestations are made by named people under maker-checker rules, recorded
in a hash-chained ledger. The release certificate states internal quality
status and the controls actually achieved — never an audit opinion,
assurance engagement, regulator acceptance or statutory compliance (QA-012,
QA-032). Claims are drawn from a vocabulary with evidence prerequisites
(QA-031); anything outside it is refused.
"""
from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal, InvalidOperation

SEVERITIES = ("BLOCKER", "CRITICAL", "MATERIAL", "REVIEW", "ADVISORY")
BLOCKING = ("BLOCKER", "CRITICAL", "MATERIAL", "REVIEW")      # all hold QUALITY_PASSED
UNWAIVABLE = ("BLOCKER", "CRITICAL")                         # QA-018
ASSERTIONS = ("existence", "completeness", "accuracy", "cut_off", "rights_obligations", "classification",
              "presentation", "disclosure")
TECHNICAL_ROLES = ("CFO", "Controller", "Audit Partner", "Tax Director")   # may accept material judgements and waive
OFFICER_ROLES = ("CFO", "Business Owner")                                  # company director / authorised officer
RULESET = {"id": "FS-ASSURANCE-2026.10-TEST", "version": "2026.10.26", "status": "UNREVIEWED_TEST_PACK"}

_FROM_04 = {"HARD_STOP": "BLOCKER", "REVIEW": "REVIEW", "INFO": "ADVISORY"}
_FROM_05 = {"P0": "BLOCKER", "P1": "MATERIAL", "P2": "REVIEW", "P3": "ADVISORY"}
_ASSERTION_BY_CODE = (
    (re.compile(r"COMPARATIVE|MISSING|DATA_MISSING|UNDECIDED"), "completeness"),
    (re.compile(r"CLASSIFICATION|FORMAT|BORROWINGS|IFRS18"), "classification"),
    (re.compile(r"NOTE_|DISCLOSURE|UNSOURCED|ASSERTION|CLAIM"), "disclosure"),
    (re.compile(r"DIVIDEND|SHARE_CAPITAL"), "rights_obligations"),
    (re.compile(r"X-0|UNBALANCED|MISMATCH|TAX|ROLLFORWARD|CONTROL_TOTAL"), "accuracy"),
    (re.compile(r"CUTOFF"), "cut_off"),
)

# §7 risk-led review: (domain, title, trigger concepts or "always", evidence required, assertion, severity if unevidenced)
RISK_DOMAINS = (
    ("going_concern", "Going concern", "always", "Forecasts, financing agreements and board minutes to the approval date.",
     "disclosure", "BLOCKER"),
    ("subsequent_events", "Events after the reporting period", "always",
     "Board minutes and a post-period review up to the authorisation date.", "completeness", "MATERIAL"),
    ("related_parties", "Related parties", "always", "Owners, directors and intercompany register with declarations.",
     "completeness", "MATERIAL"),
    ("revenue", "Revenue", ("pl.revenue",), "Contract terms, performance obligations, cut-off, rebates and credit notes.",
     "cut_off", "MATERIAL"),
    ("tax", "Tax and deferred tax", ("pl.tax", "bs.tax_payable", "bs.deferred_tax"),
     "Tax computation, payments and the opening-to-closing roll-forward.", "accuracy", "MATERIAL"),
    ("cash_flows", "Cash", ("bs.cash",), "Bank statements and the bank reconciliation at the period end.", "existence",
     "REVIEW"),
    ("financial_instruments", "Borrowings and financial instruments", ("bs.borrowings",),
     "Loan agreements: rates, maturity, security and covenants.", "rights_obligations", "REVIEW"),
    ("impairment", "Impairment of fixed assets", ("bs.ppe", "bs.intangibles"),
     "Impairment indicators, assumptions and management approval.", "accuracy", "REVIEW"),
    ("shared_costs", "Utilities and shared costs", "shared_costs",
     "Supplier invoices, service location and cost centres behind the functional split.", "classification", "REVIEW"),
)
# Assertions a trial balance alone cannot prove (QA-040), whatever is uploaded beside it.
_TB_LIMITS = (
    "A balanced trial balance proves arithmetic only, not recognition or completeness (NB-06).",
    "Existence and rights over receivables and cash are not confirmed with third parties.",
    "Completeness of liabilities, commitments and contingencies cannot be proven from recorded balances.",
    "Valuation of assets (impairment, fair value) is not re-performed.",
)
_INSTRUCTION = re.compile(r"\b(?:ignore|waive|bypass|override|disable)\b.{0,40}\b(?:controls?|gates?|checks?|blockers?|rules?)\b|"
                          r"\bmark\b.{0,30}\b(?:approved|compliant|passed)\b", re.I)
_FORBIDDEN = re.compile(r"\b(?:audited|audit\s+opinion|assured|assurance\s+engagement|certif(?:y|ied|ication)|"
                        r"guarantee[ds]?|compl(?:y|ies|iant)\s+with|in\s+(?:full\s+)?compliance|true\s+and\s+fair|"
                        r"filed\s+with|regulator[\s-]+(?:accepted|approved)|accepted\s+by\s+(?:companies\s+house|hmrc|the\s+regulator))\b",
                        re.I)

CLAIMS = {
    "ARITHMETIC_CHECKED": "Arithmetic and reconciliations passed defined internal checks.",
    "DRAFT_SOURCE_LIMITED": "Draft based on supplied trial balance; evidence and comparatives outstanding.",
    "REVIEWED": "Reviewed by {role} for {scope} on {date}.",
    "OFFICER_APPROVED": "Approved by {officer} on {date}, subject to verified approval record.",
    "STATUTORY_COMPLIANT": "Prepared in accordance with {framework}.",
    "AUDITED": "Audited.",
    "FILED": "Submitted to {receiver}, receipt {id} dated {time}.",
}


def digest(value) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def forbidden_claims(text: str) -> list[str]:
    """Wording that implies audit, assurance, certification, compliance or filing (QA-012, QA-032, T35)."""
    return sorted({m.group(0).lower() for m in _FORBIDDEN.finditer(text or "")})


def instruction_like(text: str) -> bool:
    """Uploaded text that tries to instruct the system (QA-044, T25); it is flagged and ignored."""
    return bool(_INSTRUCTION.search(text or ""))


def _dec(value) -> Decimal | None:
    try:
        return Decimal(str(value)) if value not in (None, "") else None
    except InvalidOperation:
        return None


def _assertion(code: str) -> str:
    return next((a for pattern, a in _ASSERTION_BY_CODE if pattern.search(code)), "presentation")


def _finding(source, code, severity, message, rule, *, assertion=None, domain=None, amount=None, statements=(), action=""):
    return {"key": f"{source}:{code}", "source": source, "code": code, "severity": severity, "message": message,
            "rule": rule, "assertion": assertion or _assertion(code), "risk_domain": domain,
            "amount": None if amount is None else str(amount), "statements": list(statements), "action": action}


# ── the run ─────────────────────────────────────────────────────────────────

def evaluate(*, package: dict, tb: dict, resolution: dict | None, evidence: list[dict], materiality: dict | None,
             misstatements: list[dict]) -> dict:
    """Deterministic: the same package, evidence, materiality and misstatements give the same result."""
    result = package["result"]
    findings: list[dict] = []
    add = findings.append

    # Upstream findings keep their identity; Document 07 only maps severity (it never silently changes a regime).
    for f in tb.get("findings", []):
        add(_finding("Document 04", f["code"], _FROM_04.get(f["severity"], "ADVISORY"), f["message"], f["rule"],
                     action="Resolve in trial balance intake."))
    for m in tb.get("mappings", []):
        if m["status"] != "APPROVED":
            add(_finding("Document 04", f"CLASSIFICATION_{m['account_key']}", "BLOCKER",
                         f"{m['account_name']} is {m['status'].replace('_', ' ').lower()}.", "SD-025",
                         assertion="classification", amount=m["balance"], action="Approve the mapping with evidence."))
    if resolution is not None:
        for f in resolution["result"].get("findings", []):
            add(_finding("Document 03", f["code"], "BLOCKER", f["reason"], "QA-001", action=f["action"]))
    for f in result.get("findings", []):
        if f.get("release_only"):
            continue                    # a statutory-release gate, tested by the claim vocabulary, not a quality finding
        severity = "ADVISORY" if f["severity"] == "P2" and f.get("disposition") else _FROM_05[f["severity"]]
        add(_finding("Document 05", f["code"], severity, f["message"], f["rule"], action=f["action"]))
    for reason in package.get("stale_reasons", []):
        add(_finding("Document 07", "STALE_PACKAGE", "BLOCKER", reason, "QA-026", action="Rebuild the package and re-run."))

    # Materiality (QA-013): approved thresholds, never one universal cut-off.
    overall = _dec((materiality or {}).get("overall"))
    if not materiality or overall is None:
        add(_finding("Document 07", "MATERIALITY_NOT_APPROVED", "MATERIAL", "No approved materiality for this entity "
                     "and period; findings cannot be assessed against it.", "QA-013", assertion="presentation",
                     action="A technical accounting lead records overall, performance and trivial thresholds."))

    # Uncorrected misstatements: gross and net, never netted away (QA-014, T21).
    amounts = [_dec(m.get("amount")) or Decimal("0") for m in misstatements]
    gross, net = sum((abs(a) for a in amounts), Decimal("0")), sum(amounts, Decimal("0"))
    if overall is not None and misstatements and gross > overall:
        add(_finding("Document 07", "UNCORRECTED_MISSTATEMENTS", "MATERIAL",
                     f"Uncorrected misstatements total {gross} gross ({net} net) against overall materiality {overall}; "
                     "compensating items are not netted.", "QA-014", assertion="accuracy", amount=gross,
                     action="Correct the items or obtain a technical accounting decision."))

    # Risk-domain evidence (§7, QA-024): no generic citation to the whole trial balance.
    active = [e for e in evidence if not e.get("withdrawn_at")]
    covered = {d for e in active for d in e.get("domains", [])}
    concepts = {k for s in result.get("statements", []) for l in s.get("lines", []) for k in l.get("concepts", [])
                if l.get("amount") not in (None, "0")}
    shared = [m for m in tb.get("mappings", []) if m.get("evidence_required") and m["status"] == "APPROVED"]
    domains = []
    for key, title, trigger, needed, assertion, severity in RISK_DOMAINS:
        applies = trigger == "always" or (trigger == "shared_costs" and bool(shared)) or \
            (isinstance(trigger, tuple) and bool(concepts & set(trigger)))
        if key == "shared_costs" and shared and all(m.get("evidence_ref") for m in shared):
            covered_here = True                        # each split was approved with its own evidence (Document 04)
        else:
            covered_here = key in covered
        domains.append({"domain": key, "title": title, "applies": applies, "covered": applies and covered_here,
                        "evidence_needed": needed, "evidence_ids": [e["id"] for e in active if key in e.get("domains", [])]})
        if applies and not covered_here:
            add(_finding("Document 07", f"EVIDENCE_{key.upper()}", severity, f"{title}: no evidence is linked. Needed: {needed}",
                         "QA-024", assertion=assertion, domain=key, action="Upload the evidence and link it to this domain."))
    for e in evidence:
        if e.get("instruction_flag"):
            add(_finding("Document 07", f"INSTRUCTION_IN_EVIDENCE_{e['id'][:8]}", "ADVISORY",
                         f"'{e['filename']}' contains text that reads as an instruction to the system; it was ignored.",
                         "QA-044", assertion="presentation", action="No action: uploaded text has no authority."))
        if e.get("withdrawn_at"):
            add(_finding("Document 07", f"EVIDENCE_WITHDRAWN_{e['id'][:8]}", "REVIEW",
                         f"'{e['filename']}' was withdrawn ({e.get('withdrawn_reason') or 'no reason'}); the assertions it "
                         "supported are re-opened.", "T31", action="Replace the evidence or reassess the assertion."))

    # Quality gate matrix (§5 control 04).
    gates = _gates(result, resolution, domains, findings)
    severities = {f["severity"] for f in findings}
    return {
        "ruleset": RULESET, "findings": findings, "gates": gates, "risk_domains": domains,
        "misstatements": {"items": misstatements, "gross": str(gross), "net": str(net),
                          "overall_materiality": None if overall is None else str(overall)},
        "negative": _negative(result, resolution, domains, evidence),
        "evidence_scope": "uploaded_trial_balance_only" if not active else f"trial_balance_plus_{len(active)}_evidence_items",
        "has_blockers": bool(severities & {"BLOCKER", "CRITICAL"}),
    }


def _gates(result, resolution, domains, findings) -> list[dict]:
    gates = []
    res_state = (resolution or {}).get("state")
    gates.append({"gate_id": "QG-FRAMEWORK", "title": "Framework and scope resolved", "scope": "package",
                  "status": "PASS" if res_state == "FROZEN" else "FAIL", "method": "Document 03 resolution state",
                  "source": f"resolution {(resolution or {}).get('id', 'none')}"})
    gates.append({"gate_id": "QG-SOURCE", "title": "Approved source snapshot", "scope": "package",
                  "status": "FAIL" if result.get("halted") else "PASS", "method": "Document 04 snapshot hash",
                  "source": result.get("source", {}).get("snapshot_hash") or "none"})
    for s in result.get("statements", []):
        status = {"ASSEMBLED": "PASS", "EXEMPT": "PASS", "NOT_APPLICABLE": "NOT_APPLICABLE"}.get(s["status"], "FAIL")
        gates.append({"gate_id": f"QG-STMT-{s['statement_id']}", "title": s["title"], "scope": "statement",
                      "status": status, "method": "Document 05 assembly from approved concepts",
                      "source": s.get("layout", "")})
    for a in result.get("assertions", []):
        status = {"PASS": "PASS", "FAIL": "FAIL", "EXEMPT": "PASS", "NOT_APPLICABLE": "NOT_APPLICABLE"}.get(a["status"], "CANNOT_VERIFY")
        gates.append({"gate_id": f"QG-{a['assertion_id']}", "title": a["title"], "scope": "cross-statement",
                      "status": status, "method": a["formula"], "source": "Document 05 reconciler"})
    for n in result.get("notes", []):
        status = "PASS" if n["state"] in ("SUPPORTED", "NOT_APPLICABLE", "EXEMPT") else "FAIL"
        gates.append({"gate_id": f"QG-NOTE-{n['requirement_id']}", "title": n["title"], "scope": "disclosure",
                      "status": status, "method": n["rule"], "source": n.get("evidence_ref") or "no evidence"})
    for d in domains:
        if d["applies"]:
            gates.append({"gate_id": f"QG-RISK-{d['domain']}", "title": d["title"], "scope": "evidence",
                          "status": "PASS" if d["covered"] else "CANNOT_VERIFY", "method": "Linked evidence (QA-024)",
                          "source": ", ".join(d["evidence_ids"]) or "none"})
    gates.append({"gate_id": "QG-MATERIALITY", "title": "Materiality approved", "scope": "package",
                  "status": "FAIL" if any(f["code"] == "MATERIALITY_NOT_APPROVED" for f in findings) else "PASS",
                  "method": "QA-013", "source": "materiality record"})
    return gates


def _negative(result, resolution, domains, evidence) -> dict:
    """What was not checked, missing, waived or assumed (QA-040, §1 Negative Assertion Report)."""
    res_result = (resolution or {}).get("result") or {}
    untested = list(_TB_LIMITS) + [f"{d['title']}: {d['evidence_needed']}" for d in domains if d["applies"] and not d["covered"]]
    missing = [f["message"] for f in result.get("findings", []) if f["code"] in ("COMPARATIVES_MISSING", "CASH_FLOW_DATA_MISSING")
               or f["code"].startswith("NOTE_MISSING")]
    assumptions = [f["message"] for f in result.get("findings", []) if f["code"] in
                   ("BORROWINGS_MATURITY_MISSING", "SHARE_CAPITAL_OPENING_UNEVIDENCED")]
    if res_result.get("rule_pack", {}).get("status") != "REVIEWED":
        assumptions.append("The framework rule pack and the assembly rule set are unreviewed test packs.")
    return {"unresolved_scope": [f["reason"] for f in res_result.get("findings", [])] or
                                ([] if resolution else ["No framework resolution is attached."]),
            "missing_data": missing, "untested_assertions": untested, "contingent_assumptions": assumptions,
            "withdrawn_evidence": [e["filename"] for e in evidence if e.get("withdrawn_at")],
            "outside_scope": ["External audit or independent review (not performed by ZoikoLogia).",
                              "Regulator filing and acceptance (no filer is integrated)."]}


# ── register, status and claims ─────────────────────────────────────────────

def merge_register(findings: list[dict], register: dict) -> tuple[list[dict], dict]:
    """Attach recorded states; a finding that no longer arises is closed by the re-run, never deleted (QA-036)."""
    out, keys = [], set()
    for f in findings:
        keys.add(f["key"])
        entry = register.get(f["key"]) or {}
        state = entry.get("state", "OPEN")
        if state == "CLOSED_BY_RERUN":
            state = "OPEN"                                   # it has come back
        out.append({**f, "state": state, "decisions": entry.get("decisions", []), "waiver": entry.get("waiver")})
    updated = dict(register)
    for key, entry in register.items():
        if key not in keys and entry.get("state") not in ("CLOSED_BY_RERUN", "WITHDRAWN"):
            updated[key] = {**entry, "state": "CLOSED_BY_RERUN"}
    closed = [{"key": k, **v} for k, v in updated.items() if k not in keys]
    return out, {"closed": closed, "register": updated}


def open_items(findings: list[dict], today: str) -> list[dict]:
    """Findings still holding the release; an expired waiver re-opens its finding."""
    def held(f):
        if f["state"] == "WAIVED" and (f.get("waiver") or {}).get("expires", "") < today:
            return True
        return f["state"] in ("OPEN", "ESCALATED") and f["severity"] in BLOCKING
    return [f for f in findings if held(f)]


def status(*, ingested: bool, scope_resolved: bool, open_: list[dict], attestations: dict, released: bool,
           superseded: bool) -> str:
    """§8 state machine, from the records."""
    if superseded:
        return "SUPERSEDED"
    if released:
        return "RELEASED"
    if not ingested or not scope_resolved:
        return "INGESTED"
    if open_:
        return "FINDINGS_OPEN"
    if "officer" in attestations:
        return "AUTHORIZED"
    if "independent_reviewer" in attestations:
        return "REVIEW_APPROVED"
    return "QUALITY_PASSED"


def claims(*, result: dict, resolution: dict | None, findings: list[dict], open_: list[dict], attestations: dict) -> list[dict]:
    """The claim vocabulary with each prerequisite tested (QA-031)."""
    assertions_ok = all(a["status"] in ("PASS", "EXEMPT", "NOT_APPLICABLE") for a in result.get("assertions", [])) \
        and bool(result.get("assertions"))
    reviewer, officer = attestations.get("independent_reviewer"), attestations.get("officer")
    res_result = (resolution or {}).get("result") or {}
    strong = all(a.get("auth_aal") == "aal2" for a in attestations.values()) and bool(attestations)
    statutory_reasons = [r for r, bad in (
        ("the framework resolution does not permit a statutory claim", not res_result.get("permit_statutory_claim")),
        ("quality findings are open", bool(open_)),
        ("the independent reviewer and the authorised officer have not both attested", not (reviewer and officer)),
        ("an attestation was made without strong (MFA) authentication", not strong),
        ("the assurance rule set is an unreviewed test pack", RULESET["status"] != "REVIEWED")) if bad]
    rows = [
        ("ARITHMETIC_CHECKED", assertions_ok, [] if assertions_ok else ["a cross-statement check failed or was not evaluated"], {}),
        ("DRAFT_SOURCE_LIMITED", True, [], {}),
        ("REVIEWED", bool(reviewer), [] if reviewer else ["no independent reviewer attestation"],
         {"role": "independent reviewer", "scope": (reviewer or {}).get("scope", ""), "date": (reviewer or {}).get("at", "")[:10]}),
        ("OFFICER_APPROVED", bool(officer and officer.get("approval_evidence_id")),
         [] if officer and officer.get("approval_evidence_id") else ["no authorised officer approval with an approval record"],
         {"officer": (officer or {}).get("by", ""), "date": (officer or {}).get("at", "")[:10]}),
        ("STATUTORY_COMPLIANT", not statutory_reasons, statutory_reasons, {"framework": res_result.get("framework_edition") or ""}),
        ("AUDITED", False, ["ZoikoLogia does not perform audits; no authentic external auditor's report is verified"], {}),
        ("FILED", False, ["no regulator filer is integrated, so no real receipt exists"], {}),
    ]
    return [{"claim": c, "allowed": ok, "text": CLAIMS[c].format(**fields) if ok and fields else CLAIMS[c] if ok else None,
             "missing": missing} for c, ok, missing, fields in rows]


def control_statement(*, package: dict, resolution: dict | None, state: str, open_: list[dict], claim_rows: list[dict],
                      evidence_scope: str) -> dict:
    """The machine-readable control statement (§11 sample)."""
    allowed = {c["claim"]: c["allowed"] for c in claim_rows}
    return {"package_id": package["id"], "package_version": package["version"],
            "framework": ((resolution or {}).get("result") or {}).get("selected_framework"),
            "status": "BLOCKED" if open_ else state, "is_external_audit": False, "evidence_scope": evidence_scope,
            "blockers": [f["code"].lower() for f in open_ if f["severity"] in ("BLOCKER", "CRITICAL")],
            "can_claim_statutory_compliance": allowed["STATUTORY_COMPLIANT"], "can_issue_as_audited": False}


def summary_text(view: dict) -> str:
    """Human-readable findings and limitations (QA-045), exported beside the machine-readable metadata."""
    lines = [f"Assurance run {view['id']} — package {view['package_id']} v{view['package_version']}",
             f"Status: {view['status']} (internal quality status; not an audit opinion or a statutory compliance certificate)",
             f"Evidence scope: {view['result']['evidence_scope']}", "", "Open findings:"]
    lines += [f"  [{f['severity']}] {f['code']}: {f['message']}" for f in view["open"]] or ["  none"]
    lines += ["", "Not checked / limitations:"]
    negative = view["result"]["negative"]
    for key in ("unresolved_scope", "missing_data", "untested_assertions", "contingent_assumptions", "outside_scope"):
        lines += [f"  - {item}" for item in negative.get(key, [])]
    lines += ["", "Claims:"] + [f"  {c['claim']}: {'allowed — ' + c['text'] if c['allowed'] else 'not allowed (' + '; '.join(c['missing']) + ')'}"
                                for c in view["claims"]]
    return "\n".join(lines) + "\n"
