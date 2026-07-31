"""Base contract for official document, docket, law, and procurement search APIs."""
from __future__ import annotations

from abc import ABC, abstractmethod

import httpx

from app.domains.live_sources.evidence_schemas import EvidenceSearchIntent, EvidenceSearchResponse


class EvidenceSearchConnector(ABC):
    provider_key: str

    @abstractmethod
    async def search(
        self, intent: EvidenceSearchIntent, *, timeout: float,
        client: httpx.AsyncClient | None = None,
    ) -> EvidenceSearchResponse:
        raise NotImplementedError
