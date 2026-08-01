"""Public Cellar knowledge-graph search for official EU legal metadata."""
from __future__ import annotations

from datetime import datetime, timezone

import httpx

from app.core.config import get_settings
from app.domains.live_sources.connectors.evidence_base import EvidenceSearchConnector
from app.domains.live_sources.evidence_schemas import EvidenceRecord, EvidenceSearchIntent, EvidenceSearchResponse


def _sparql_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\r", " ").replace("\n", " ")


_ENGLISH = "<http://publications.europa.eu/resource/authority/language/ENG>"


class CellarConnector(EvidenceSearchConnector):
    provider_key = "cellar"

    def __init__(self, endpoint: str, timeout_seconds: float | None = None) -> None:
        self.endpoint = endpoint
        # Cellar needs its own budget: the shared 20s live-source timeout is
        # what made every live probe of this connector fail, and raising the
        # global value would have slowed the failure detection of nine fast
        # connectors to fix one slow one.
        self.timeout_seconds = timeout_seconds if timeout_seconds is not None else get_settings().CELLAR_SPARQL_TIMEOUT_SECONDS

    async def search(self, intent: EvidenceSearchIntent, *, timeout: float, client: httpx.AsyncClient | None = None) -> EvidenceSearchResponse:
        term = _sparql_literal(intent.query)
        # Two deliberate restrictions, both of which bound what would
        # otherwise be an unindexed substring scan across every expression
        # title in Cellar (every act, in every one of ~24 official
        # languages), which is why the original query exceeded 30 seconds:
        #   - the CELEX id is a required pattern rather than OPTIONAL, so the
        #     scan starts from legal acts instead of the whole corpus. This
        #     is also what every returned record needs to resolve to a
        #     eur-lex.europa.eu citation URL at all.
        #   - only English expressions, so a matching act is considered once
        #     rather than once per language.
        query = f'''PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
SELECT DISTINCT ?work ?celex ?title ?date WHERE {{
  ?work cdm:resource_legal_id_celex ?celex .
  ?expr cdm:expression_belongs_to_work ?work ;
        cdm:expression_uses_language {_ENGLISH} ;
        cdm:expression_title ?title .
  OPTIONAL {{ ?work cdm:work_date_document ?date . }}
  FILTER(CONTAINS(LCASE(STR(?title)), LCASE("{term}")))
}} ORDER BY DESC(?date) LIMIT {intent.page_size}'''
        headers = {"Accept": "application/sparql-results+json"}
        request_timeout = max(timeout, self.timeout_seconds)
        payload = {"query": query, "format": "application/sparql-results+json"}
        if client is not None:
            response = await client.post(self.endpoint, data=payload, headers=headers, timeout=request_timeout)
        else:
            async with httpx.AsyncClient(timeout=request_timeout) as c:
                response = await c.post(self.endpoint, data=payload, headers=headers)
        response.raise_for_status()
        bindings = ((response.json().get("results") or {}).get("bindings") or [])
        records = []
        for row in bindings:
            work = (row.get("work") or {}).get("value", "")
            title = (row.get("title") or {}).get("value", "").strip()
            celex = (row.get("celex") or {}).get("value", "").strip()
            if not work or not title:
                continue
            url = f"https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{celex}" if celex else work
            records.append(EvidenceRecord(
                provider_key=self.provider_key, record_id=celex or work.rsplit("/", 1)[-1],
                record_type="EU legal act", title=title, jurisdiction="EU",
                published_at=(row.get("date") or {}).get("value"), source_url=url,
                metadata={"cellar_work_uri": work, "celex": celex or None},
            ))
        return EvidenceSearchResponse(provider_key=self.provider_key, query=intent.query, records=records,
                                      fetched_at=datetime.now(timezone.utc).isoformat())
