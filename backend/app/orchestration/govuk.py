"""UK tax rates and thresholds from the official GOV.UK Content API.

Keyless and authoritative, and the obvious missing piece for a UK accounting
product. It is also, on inspection, the single most dangerous source available
to ground a tax answer on, and this module is built around that rather than
despite it.

GOV.UK never deletes a page. It publishes a page, and then a later page with
the same slug, and both answer HTTP 200 through the Content API forever. On
inspection while writing this:

  /government/publications/corporation-tax-main-rate   200, updated 2015-07-08
      body: "The Corporation Tax main rate for 1 April 2016 is set at 20%.
             The rate for 1 April 2017 is 19% ... 1 April 2020 is set at 18%."
  /vat-rates                                          200, updated 2014-12-12

A connector that simply fetched "the corporation tax page" would have returned
a decade-old document whose stated rates are all wrong, in clean prose, with a
live gov.uk URL, and the model would have reported 19% as the UK corporation
tax main rate. That is the single worst failure available to this product.

So the governing rule here is an expiry, not a lookup. A page is used only if
GOV.UK itself reports it as updated within GOVUK_MAX_AGE_MONTHS (default 12,
set for a Budget cycle rather than a product cycle), and the page's own
last-updated date is put on the face of every source built from it. A tax rate
that cannot be shown to be current is not reported — the question falls
through to SearXNG, which cites the page it found and lets the reader judge.

The practical consequence is honest and worth stating: most UK rate content
currently lives in spreadsheet attachments that the API does not serve, so in
practice this connector answers VAT and similar long-form guidance well and
leaves banded tables to the search path. Coverage here is deliberately smaller
than the number of pages that would technically resolve.
"""
from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape

import httpx

from app.domains.calculations.schemas import LiveObservation
from app.orchestration.uk_scope import is_uk_scoped
from app.orchestration.websearch import WebSource

PROVIDER = "GOV.UK"

_BASE_DEFAULT = "https://www.gov.uk"

# tax topic -> the terms that find its current page on GOV.UK.
_TOPICS: dict[str, str] = {
    "corporation tax": "corporation tax rates",
    "company tax": "corporation tax rates",
    "ct600": "corporation tax rates",
    "income tax": "income tax rates and allowances",
    "paye": "income tax rates and allowances",
    "national insurance": "national insurance rates and categories",
    "ni": "national insurance rates and categories",
    "vat": "VAT rates",
    "stamp duty": "stamp duty land tax rates",
    "sdlt": "stamp duty land tax rates",
}
_RATE_HINT = re.compile(
    r"\b(?:rate|rates|allowance|allowances|band|bands|threshold|thresholds|"
    r"percentage|deduction|relief|limit)\b",
    re.I,
)
# A "current rate" question. A question about how a regime works is not one,
# and must not be answered with whatever single page happens to be current.
_CURRENT_HINT = re.compile(
    r"\b(?:current|currently|now|today|latest|this year|202\d|20\d{2}|"
    r"what is|whats|how much is|at the moment|at present)\b",
    re.I,
)
_TAG = re.compile(r"<[^>]+>")


def _base() -> str:
    base = os.getenv("GOVUK_API_BASE_URL", _BASE_DEFAULT).strip().rstrip("/")
    if "=" in base or not base.startswith(("https://", "http://")):
        return _BASE_DEFAULT
    return base


def _max_age_months() -> int:
    try:
        value = int(os.getenv("GOVUK_MAX_AGE_MONTHS", "12"))
    except ValueError:
        return 12
    return value if 0 < value <= 120 else 12


def _strip_html(markup: str) -> str:
    text = _TAG.sub(" ", markup or "")
    text = re.sub(r"(?i)</(p|li|tr|h\d|div)>", "\n", text)
    text = unescape(text)
    # Inline tags become spaces, which leaves "20% ." and " , 5 points" in text
    # that goes straight into a model prompt as though it were the official
    # wording. Tidy the punctuation that spacing introduced.
    text = re.sub(r"\s+([.,;:%)])", r"\1", text)
    text = re.sub(r"([($])\s+", r"\1", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return re.sub(r"[ \t]*\n[ \t]*", "\n", text).strip()


def _topics(query: str) -> list[str]:
    lowered = (query or "").lower()
    return [terms for topic, terms in _TOPICS.items() if re.search(rf"\b{re.escape(topic)}\b", lowered)]


def _is_fresh(updated_at: str | None, *, now: datetime | None = None) -> bool:
    """Whether GOV.UK reports this page as updated recently enough to be a
    current rate. Unparseable or absent dates are treated as stale: a page that
    will not state when it was last checked is not evidence of a current rate."""
    if not updated_at:
        return False
    now = now or datetime.now(timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(updated_at).replace("Z", "+00:00"))
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    months = (now - parsed).days / 30.44
    return months <= _max_age_months()


def _definition_for_query(query: str) -> str | None:
    topics = _topics(query)
    if not topics:
        return None
    if not _RATE_HINT.search(query or ""):
        return None
    if not _CURRENT_HINT.search(query or ""):
        return None
    # GOV.UK is a UK site and its rate pages are UK rates. "What is the current
    # German VAT rate" matches the VAT topic, the rate wording and the
    # currentness intent all at once, so without this it would be answered with
    # the UK VAT page — a real official rate, for the wrong country, which is
    # the hardest kind of wrong to spot. Same scope rule as the Bank Rate
    # connector, and the same shared country list.
    if not is_uk_scoped(query):
        return None
    return topics[0]


@dataclass
class GovUkMatch:
    title: str
    path: str
    updated_at: str
    body: str
    url: str

    @property
    def updated_date(self) -> str:
        return str(self.updated_at)[:10]


async def _find_uk_tax_rate(
    query: str, *, client: httpx.AsyncClient | None = None,
) -> GovUkMatch | None:
    terms = _definition_for_query(query)
    if terms is None:
        return None

    base = _base()
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=10.0, follow_redirects=True)
    try:
        try:
            response = await http.get(
                f"{base}/api/search.json",
                params={"q": terms, "count": 5, "fields": "title,link,public_timestamp"},
            )
            response.raise_for_status()
            results = response.json().get("results") or []
        except Exception:
            return None

        for result in results:
            path = str(result.get("link") or "")
            if not path:
                continue
            # The search index carries its own timestamp, so a decade-old page
            # costs nothing extra to reject.
            if not _is_fresh(result.get("public_timestamp")):
                continue
            try:
                page = await http.get(f"{base}/api/content{path}")
                page.raise_for_status()
                document = page.json()
            except Exception:
                continue
            if not _is_fresh(document.get("public_updated_at")):
                continue
            body = _strip_html((document.get("details") or {}).get("body") or "")
            # Many rate pages are a stub whose real content is an attachment
            # the API does not serve. An empty body is not a rate.
            if len(body) < 200:
                continue
            return GovUkMatch(
                title=str(document.get("title") or result.get("title") or path),
                path=path, updated_at=str(document.get("public_updated_at") or ""),
                body=body, url=f"{base}{path}",
            )
        return None
    finally:
        if owns_client:
            await http.aclose()


def _build_source(match: GovUkMatch) -> WebSource:
    clipped = match.body[:8000] + (" …" if len(match.body) > 8000 else "")
    snippet = (
        f"Official GOV.UK guidance: \"{match.title}\", last updated by GOV.UK on "
        f"{match.updated_date}. Quote any rate with that date attached; tax "
        f"rates change at Budget and in April, and a figure from a page that "
        f"has not been updated in over a year is not a current rate. "
        f"Page text follows.\n\n{clipped}"
    )
    return WebSource(
        title=f"GOV.UK — {match.title} (updated {match.updated_date})",
        url=match.url,
        snippet=snippet,
        provider=PROVIDER,
        freshness="legislation",
        observation=LiveObservation(
            observation_id=f"obs_{uuid.uuid4().hex}",
            indicator=match.title, value=match.updated_date, unit="last updated",
            period=match.updated_date, provider=PROVIDER, source_url=match.url,
            freshness="legislation",
        ),
    )
