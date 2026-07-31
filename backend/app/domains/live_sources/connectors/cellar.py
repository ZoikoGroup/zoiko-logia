"""Public Cellar knowledge-graph search for official EU legal metadata."""
from __future__ import annotations

from datetime import datetime, timezone

import httpx

from app.domains.live_sources.connectors.evidence_base import EvidenceSearchConnector
from app.domains.live_sources.evidence_schemas import EvidenceRecord, EvidenceSearchIntent, EvidenceSearchResponse


def _sparql_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\r", " ").replace("\n", " ")


class CellarConnector(EvidenceSearchConnector):
    provider_key = "cellar"

    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint

    async def search(self, intent: EvidenceSearchIntent, *, timeout: float, client: httpx.AsyncClient | None = None) -> EvidenceSearchResponse:
        term = _sparql_literal(intent.query)
        query = f'''PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
SELECT DISTINCT ?work ?celex ?title ?date WHERE {{
  ?expr cdm:expression_belongs_to_work ?work ; cdm:expression_title ?title .
  OPTIONAL {{ ?work cdm:resource_legal_id_celex ?celex . }}
  OPTIONAL {{ ?work cdm:work_date_document ?date . }}
  FILTER(CONTAINS(LCASE(STR(?title)), LCASE("{term}")))
}} ORDER BY DESC(?date) LIMIT {intent.page_size}'''
        headers = {"Accept": "application/sparql-results+json"}
        if client is not None:
            response = await client.post(self.endpoint, data={"query": query, "format": "application/sparql-results+json"}, headers=headers)
        else:
            async with httpx.AsyncClient(timeout=timeout) as c:
                response = await c.post(self.endpoint, data={"query": query, "format": "application/sparql-results+json"}, headers=headers)
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
