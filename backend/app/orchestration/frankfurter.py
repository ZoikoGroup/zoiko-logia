"""
Frankfurter exchange-rate retrieval for Ask Kriton™.

Frankfurter (https://frankfurter.dev) is a free, keyless API serving the ECB's
daily reference exchange rates. When a question is about currency conversion or
an exchange rate, this fetches the live rate and returns it as a WebSource — the
SAME shape SearXNG results use — so it merges straight into the existing grounded
answer pipeline (grounding context + [REF-N] source panel) with no other change.

Fails soft: returns [] on any non-FX question, missing currencies, or network/
parse error, so the bot simply falls back to its normal web-grounded answer.
"""
from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass

import httpx

from app.orchestration.websearch import WebSource
from app.domains.calculations.schemas import LiveObservation

# Currencies Frankfurter (ECB daily reference rates) actually publishes —
# NOT a generic ISO-4217 list. AED, SAR and RUB were previously included here
# despite Frankfurter never having rates for them: _find_rate would silently
# return None for those pairs, and the LLM would then fill the gap with an
# approximate rate from its own training data instead of an honest "not
# available" — a real fabrication bug found via live testing. Keep this list
# exactly matched to https://frankfurter.dev's supported currencies so a
# "recognised" code always means Frankfurter can actually answer for it.
_CURRENCY_CODES = {
    "USD", "EUR", "GBP", "INR", "JPY", "AUD", "CAD", "CHF", "CNY", "HKD",
    "SGD", "NZD", "SEK", "NOK", "DKK", "ZAR", "BRL", "MXN",
    "KRW", "TRY", "PLN", "THB", "IDR", "MYR", "PHP", "CZK", "HUF",
    "ILS", "RON", "BGN", "ISK",
}


# How people actually write these currencies. _CURRENCY_CODES above remains
# the sole authority on what Frankfurter can ANSWER for; this table only
# widens how a user may SPELL one of those same currencies. "convert 1100
# dollars to indian rupees" previously found no currency at all and fell
# through to a plain web search, which had no live rate — a question the
# connector could answer perfectly, refused on spelling.
#
# Deliberately absent: bare "peso", "krone", "krona", "won" and "real".
# Each names several different currencies (or, for "won" and "real", is an
# ordinary English word), so only the qualified forms below are matched. A
# guess between Mexican and Philippine pesos is not worth making.
_CURRENCY_ALIASES: dict[str, tuple[str, ...]] = {
    "USD": ("united states dollar", "us dollar", "u.s. dollar", "american dollar",
            "us dollars", "usd", "dollar", "dollars", "$", "us$"),
    "EUR": ("euro", "euros", "eur", "€"),
    "GBP": ("pound sterling", "pounds sterling", "british pound", "british pounds",
            "sterling", "gbp", "quid", "pound", "pounds", "£"),
    "INR": ("indian rupee", "indian rupees", "inr", "rupee", "rupees", "₹"),
    "JPY": ("japanese yen", "jpy", "yen", "¥"),
    "AUD": ("australian dollar", "australian dollars", "aussie dollar", "aud", "a$"),
    "CAD": ("canadian dollar", "canadian dollars", "cad", "c$"),
    "CHF": ("swiss franc", "swiss francs", "chf", "franc", "francs"),
    "CNY": ("chinese yuan", "renminbi", "yuan", "rmb", "cny"),
    "HKD": ("hong kong dollar", "hong kong dollars", "hkd", "hk$"),
    "SGD": ("singapore dollar", "singaporean dollar", "sgd", "s$"),
    "NZD": ("new zealand dollar", "kiwi dollar", "nzd", "nz$"),
    "SEK": ("swedish krona", "swedish kronor", "sek"),
    "NOK": ("norwegian krone", "norwegian kroner", "nok"),
    "DKK": ("danish krone", "danish kroner", "dkk"),
    "ZAR": ("south african rand", "rand", "zar"),
    "BRL": ("brazilian real", "brazilian reais", "reais", "brl", "r$"),
    "MXN": ("mexican peso", "mexican pesos", "mxn"),
    "KRW": ("south korean won", "korean won", "krw", "₩"),
    "TRY": ("turkish lira", "lira", "₺"),
    "PLN": ("polish zloty", "zloty", "pln", "zł"),
    "THB": ("thai baht", "baht", "thb", "฿"),
    "IDR": ("indonesian rupiah", "rupiah", "idr"),
    "MYR": ("malaysian ringgit", "ringgit", "myr"),
    "PHP": ("philippine peso", "philippine pesos", "filipino peso"),
    "CZK": ("czech koruna", "koruna", "czk"),
    "HUF": ("hungarian forint", "forint", "huf"),
    "ILS": ("israeli shekel", "israeli shekels", "shekel", "shekels", "ils", "₪"),
    "RON": ("romanian leu", "romanian lei"),
    "BGN": ("bulgarian lev", "lev", "bgn"),
    "ISK": ("icelandic krona", "icelandic króna", "isk"),
}

# Currencies the ECB does not publish, recognised ONLY so the answer can say
# that outright. This is the other half of the fabrication fix described above
# _CURRENCY_CODES: silently finding nothing is what let the model supply a
# rate from its training data. Naming the gap closes that door. Every entry
# here must stay OUT of _CURRENCY_CODES.
_UNSUPPORTED_ALIASES: dict[str, tuple[str, ...]] = {
    "AED": ("uae dirham", "emirati dirham", "dirham", "dirhams", "aed"),
    "SAR": ("saudi riyal", "saudi riyals", "riyal", "riyals", "sar"),
    "RUB": ("russian ruble", "russian rouble", "ruble", "rouble", "rub", "₽"),
    "PKR": ("pakistani rupee", "pakistani rupees", "pkr"),
    "LKR": ("sri lankan rupee", "sri lankan rupees", "lkr"),
    "NPR": ("nepalese rupee", "nepali rupee", "npr"),
    "BDT": ("bangladeshi taka", "taka", "bdt"),
    "NGN": ("nigerian naira", "naira", "ngn"),
    "EGP": ("egyptian pound", "egyptian pounds", "egp"),
    "VND": ("vietnamese dong", "dong", "vnd"),
    "KES": ("kenyan shilling", "kes"),
    "ARS": ("argentine peso", "argentinian peso", "ars"),
    "CLP": ("chilean peso", "clp"),
    "COP": ("colombian peso", "cop"),
    "QAR": ("qatari riyal", "qar"),
    "KWD": ("kuwaiti dinar", "kwd"),
    "TWD": ("taiwan dollar", "taiwanese dollar", "twd"),
}

# Three-letter codes that are also ordinary English words. Matched only when
# written in capitals, so "try converting 10 GBP" does not resolve to the
# Turkish lira and "php script" does not become a Philippine peso.
_CASE_SENSITIVE_CODES = {"TRY", "RON", "PHP"}

_ALIAS_TO_CODE: dict[str, str] = {}
_SUPPORTED_ALIASES: set[str] = set()
for _table, _is_supported in ((_CURRENCY_ALIASES, True), (_UNSUPPORTED_ALIASES, False)):
    for _code, _aliases in _table.items():
        for _alias in (*_aliases, _code.lower()):
            _ALIAS_TO_CODE[_alias] = _code
            if _is_supported:
                _SUPPORTED_ALIASES.add(_alias)

# Longest first so "canadian dollar" wins over "dollar", and "egyptian pound"
# over "pound" — re alternation takes the first listed alternative that
# matches at a position, so ordering here IS the disambiguation.
_WORD_ALIASES = sorted(
    (a for a in _ALIAS_TO_CODE if a[0].isalnum()), key=len, reverse=True,
)
_SYMBOL_ALIASES = sorted(
    (a for a in _ALIAS_TO_CODE if not a[0].isalnum()), key=len, reverse=True,
)
# Trailing "s" is optional on every word form, so the table lists each
# currency once instead of once per plural — "russian rubles" and "shekels"
# resolve without "ruble"/"shekel" needing a twin entry. The lookup strips it
# back off again below.
_CURRENCY_MENTION = re.compile(
    r"\b(?:"
    + "|".join(re.escape(a) + ("" if a.endswith("s") else "s?") for a in _WORD_ALIASES)
    + r")\b"
    r"|(?:" + "|".join(re.escape(a) for a in _SYMBOL_ALIASES) + r")",
    re.I,
)


def _frankfurter_base() -> str:
    return os.getenv("FRANKFURTER_API_BASE_URL", "https://api.frankfurter.dev/v1").rstrip("/")


def _find_currency_mentions(query: str) -> list[tuple[str, bool]]:
    """(code, is_supported) for every currency named, in the order written.

    Order matters: the first is the base and the second the quote, so
    "1100 dollars to indian rupees" must yield USD before INR.
    """
    seen: list[tuple[str, bool]] = []
    for match in _CURRENCY_MENTION.finditer(query or ""):
        text = match.group(0)
        alias = text.lower()
        code = _ALIAS_TO_CODE.get(alias)
        if code is None and alias.endswith("s"):
            # The optional plural "s" the pattern allowed; the table holds
            # the singular.
            alias = alias[:-1]
            code = _ALIAS_TO_CODE.get(alias)
        if code is None:
            continue
        # An ambiguous code spelled in lower case is the English word, not
        # the currency.
        if code in _CASE_SENSITIVE_CODES and alias == code.lower() and text != code:
            continue
        entry = (code, alias in _SUPPORTED_ALIASES)
        if entry not in seen and all(c != code for c, _ in seen):
            seen.append(entry)
    return seen


def _find_currencies(query: str) -> list[str]:
    """Supported currency codes named in the question, in order."""
    return [code for code, supported in _find_currency_mentions(query) if supported]


def _find_amount(query: str) -> float:
    # Strip thousands separators before parsing, but do not remove every
    # comma from the query (which could join unrelated tokens).
    normalized = re.sub(r"(?<=\d),(?=\d{3}\b)", "", query)
    m = re.search(r"\b(\d+(?:\.\d+)?)\b", normalized)
    return float(m.group(1)) if m else 1.0


@dataclass
class RateMatch:
    """The full result of a Frankfurter lookup — WebSource text (via fetch_fx)
    and structured evidence are both built from this SAME object, so they can
    never disagree about the underlying rate."""

    base_cur: str
    quote_cur: str
    rate: float
    amount: float
    converted: float
    date: str
    url: str


async def _find_rates(query: str) -> list[RateMatch]:
    """One HTTP round-trip to Frankfurter, returning every matched rate. The
    first recognised code is the base, every other recognised code is a target
    rate against it. A query naming three-plus codes ("compare USD to EUR and
    USD to GBP") previously only ever looked at codes[0]/codes[1] and silently
    dropped every other pair, e.g. losing GBP from that exact question.
    Frankfurter's /latest endpoint accepts a comma-separated symbols list, so
    every target is still fetched in a single request, not one per pair."""
    codes = _find_currencies(query)
    # Two recognised currency codes (from -> to) is itself a strong enough
    # signal — no separate FX-hint check needed on top of it (a prior version
    # of this check was a tautology: it only ever ran once len(codes) >= 2
    # was already known true, so it could never actually reject anything).
    if len(codes) < 2:
        return []

    return await _fetch_matches(codes[0], codes[1:], _find_amount(query))


async def _fetch_matches(base_cur: str, quote_curs: list[str], amount: float = 1.0) -> list[RateMatch]:
    """One request for the ECB's own EUR-based rates, crossed here. Asking
    Frankfurter for base=INR returns rates cut to ~4 significant digits
    (1 INR = 0.01042 USD), so ₹25,00,000 came out as $26,050 instead of
    $26,045.73; the EUR table carries the ECB's full published precision."""
    if not quote_curs:
        return []
    base = _frankfurter_base()
    symbols = sorted({base_cur, *quote_curs} - {"EUR"})
    url = f"{base}/latest?symbols={','.join(symbols)}" if symbols else f"{base}/latest"
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
        per_euro = {"EUR": 1.0, **{code: float(value) for code, value in (data.get("rates") or {}).items()}}
        date = data.get("date", "")
    except Exception:
        return []
    if not per_euro.get(base_cur):
        return []

    matches: list[RateMatch] = []
    for quote_cur in quote_curs:
        if quote_cur not in per_euro:
            continue
        rate = per_euro[quote_cur] / per_euro[base_cur]
        matches.append(RateMatch(
            base_cur=base_cur, quote_cur=quote_cur, rate=rate,
            amount=amount, converted=amount * rate, date=date,
            url=f"{base}/latest?base={base_cur}&symbols={quote_cur}",
        ))
    return matches


async def fetch_fx_rates(base_cur: str, quote_curs: list[str], amount: float = 1.0) -> list[WebSource]:
    """Structured entry point: one WebSource per quote currency, from already
    known ISO codes — what the get_exchange_rate tool calls with the model's
    typed arguments. Fails soft to [] like fetch_fx()."""
    return [_build_source(match) for match in await _fetch_matches(base_cur, quote_curs, amount)]


async def _find_rate(query: str) -> RateMatch | None:
    """The single matched rate for a two-currency question, or None. The sole
    source of truth both fetch_fx() and the structured evidence path build
    from."""
    matches = await _find_rates(query)
    return matches[0] if matches else None


def _build_source(match: RateMatch) -> WebSource:
    snippet = (
        f"Live ECB reference rate (Frankfurter), {match.date}: "
        f"1 {match.base_cur} = {match.rate:.8g} {match.quote_cur}. "
        f"{match.amount:.15g} {match.base_cur} = {match.converted:.2f} {match.quote_cur}."
    )
    return WebSource(
        title=f"Frankfurter — {match.base_cur}/{match.quote_cur} exchange rate ({match.date})",
        url=match.url,
        snippet=snippet,
        provider="Frankfurter (ECB reference rates)",
        freshness="daily",
        observation=LiveObservation(
            observation_id=f"obs_{uuid.uuid4().hex}",
            indicator=f"{match.base_cur}/{match.quote_cur} exchange rate",
            value=f"{match.rate:.8g}", unit=f"{match.quote_cur} per {match.base_cur}",
            period=match.date, provider="Frankfurter (ECB reference rates)",
            source_url=match.url, freshness="daily",
        ),
    )


def unsupported_currency_note(query: str) -> WebSource | None:
    """A source stating that a named currency has no ECB reference rate.

    Returning nothing for these is what produced the fabrication bug recorded
    above _CURRENCY_CODES: with no source either way, the model supplied a
    rate from its training data and it looked as grounded as a real one.
    Saying "Frankfurter does not publish this" is itself a fact worth
    grounding on, so it goes into the source panel like any other.

    Only speaks when the question is clearly about a currency pair — two
    currencies named, at least one of them unserviceable — so it stays silent
    on text that merely mentions a currency in passing.
    """
    mentions = _find_currency_mentions(query)
    if len(mentions) < 2:
        return None
    missing = [code for code, supported in mentions if not supported]
    if not missing:
        return None
    named = ", ".join(missing)
    plural = "these currencies" if len(missing) > 1 else "this currency"
    return WebSource(
        title=f"Frankfurter — no ECB reference rate for {named}",
        url="https://frankfurter.dev",
        snippet=(
            f"Frankfurter serves the European Central Bank's daily reference "
            f"rates, which do not include {named}. No live rate is available "
            f"for {plural} from this source, and none should be stated. "
            f"The currencies covered are: {', '.join(sorted(_CURRENCY_CODES))}."
        ),
        provider="frankfurter",
        freshness="realtime",
    )


async def fetch_fx(query: str) -> list[WebSource]:
    """Return one WebSource per base/target currency pair when the question
    names two or more supported currencies; otherwise the explicit "not
    published" note, or []."""
    matches = await _find_rates(query)
    if matches:
        return [_build_source(match) for match in matches]
    note = unsupported_currency_note(query)
    return [note] if note else []
