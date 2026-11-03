"""Global Source Registry, Stage S4 (shadow; off unless KRITON_REGISTRY_SHADOW).

For each part the Task Contract says needs an official figure or rule, the
sources the registry (backend/registry/global_source_registry.json) would
select by country, fact type, topic and period, beside what retrieval selects
today (the requirement's fixed pages, connector and search domains). Logged
on kriton.task_contract (stage "registry"); a JSON-lines file only when the
flag is on. Nothing reads the selection, so answers are unchanged. No model,
network or database call is made.

Selection, from the registry's own metadata only:
- an entry serves a part when its countries include one of the part's (or
  GLOBAL), its fact types include the part's, its topics meet the part's
  (an entry or part with no classified topic is not excluded on topic), and
  it is in use (library entries also need an approved version that counts
  for coverage);
- an entry with subjects (VAT, corporation tax, Bank Rate…; S4b) serves
  only a part that names one of them (source_registry.subjects_of);
- a secondary connector (the OECD tax database) is listed, never the tier;
- an entry whose period is current, live or as published is not taken to
  serve a year, a before/after date, a range or a historical question: it is
  listed under period_unconfirmed instead;
- the tier is the best kind selected: fixed page > connector > library >
  search only > none (the coverage matrix tiers).
Registered is not retrieved: this records what the registry holds, not what
was fetched or whether the figure was found (task_contract.record_retrieved).
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("kriton.task_contract")
_LOG_FILE = Path(__file__).resolve().parents[2] / "logs" / "registry-shadow.jsonl"

_TIERS = ("fixed_page", "connector", "library", "search_only", "none")
_DATED = {"year", "before", "after", "range", "historical"}
_UNDATED = {"current", "live", "as_published"}
# Today's connector names (task_contract._connector) and the registry entry
# that is the same source.
_CONNECTOR_IDS = {"exchange_rate": "connector:find_rate", "bank_of_england": "connector:find_bank_rate",
                  "hmrc_vat_registration": "page:hmrc-register-for-vat"}


def shadow_enabled() -> bool:
    return os.getenv("KRITON_REGISTRY_SHADOW", "").strip().lower() in {"1", "true", "yes", "on"}


def entries() -> tuple[dict, ...]:
    from app.orchestration.source_registry import entries as registry_entries
    return registry_entries()


class RegistrySelection(BaseModel):
    model_config = ConfigDict(frozen=True)

    part: str
    fact_type: str
    jurisdictions: list[str] = Field(default_factory=list)
    tier: str = "none"
    fixed_pages: list[str] = Field(default_factory=list)
    connectors: list[str] = Field(default_factory=list)
    # Secondary sources (OECD tax database): listed, never the tier.
    secondary_connectors: list[str] = Field(default_factory=list)
    subjects: list[str] = Field(default_factory=list)
    library: list[str] = Field(default_factory=list)
    search_domains: list[str] = Field(default_factory=list)
    period_unconfirmed: list[str] = Field(default_factory=list)
    # Today's selection, as the requirement records it.
    today_pages: list[str] = Field(default_factory=list)
    today_connector: Optional[str] = None
    today_domains: list[str] = Field(default_factory=list)
    # The comparison.
    pages_agree: bool = True
    pages_registry_only: list[str] = Field(default_factory=list)
    pages_today_only: list[str] = Field(default_factory=list)
    connector_agrees: bool = True
    domains_registry_only: list[str] = Field(default_factory=list)
    domains_today_only: list[str] = Field(default_factory=list)


def _fact(requirement) -> str:
    return "fx_rate" if requirement.connector == "exchange_rate" else requirement.fact_type


def _serves(entry: dict, countries: set[str], fact: str, topics: set[str], subjects: set[str]) -> bool:
    if entry.get("status") != "in_use" or entry.get("counts_for_coverage") is False:
        return False
    if entry["kind"] == "library" and not entry.get("approved_versions"):
        return False
    if not (set(entry.get("countries") or ()) & (countries | {"GLOBAL"})):
        return False
    if fact not in (entry.get("fact_types") or ()):
        return False
    held = set(entry.get("topics") or ()) - {"unclassified"}
    if held and topics and not held & topics:
        return False
    # S4b: an entry about named subjects (VAT, corporation tax, Bank Rate)
    # serves only a part that names one of them.
    named = set(entry.get("subjects") or ())
    return not named or bool(named & subjects)


def select(requirement) -> RegistrySelection:
    """What the registry would select for one requirement, beside today's."""
    countries, fact = set(requirement.jurisdictions), _fact(requirement)
    topics = set(requirement.topics) - {"unclassified"}
    from app.orchestration.source_registry import subjects_of
    subjects = set(subjects_of(requirement.part)) | ({"fx"} if fact == "fx_rate" else set())
    dated = requirement.period.kind in _DATED
    pages, connectors, secondary, library, domains, unconfirmed = [], [], [], [], set(), []
    for entry in entries():
        if not _serves(entry, countries, fact, topics, subjects):
            continue
        if dated and (entry.get("period") or {}).get("kind") in _UNDATED and entry["kind"] != "search_scope":
            unconfirmed.append(entry["id"])
            continue
        kind = entry["kind"]
        if kind == "fixed_page":
            pages.append(entry["url"])
        elif kind == "connector":
            (secondary if entry.get("authority_level") == "secondary" else connectors).append(entry["id"])
        elif kind == "library":
            library.append(entry["id"])
        elif kind == "search_scope":
            domains.update(entry.get("domains") or ())
    tier = ("fixed_page" if pages else "connector" if connectors else "library" if library
            else "search_only" if domains else "none")

    today_pages = [url for _, url in requirement.official_pages]
    connector_id = _CONNECTOR_IDS.get(requirement.connector) if requirement.connector else None
    # A connector today that the registry holds as a fixed page (HMRC VAT
    # registration) agrees when that page is selected.
    connector_agrees = connector_id is None or connector_id in connectors or any(
        entry["id"] == connector_id and entry.get("url") in pages for entry in entries())
    today_domains = set(requirement.official_domains)
    return RegistrySelection(
        part=requirement.part[:200], fact_type=fact, jurisdictions=list(requirement.jurisdictions), tier=tier,
        fixed_pages=pages, connectors=connectors, secondary_connectors=secondary, subjects=sorted(subjects), library=library, search_domains=sorted(domains),
        period_unconfirmed=unconfirmed, today_pages=today_pages, today_connector=requirement.connector,
        today_domains=sorted(today_domains), pages_agree=set(pages) == set(today_pages),
        pages_registry_only=sorted(set(pages) - set(today_pages)), pages_today_only=sorted(set(today_pages) - set(pages)),
        connector_agrees=connector_agrees, domains_registry_only=sorted(domains - today_domains),
        domains_today_only=sorted(today_domains - domains))


def selections(contract) -> list[RegistrySelection]:
    if contract is None:
        return []
    return [select(r) for r in contract.retrieval if r.needs_official]


def record(contract, *, query_id: str) -> None:
    """Log the registry's selection beside today's. Off unless the flag is
    on; never raises and never reaches the request."""
    if not shadow_enabled():
        return
    try:
        chosen = [s.model_dump() for s in selections(contract)]
        if not chosen:
            return
        logger.info("Task contract query=%s stage=registry %s", query_id, json.dumps(chosen, default=str))
        _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _LOG_FILE.open("a") as handle:
            handle.write(json.dumps({"query_id": query_id, "stage": "registry", "selections": chosen}, default=str) + "\n")
    except Exception:  # noqa: BLE001
        logger.warning("registry_shadow_failed", extra={"query_id": query_id})
