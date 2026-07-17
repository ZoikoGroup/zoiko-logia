"""
Keyword-based "does this query want live external data" detector — the live-
source analogue of app.orchestration.retrieve.py's infer_category(), but
answering a different question (which external indicator + country, not
which internal document category). Kept as a separate module rather than
folded into infer_category() since the two never need to run against each
other's tables.

MVP scope: World Bank indicators only (GDP, inflation, unemployment).
Anything else returns None — the live-data path is a no-op for those
queries, leaving the existing document pipeline completely unaffected.
"""
from __future__ import annotations

from app.domains.live_sources.schemas import LiveDataIntent

# Ordered so multi-word phrases are checked before their single-word
# substrings (e.g. "gdp growth" before "gdp") would matter if overlapping
# keywords existed; kept as a plain dict since none currently overlap, but
# order is preserved for future additions.
_INDICATOR_KEYWORDS: list[tuple[str, str, str]] = [
    ("gdp growth", "NY.GDP.MKTP.KD.ZG", "GDP growth (annual %)"),
    ("gdp", "NY.GDP.MKTP.CD", "GDP (current US$)"),
    ("inflation", "FP.CPI.TOTL.ZG", "Inflation, consumer prices (annual %)"),
    ("cpi", "FP.CPI.TOTL.ZG", "Inflation, consumer prices (annual %)"),
    ("unemployment", "SL.UEM.TOTL.ZS", "Unemployment (% of total labor force)"),
]

_COUNTRY_KEYWORDS: dict[str, tuple[str, str]] = {
    "india": ("IN", "India"),
    "united states": ("US", "United States"),
    "usa": ("US", "United States"),
    "us": ("US", "United States"),
    "united kingdom": ("GB", "United Kingdom"),
    "uk": ("GB", "United Kingdom"),
}

_DEFAULT_COUNTRY = ("WLD", "World")


def detect_live_data_intent(query: str) -> LiveDataIntent | None:
    lowered = query.lower()

    indicator = next(
        ((code, label) for keyword, code, label in _INDICATOR_KEYWORDS if keyword in lowered),
        None,
    )
    if indicator is None:
        return None

    country = next(
        (value for keyword, value in _COUNTRY_KEYWORDS.items() if keyword in lowered),
        _DEFAULT_COUNTRY,
    )

    indicator_code, indicator_label = indicator
    country_code, country_label = country
    return LiveDataIntent(
        provider_key="world_bank",
        indicator_code=indicator_code,
        indicator_label=indicator_label,
        country_code=country_code,
        country_label=country_label,
    )
