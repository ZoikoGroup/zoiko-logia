"""Specification-driven internal draft boundary; no persistence or issue authority.

The caller supplies server-resolved authorised entities, never values taken from
request roles. Export, rule packs and professional approval are not implemented.
"""
from dataclasses import dataclass, field

from .pipeline import ReportDraft, build_draft
from .specification import (STATEMENT_TEMPLATES, SpecificationError, load_table,
                            validate_contract)
from .states import ReportState


@dataclass
class RequestedDraft:
    draft: ReportDraft
    facts: list[dict] = field(default_factory=list)
    template_id: str | None = None


def _unavailable(code: str, detail: str) -> RequestedDraft:
    return RequestedDraft(ReportDraft(state=ReportState.UNAVAILABLE, error_code=code, error_detail=detail))


def build_requested_draft(request: dict, ledger: dict, account_map: dict, *,
                          authorised_entity_ids: frozenset[str]) -> RequestedDraft:
    """Build only the explicitly supported synthetic, single-entity JSON draft."""
    try:
        validate_contract("report_request", request)
        templates = {row["report_id"]: row for row in load_table("report_catalog")}
    except SpecificationError as error:
        return _unavailable("request_invalid", str(error))
    template = templates.get(request["template_id"])
    if template is None:
        return _unavailable("template_unknown", "The template is not in the supplied catalogue.")
    if template["report_class"] != request["report_class"]:
        return _unavailable("report_class_mismatch", "Report class must agree with the catalogue.")
    scope = request["entity_scope"]
    if not set(scope["entity_ids"]) <= authorised_entity_ids:
        return _unavailable("entity_access_denied", "The requested entity is outside the authorised scope.")
    if request["template_id"] not in STATEMENT_TEMPLATES:
        return _unavailable("template_not_implemented", "This catalogue template has no draft compiler yet.")
    if scope["scope_type"] != "SEPARATE" or scope["entity_ids"] != [ledger.get("entity")]:
        return _unavailable("scope_unsupported", "Only one matching separate entity is supported.")
    if (request["basis"] != "SYNTHETIC" or ledger.get("metadata", {}).get("synthetic") is not True
            or request["framework"] != {"code": "MANAGEMENT_BASIS", "adoption_mode": "DEFAULT"}
            or request["period"].get("comparison", "NONE") != "NONE"):
        return _unavailable("basis_unsupported", "Only synthetic drafts without framework compliance or comparatives are supported.")
    if (request["presentation"]["currency"] != ledger.get("currency")
            or request["presentation"]["scale"] != 1 or request["outputs"] != ["JSON"]):
        return _unavailable("presentation_unsupported", "Only unscaled ledger-currency JSON facts are supported.")
    if (request["period"]["start"], request["period"]["end"]) != (ledger.get("period_start"), ledger.get("period_end")):
        return _unavailable("period_mismatch", "Request and ledger periods differ.")
    draft = build_draft(ledger, account_map)
    result = RequestedDraft(draft=draft, template_id=request["template_id"])
    if draft.state != ReportState.DRAFT_RECONCILED:
        return result
    statement = STATEMENT_TEMPLATES[request["template_id"]]
    for line in draft.compiled.statements[statement]:
        fact = draft.compiled.facts[line.fact_id]
        period = ({"instant": fact.period_end.isoformat()} if fact.context == "instant" else
                  {"start": fact.period_start.isoformat(), "end": fact.period_end.isoformat()})
        item = {"fact_id": fact.fact_id, "entity_id": ledger["entity"], "concept_id": fact.concept,
                "basis": request["basis"], "period": period, "value": format(fact.value, "f"),
                "currency": fact.currency, "source_snapshot_id": fact.snapshot_hash,
                "value_status": "ZERO" if fact.value == 0 else "PRESENT",
                "account_map_version": fact.mapping_version}
        try:
            validate_contract("financial_fact", item)
        except SpecificationError as error:
            return RequestedDraft(ReportDraft(state=ReportState.DRAFT_INCOMPLETE,
                                             error_code="fact_contract_invalid", error_detail=str(error)))
        result.facts.append(item)
    return result
