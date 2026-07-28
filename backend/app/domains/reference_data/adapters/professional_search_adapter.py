"""Restricted web discovery for US accounting, tax, and audit authorities."""
from __future__ import annotations

import html
import re
from urllib.parse import urlparse

import httpx

from app.core.config import get_settings

_TIMEOUT = 15.0
_MAX_RESULTS = 3


class ProfessionalSearchError(Exception):
    pass


def is_allowed_authority_url(url: str, allowed_domains: list[str]) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    return urlparse(url).scheme == "https" and any(
        host == domain or host.endswith(f".{domain}") for domain in allowed_domains
    )


def _plain_text(value: str) -> str:
    value = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", value or "", flags=re.I | re.S)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", value)).split())


async def search_tavily(query: str) -> list[dict]:
    settings = get_settings()
    if not settings.TAVILY_API_KEY:
        raise ProfessionalSearchError("Tavily API key is not configured")
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.post(
            f"{settings.TAVILY_API_BASE_URL.rstrip('/')}/search",
            json={
                "api_key": settings.TAVILY_API_KEY,
                "query": query,
                "include_domains": settings.PROFESSIONAL_SEARCH_ALLOWED_DOMAINS,
                "include_raw_content": True,
                "max_results": _MAX_RESULTS,
                "search_depth": "basic",
            },
        )
    if response.status_code != 200:
        raise ProfessionalSearchError(f"Tavily returned status {response.status_code}")
    results = response.json().get("results", [])
    return [
        {"title": item.get("title", "Authority page"), "url": item.get("url", ""),
         "content": _plain_text(item.get("raw_content") or item.get("content") or "")}
        for item in results if is_allowed_authority_url(item.get("url", ""), settings.PROFESSIONAL_SEARCH_ALLOWED_DOMAINS)
    ]


async def search_serpapi(query: str) -> list[dict]:
    settings = get_settings()
    if not settings.SERP_API_KEY:
        raise ProfessionalSearchError("SerpAPI key is not configured")
    site_filter = " OR ".join(f"site:{domain}" for domain in settings.PROFESSIONAL_SEARCH_ALLOWED_DOMAINS)
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        response = await client.get(
            settings.SERP_API_BASE_URL,
            params={"api_key": settings.SERP_API_KEY, "engine": "google", "q": f"({site_filter}) {query}", "num": _MAX_RESULTS},
        )
        if response.status_code != 200:
            raise ProfessionalSearchError(f"SerpAPI returned status {response.status_code}")
        candidates = response.json().get("organic_results", [])[:_MAX_RESULTS]
        results = []
        for item in candidates:
            url = item.get("link", "")
            if not is_allowed_authority_url(url, settings.PROFESSIONAL_SEARCH_ALLOWED_DOMAINS):
                continue
            try:
                page = await client.get(url)
                if page.status_code != 200 or not is_allowed_authority_url(str(page.url), settings.PROFESSIONAL_SEARCH_ALLOWED_DOMAINS):
                    continue
                content = _plain_text(page.text)
            except httpx.HTTPError:
                continue
            if content:
                results.append({"title": item.get("title", "Authority page"), "url": str(page.url), "content": content})
        return results
