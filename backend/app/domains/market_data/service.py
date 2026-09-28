"""Market-data orchestration: intent → entity → provider → normalized result.

Fallback semantics, which are the whole point of this layer:

  - A provider that is unconfigured, rate-limited, unavailable or genuinely
    incapable → move to the next provider.
  - A provider that answers "there is no such company" → stop. That is an
    answer, not an outage, and asking three more providers the same question
    invites three different guesses about a company that does not exist.

Everything fails soft at the boundary: fetch_market_data() never raises, so a
provider outage degrades an answer to web-grounded rather than erroring the
whole request — matching how every other live connector in this codebase
behaves.
"""
from __future__ import annotations

import logging
import re

import httpx

from app.domains.market_data import registry
from app.domains.market_data.http import make_client
from app.domains.market_data.identity import company_name_hint, resolve_local
from app.domains.market_data.providers.base import CAP_SEARCH, BaseStockProvider
from app.domains.market_data.schemas import (
    CapabilityNotSupported,
    CompanyProfile,
    EntityRef,
    FilingRecord,
    FinancialMetric,
    OHLCVBar,
    ProviderBadResponse,
    ProviderError,
    ProviderHealth,
    ProviderNotConfigured,
    StockQuote,
)

logger = logging.getLogger(__name__)

# Errors that mean "try the next provider". ProviderBadResponse is deliberately
# absent: it usually means the provider answered and the entity does not exist
# there, which is information, not a failure to route around.
_FALLBACK_ERRORS = (ProviderNotConfigured, CapabilityNotSupported)

MarketResult = StockQuote | list[OHLCVBar] | list[FinancialMetric] | list[FilingRecord] | CompanyProfile
MarketResultForCompany = tuple[MarketResult, str, str, str]  # result, provider_name, intent, company_label

_SEC_FILING_HINT = re.compile(r"\b(?:SEC|EDGAR|10-K|10-Q|8-K|20-F|6-K)\b", re.I)


def _best_provider_search_match(term: str, candidates: list[EntityRef]) -> EntityRef | None:
    """Return a candidate only when every requested identity token is present.

    Provider search ordering is not an identity guarantee. In particular,
    Companies House free-text results may rank a similarly named shell above
    the entity the user meant. Failing closed is safer than attaching another
    company's real filings to the answer.
    """
    words = tuple(re.findall(r"[a-z0-9]+", (term or "").casefold()))
    if not words:
        return None

    def score(candidate: EntityRef) -> tuple[int, int, int]:
        name = candidate.name.casefold().strip()
        name_words = set(re.findall(r"[a-z0-9]+", name))
        if not all(word in name_words for word in words):
            return (-1, 0, 0)
        exact = int(name == " ".join(words))
        active = int(candidate.company_status.casefold() == "active")
        return (exact, active, -len(name_words))

    ranked = sorted(candidates, key=score, reverse=True)
    return ranked[0] if ranked and score(ranked[0])[0] >= 0 else None


# Which identifier each intent actually needs. A ticker is useless to
# Companies House and a company number is useless to a market API, so
# "we resolved *an* id" is not the same as "we resolved a usable one" — that
# conflation silently searched Companies House for an empty string.
_REQUIRED_ID = {
    registry.INTENT_FILINGS: "company_number",
    registry.INTENT_LOOKUP: "company_number",
}


async def _ticker_from_sec_registry(query: str, hint: str) -> tuple[str, str] | None:
    """(ticker, filed name) from SEC EDGAR's registrant index, or None.

    Imported inside the function on purpose: app.orchestration imports this
    domain package, so a module-level import back into orchestration would
    close the loop at startup. Failure is always None — this is an optional
    accelerator in front of the provider search, never a dependency of it.

    `hint` is the query stripped of its scaffolding, which is what lets a
    lower-case "nike stock price" resolve: the hint is exactly "nike". Passing
    it is not the same as relaxing the registry's prose guard — "set a target
    revenue for next year" reduces to "set target next year" and still matches
    nothing, which is the behaviour that guard exists to protect.
    """
    from app.orchestration.sec_edgar import ticker_for_company

    try:
        return await ticker_for_company(query, exact_name=hint)
    except Exception:  # noqa: BLE001 — connector boundary must fail soft
        return None


async def _resolve_entity(
    client: httpx.AsyncClient, query: str, providers: list[BaseStockProvider], intent: str
) -> EntityRef:
    """Pin the question to a company, in the identifier this intent can use.

    Local resolution first (an explicit ticker or UK company number costs no
    network call). If that did not produce the identifier this intent needs, a
    provider search fills the gap — run against the providers already selected
    for the intent, so a UK filings question searches Companies House rather
    than a US market API.
    """
    ref = resolve_local(query)
    # The hint is a SEARCH term, not a display name — it is kept out of
    # ref.name deliberately, because a best-effort phrase shown as a company
    # name reads as "Apple s". ref.name is only ever a confirmed name.
    hint = company_name_hint(query)

    required = _REQUIRED_ID.get(intent, "ticker")
    if getattr(ref, required, ""):
        return ref
    if not hint:
        return ref

    # The SEC's own registrant index before any provider search: it resolves
    # roughly ten thousand US companies by name from one cached file, costs no
    # provider call, and is a filed record rather than a vendor's fuzzy search.
    # identity.py refuses to guess a ticker from a name and its well-known
    # table holds sixteen, so without this "Nike stock price" reached the
    # providers as a free-text guess or resolved to nothing at all.
    if required == "ticker":
        resolved = await _ticker_from_sec_registry(query, hint)
        if resolved is not None:
            ticker, filed_name = resolved
            ref.ticker = ticker
            ref.name = ref.name or filed_name
            return ref

    for provider in providers:
        if not provider.supports(CAP_SEARCH):
            continue
        try:
            matches = await provider.search(client, hint, limit=10)
        except ProviderError as exc:
            logger.info("market_data: search via %s failed: %s", provider.name, exc.message)
            continue
        if not matches:
            continue
        found = _best_provider_search_match(hint, matches)
        if found is None:
            continue
        if not getattr(found, required, ""):
            # This provider found something, but not in the identifier space
            # this intent needs — keep looking rather than returning a ref the
            # downstream call cannot use.
            continue
        found.name = found.name or hint
        # Keep anything local resolution already established (e.g. a ticker
        # alongside a newly-found company number).
        found.ticker = found.ticker or ref.ticker
        found.company_number = found.company_number or ref.company_number
        return found
    return ref


async def fetch_for_intent(
    client: httpx.AsyncClient, intent: str, ref: EntityRef, *, limit: int = 10,
    interval: str = "1d",
) -> tuple[MarketResult, str] | None:
    """First provider that produces data for `intent`, with its name."""
    providers = registry.providers_for(intent)
    for provider in providers:
        try:
            if intent == registry.INTENT_QUOTE:
                return await provider.get_quote(client, ref), provider.name
            if intent == registry.INTENT_HISTORY:
                return await provider.get_history(client, ref, interval=interval, limit=limit), provider.name
            if intent == registry.INTENT_FUNDAMENTALS:
                return await provider.get_fundamentals(client, ref), provider.name
            if intent == registry.INTENT_FILINGS:
                return await provider.get_filings(client, ref, limit=limit), provider.name
            if intent in (registry.INTENT_PROFILE, registry.INTENT_LOOKUP):
                return await provider.get_company_profile(client, ref), provider.name
        except _FALLBACK_ERRORS as exc:
            logger.info("market_data: %s cannot serve %s (%s)", provider.name, intent, exc.message)
            continue
        except ProviderBadResponse as exc:
            # The provider answered; the entity is not there. Stop rather than
            # letting the next provider guess at a different company.
            logger.info("market_data: %s had no data for %s: %s", provider.name, intent, exc.message)
            return None
        except ProviderError as exc:
            logger.warning("market_data: %s failed on %s: %s", provider.name, intent, exc.message)
            continue
    return None


async def fetch_market_data(query: str, *, limit: int = 10) -> tuple[MarketResult, str, str] | None:
    """(result, provider_name, intent) for a market/company question, or None.

    Never raises. None means "this question is not about market data, or no
    configured provider could answer it" — the caller falls back to its normal
    web-grounded path.
    """
    intent = registry.detect_intent(query)
    if intent is None:
        return None

    # "SEC filings" is an explicit source/jurisdiction constraint. Companies
    # House is authoritative only for UK entities, so allowing this request
    # into its free-text search can silently return a similarly named UK
    # company. The EDGAR connector owns explicit SEC filing requests.
    if intent == registry.INTENT_FILINGS and _SEC_FILING_HINT.search(query):
        return None

    providers = registry.providers_for(intent)
    if not providers:
        return None

    try:
        async with make_client() as client:
            # Auth differs per provider (Basic vs header), so each request
            # carries its own; the client itself stays credential-free.
            ref = await _resolve_entity(client, query, providers, intent)
            if not ref.has_any_id() and not ref.name:
                return None

            # History honours an explicit span in the question ("the last 30
            # days"); everything else uses the caller's limit. The interval
            # coarsens with the span so a long request covers its whole period
            # instead of being silently clipped to the most recent 400 days.
            effective_interval, effective_limit = "1d", limit
            if intent == registry.INTENT_HISTORY:
                effective_interval, effective_limit = registry.requested_history_window(query)
            outcome = await fetch_for_intent(
                client, intent, ref, limit=effective_limit, interval=effective_interval
            )
            if outcome is None:
                return None
            result, provider_name = outcome
            return result, provider_name, intent
    except Exception as exc:  # noqa: BLE001 — connector boundary must fail soft
        logger.warning("market_data: unexpected failure: %s", type(exc).__name__)
        return None


async def fetch_market_data_for_companies(
    query: str, companies: list[tuple[str, str, str]], *, limit: int = 10
) -> list[MarketResultForCompany]:
    """(result, provider_name, intent, company_label) for each of `companies`
    (ticker, country, name) — see identity.find_all_known_names(), which the
    caller uses to detect a comparison question up front.

    fetch_market_data() above only ever resolves and answers for a single
    company: "Compare Apple and Microsoft stock price performance" resolved
    to whichever one _resolve_entity() happened to match first, so the other
    company's data was never fetched at all, not just dropped from the
    answer. Each company here is resolved directly from its already-known
    identifiers (no text re-parsing needed, since the caller already pinned
    them) and fetched independently; one company having no data must not
    drop the rest of the comparison, so a per-company failure is skipped
    rather than raised — the answer includes whichever companies actually
    had usable data, same fail-soft contract as fetch_market_data()."""
    intent = registry.detect_intent(query)
    if intent is None:
        return []

    providers = registry.providers_for(intent)
    if not providers:
        return []

    effective_limit = registry.requested_bars(query) if intent == registry.INTENT_HISTORY else limit

    results: list[MarketResultForCompany] = []
    try:
        async with make_client() as client:
            for ticker, country, name in companies:
                ref = EntityRef(ticker=ticker, country=country, name=name)
                try:
                    outcome = await fetch_for_intent(client, intent, ref, limit=effective_limit)
                except Exception as exc:  # noqa: BLE001 — one company's failure must not drop the rest
                    logger.warning(
                        "market_data: comparison fetch failed for %s: %s", name, type(exc).__name__
                    )
                    continue
                if outcome is None:
                    continue
                result, provider_name = outcome
                results.append((result, provider_name, intent, name))
    except Exception as exc:  # noqa: BLE001 — connector boundary must fail soft
        logger.warning("market_data: unexpected failure building comparison client: %s", type(exc).__name__)
        return results
    return results


async def health() -> list[ProviderHealth]:
    """Per-provider health for the status endpoint. Never raises, never returns
    anything derived from a credential."""
    results: list[ProviderHealth] = []
    async with make_client(timeout=5.0) as client:
        for provider in registry.all_providers():
            if not provider.configured():
                results.append(ProviderHealth(provider=provider.name, configured=False, detail="API key not set"))
                continue
            results.append(await provider.health_check(client))
    return results
