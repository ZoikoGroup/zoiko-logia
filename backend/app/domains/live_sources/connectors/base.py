from __future__ import annotations

from abc import ABC, abstractmethod

from app.domains.live_sources.schemas import LiveDataIntent, NormalizedResponse


import httpx


class LiveSourceConnector(ABC):
    provider_key: str

    @abstractmethod
    async def fetch(self, intent: LiveDataIntent, *, timeout: float, client: httpx.AsyncClient | None = None) -> NormalizedResponse:
        """Fetch and normalize one data point. Raise on failure — callers
        (live_sources/service.py) are responsible for catching and
        degrading gracefully; a connector should not swallow errors."""
        raise NotImplementedError
