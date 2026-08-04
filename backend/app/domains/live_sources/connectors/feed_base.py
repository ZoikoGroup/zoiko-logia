"""Base contract for bulk authoritative feeds synchronized as snapshots."""
from __future__ import annotations

from abc import ABC, abstractmethod

import httpx

from app.domains.live_sources.feed_schemas import SanctionsSnapshot


class SanctionsFeedConnector(ABC):
    provider_key: str

    @abstractmethod
    async def fetch_snapshot(
        self, *, timeout: float, max_bytes: int,
        client: httpx.AsyncClient | None = None,
    ) -> SanctionsSnapshot:
        raise NotImplementedError
