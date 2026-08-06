"""Optional Azure AI Search category classifier for Ask Kriton.

Azure supplies a ranked topic/category candidate only. Security screening,
professional-risk classification, licence gates, and route selection remain
deterministic controls owned by the existing orchestration pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import get_settings


@dataclass(frozen=True)
class AzureCategoryCandidate:
    category: str
    score: float
    runner_up_score: float = 0.0
    classification_id: str = ""


class AzureQueryClassifier:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.settings = get_settings()
        self._transport = transport

    @property
    def configured(self) -> bool:
        return bool(
            self.settings.AZURE_AI_SEARCH_ENDPOINT
            and self.settings.AZURE_AI_SEARCH_API_KEY
            and self.settings.AZURE_AI_SEARCH_CLASSIFICATION_INDEX
        )

    async def classify(self, query: str, *, allowed_categories: set[str]) -> AzureCategoryCandidate | None:
        if not self.configured:
            return None

        endpoint = self.settings.AZURE_AI_SEARCH_ENDPOINT.rstrip("/")
        index = self.settings.AZURE_AI_SEARCH_CLASSIFICATION_INDEX
        url = f"{endpoint}/indexes/{index}/docs/search"
        body: dict[str, Any] = {
            "search": query,
            "top": 3,
            "select": "classification_id,category,example_text",
        }
        if self.settings.AZURE_AI_SEARCH_SEMANTIC_CONFIGURATION:
            body.update({
                "queryType": "semantic",
                "semanticQuery": query,
                "semanticConfiguration": self.settings.AZURE_AI_SEARCH_SEMANTIC_CONFIGURATION,
            })
        if self.settings.AZURE_AI_SEARCH_CLASSIFICATION_VECTOR_FIELD:
            body["vectorQueries"] = [{
                "kind": "text",
                "text": query,
                "fields": self.settings.AZURE_AI_SEARCH_CLASSIFICATION_VECTOR_FIELD,
                "k": 20,
            }]

        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=self.settings.AZURE_AI_SEARCH_TIMEOUT_SECONDS,
            ) as client:
                response = await client.post(
                    url,
                    params={"api-version": self.settings.AZURE_AI_SEARCH_API_VERSION},
                    headers={
                        "api-key": self.settings.AZURE_AI_SEARCH_API_KEY,
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
                response.raise_for_status()
                rows = response.json().get("value", [])
        except (httpx.HTTPError, ValueError, TypeError):
            return None

        candidates: list[tuple[str, float, str]] = []
        for row in rows:
            category = str(row.get("category", "")).strip()
            if category not in allowed_categories:
                continue
            # Prefer semantic reranker score when enabled; otherwise use the
            # ordinary hybrid/BM25 search score. These are relevance values,
            # not probabilities, so acceptance uses separately tuned limits.
            raw_score = row.get("@search.rerankerScore", row.get("@search.score", 0.0))
            try:
                score = float(raw_score)
            except (TypeError, ValueError):
                continue
            candidates.append((category, score, str(row.get("classification_id", ""))))

        if not candidates:
            return None
        # Multiple example documents commonly represent the same category.
        # Compare the best score per category so two strong audit examples do
        # not incorrectly look like an ambiguous audit-vs-audit decision.
        best_by_category: dict[str, tuple[float, str]] = {}
        for category, score, classification_id in candidates:
            current = best_by_category.get(category)
            if current is None or score > current[0]:
                best_by_category[category] = (score, classification_id)
        ranked = sorted(best_by_category.items(), key=lambda item: item[1][0], reverse=True)
        category, (score, classification_id) = ranked[0]
        runner_up = ranked[1][1][0] if len(ranked) > 1 else 0.0
        if score < self.settings.AZURE_AI_SEARCH_CLASSIFICATION_MIN_SCORE:
            return None
        if len(ranked) > 1 and score - runner_up < self.settings.AZURE_AI_SEARCH_CLASSIFICATION_MIN_MARGIN:
            return None
        return AzureCategoryCandidate(category, score, runner_up, classification_id)
