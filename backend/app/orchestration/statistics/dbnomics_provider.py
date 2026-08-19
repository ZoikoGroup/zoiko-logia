from __future__ import annotations

import os
import re
from typing import Any

import httpx

from app.orchestration.statistics.models import (
    DataSeries,
    MetricRequest,
    Observation,
    SeriesProvenance,
    StatisticalQueryPlan,
)


# Curated, definition-checked fast paths. Generic search remains available for
# other combinations, but known production series should not be rediscovered on
# every request. The UK entries below are annual, current-price national-
# currency measures from OECD Revenue Statistics and the European Commission's
# AMECO database. Their shared periods are aligned before analysis; provenance
# remains explicit because their methodologies come from different providers.
_APPROVED_SERIES: dict[tuple[str, str, str], tuple[str, str, str]] = {
    ("GBR", "tax_revenue", "annual"): (
        "OECD",
        "DSD_REV_OECD@DF_REVGBR",
        "GBR.TAX_REV.S13._T._T.GBP.A",
    ),
    ("GBR", "gdp", "annual"): (
        "AMECO",
        "UVGD",
        "GBR.1.0.0.0.UVGD",
    ),
}


class DBnomicsStatisticalProvider:
    name = "DBnomics"

    def __init__(self, client: httpx.AsyncClient | None = None):
        self._client = client

    @property
    def base_url(self) -> str:
        return os.getenv("DBNOMICS_API_BASE_URL", "https://api.db.nomics.world/v22").rstrip("/")

    async def fetch_series(
        self, metric: MetricRequest, plan: StatisticalQueryPlan
    ) -> DataSeries | None:
        client = self._client or httpx.AsyncClient(timeout=10.0)
        owns_client = self._client is None
        try:
            approved_key = (plan.geography_code or "", metric.code, plan.frequency)
            if approved_key in _APPROVED_SERIES:
                # A failed curated endpoint should fall through to the next
                # registered provider, not fan out into expensive ambiguous
                # discovery against the same throttled service.
                return await self._fetch_approved(client, metric, plan)
            candidates = await self._search_candidates(client, metric, plan)
        finally:
            if owns_client:
                await client.aclose()
        return self._select_candidate(candidates, metric, plan)

    async def _fetch_approved(
        self,
        client: httpx.AsyncClient,
        metric: MetricRequest,
        plan: StatisticalQueryPlan,
    ) -> DataSeries | None:
        identity = _APPROVED_SERIES.get(
            (plan.geography_code or "", metric.code, plan.frequency)
        )
        if identity is None:
            return None
        provider_code, dataset_code, series_code = identity
        try:
            response = await client.get(
                f"{self.base_url}/series/{provider_code}/{dataset_code}/{series_code}",
                params={"observations": "1"},
            )
            response.raise_for_status()
        except httpx.HTTPError:
            return None
        docs = response.json().get("series", {}).get("docs", [])
        if not docs:
            return None
        candidate = docs[0]
        observations = tuple(
            Observation(str(period), float(value))
            for period, value in zip(candidate.get("period") or [], candidate.get("value") or [])
            if isinstance(value, (int, float)) and self._frequency_matches(str(period), plan.frequency)
        )
        if len(observations) < 3:
            return None
        title = str(candidate.get("series_name") or metric.label).replace("�", "·").strip()
        return DataSeries(
            metric_code=metric.code,
            metric_label=metric.label,
            geography_code=plan.geography_code,
            geography_label=plan.geography_label,
            frequency=plan.frequency,
            unit=self._unit(candidate),
            observations=observations,
            provenance=SeriesProvenance(
                provider=f"DBnomics/{provider_code}",
                dataset_code=dataset_code,
                series_code=series_code,
                title=title,
                url=f"{self.base_url}/series/{provider_code}/{dataset_code}/{series_code}",
            ),
        )

    async def _search_candidates(
        self,
        client: httpx.AsyncClient,
        metric: MetricRequest,
        plan: StatisticalQueryPlan,
    ) -> list[dict[str, Any]]:
        # Search metrics independently. Short but meaningful concepts such as
        # GDP, tax and UK are deliberately retained instead of being removed by
        # a generic token-length filter.
        geography = plan.geography_label or ""
        searches = [f"{geography} {alias}".strip() for alias in metric.aliases]
        datasets_by_id: dict[tuple[str, str], dict[str, Any]] = {}
        for query in dict.fromkeys(searches):
            try:
                response = await client.get(f"{self.base_url}/search", params={"q": query, "limit": 10})
                response.raise_for_status()
            except httpx.HTTPError:
                continue
            for dataset in response.json().get("results", {}).get("docs", []):
                identity = (str(dataset.get("provider_code") or ""), str(dataset.get("code") or ""))
                if all(identity):
                    datasets_by_id[identity] = dataset

        datasets = sorted(
            datasets_by_id.values(),
            key=lambda dataset: self._dataset_score(dataset, metric, plan),
            reverse=True,
        )

        candidates: list[dict[str, Any]] = []
        for dataset in datasets[:4]:
            provider_code, dataset_code = dataset.get("provider_code"), dataset.get("code")
            if not provider_code or not dataset_code:
                continue
            try:
                response = await client.get(
                    f"{self.base_url}/series/{provider_code}/{dataset_code}",
                    params={"observations": "1", "limit": 100},
                )
                response.raise_for_status()
            except httpx.HTTPError:
                # One large or temporarily unavailable dataset must not prevent
                # fallback to another provider/dataset returned by search.
                continue
            for series in response.json().get("series", {}).get("docs", []):
                series["_dataset"] = dataset
                candidates.append(series)
        return candidates

    @staticmethod
    def _dataset_score(
        dataset: dict[str, Any], metric: MetricRequest, plan: StatisticalQueryPlan
    ) -> int:
        searchable = f"{dataset.get('name', '')} {dataset.get('code', '')}".lower()
        score = sum(3 for alias in metric.aliases if alias in searchable)
        if plan.geography_label and plan.geography_label.lower() in searchable:
            score += 6
        if plan.geography_code and plan.geography_code.lower() in searchable:
            score += 4
        return score

    def _select_candidate(
        self,
        candidates: list[dict[str, Any]],
        metric: MetricRequest,
        plan: StatisticalQueryPlan,
    ) -> DataSeries | None:
        best: tuple[int, dict[str, Any], tuple[Observation, ...]] | None = None
        geography_terms = tuple(
            term.lower() for term in (plan.geography_label or "", plan.geography_code or "") if term
        )
        metric_terms = tuple(alias.lower() for alias in metric.aliases)

        for candidate in candidates:
            periods = candidate.get("period") or []
            values = candidate.get("value") or []
            observations = tuple(
                Observation(str(period), float(value))
                for period, value in zip(periods, values)
                if isinstance(value, (int, float)) and self._frequency_matches(str(period), plan.frequency)
            )
            if len(observations) < 3:
                continue
            dataset = candidate.get("_dataset", {})
            searchable = " ".join(
                str(candidate.get(key) or "")
                for key in ("series_name", "series_code", "dimensions", "dataset_name")
            ) + f" {dataset.get('name', '')} {dataset.get('code', '')}"
            searchable = searchable.lower()
            metric_score = max((4 if term in searchable else 0 for term in metric_terms), default=0)
            geography_score = max((4 if term in searchable else 0 for term in geography_terms), default=0)
            frequency_score = 2 if plan.frequency.lower() in searchable else 0
            score = metric_score + geography_score + frequency_score + min(len(observations) // 10, 3)
            if metric_score == 0 or (geography_terms and geography_score == 0):
                continue
            if best is None or score > best[0]:
                best = (score, candidate, observations)

        if best is None:
            return None
        _, candidate, observations = best
        dataset = candidate.get("_dataset", {})
        provider_code = str(candidate.get("provider_code") or dataset.get("provider_code") or "")
        dataset_code = str(candidate.get("dataset_code") or dataset.get("code") or "")
        series_code = str(candidate.get("series_code") or "")
        title = str(candidate.get("series_name") or metric.label).replace("�", "·").strip()
        return DataSeries(
            metric_code=metric.code,
            metric_label=metric.label,
            geography_code=plan.geography_code,
            geography_label=plan.geography_label,
            frequency=plan.frequency,
            unit=self._unit(candidate),
            observations=observations,
            provenance=SeriesProvenance(
                provider=f"DBnomics/{provider_code}",
                dataset_code=dataset_code,
                series_code=series_code,
                title=title,
                url=f"{self.base_url}/series/{provider_code}/{dataset_code}/{series_code}",
            ),
        )

    @staticmethod
    def _frequency_matches(period: str, frequency: str) -> bool:
        if frequency == "annual":
            return re.fullmatch(r"\d{4}", period) is not None
        if frequency == "quarterly":
            return re.fullmatch(r"\d{4}-Q[1-4]", period, re.I) is not None
        return True

    @staticmethod
    def _unit(candidate: dict[str, Any]) -> str | None:
        for key in ("unit_name", "unit", "Unit"):
            value = candidate.get(key)
            if value:
                return str(value)
        return None
