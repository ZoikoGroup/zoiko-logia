"""US federal debt, deficit and receipts from Treasury's own Fiscal Data API.

FRED (fred.py) already carries the US federal debt, deficit, revenue, trade
balance and current account as RATIOS — debt and deficit as a percentage of
GDP. That is the right answer to "how big is the deficit relative to the
economy" and the wrong answer to "how much is it", which is how the question is
usually phrased. This connector covers the DOLLAR figures FRED does not carry,
from the primary publisher rather than a mirror of it: the Daily Treasury
Statement and the Monthly Treasury Statement, both keyless.

Three datasets, one per category:
  - debt_to_penny, published every business day — the headline US federal debt
    figure, quoted by the press and used as the debt ceiling denominator.
  - Monthly Treasury Statement table 1, which carries monthly gross receipts,
    outlays and the surplus-or-deficit for the month.

Both are fiscal-year data and both are restated, so the period is stated on the
source rather than left for the reader to infer. A deficit that is a monthly
figure and a deficit that is fiscal-year-to-date are not the same number, and
labelling one as the other is the kind of quiet error that survives review.

The MTS table 1 rows are one per MONTH OF THE FISCAL YEAR, not per reporting
month, so the same `record_date` appears up to twelve times with a different
`classification_desc` each time. Summing them silently would answer "what is
the deficit" with a twelve-times-wrong number, so the connector reports the
most recent single month and says which month it is.
"""
from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from app.domains.calculations.schemas import LiveObservation
from app.orchestration.country_scope import is_country_scoped
from app.orchestration.websearch import WebSource

PROVIDER = "U.S. Department of the Treasury"

_BASE_DEFAULT = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service"

_UA_DEFAULT = "ZoikoLogia Kriton ops@zoikogroup.com"

_COUNTRY = "US"

_DEBT_PATH = "/v2/accounting/od/debt_to_penny"
_MTS_PATH = "/v1/accounting/mts/mts_table_1"

_DEBT_PAGE = "https://fiscaldata.treasury.gov/datasets/daily-treasury-statement/operating-cash-balance/debt-to-the-penny"
_MTS_PAGE = "https://fiscaldata.treasury.gov/datasets/monthly-treasury-statement/operating-cash-balance/mts-table-1"


def _user_agent() -> str:
    return os.getenv("TREASURY_USER_AGENT", _UA_DEFAULT).strip() or _UA_DEFAULT


def _base() -> str:
    base = os.getenv("TREASURY_API_BASE_URL", _BASE_DEFAULT).strip().rstrip("/")
    if "=" in base or not base.startswith(("https://", "http://")):
        return _BASE_DEFAULT
    return base


# The three categories this connector owns. FRED's ratios are matched first by
# fred.py when the question asks for a share of GDP; this connector deliberately
# only claims the DOLLAR questions, so the two never compete for one phrasing.
_DEBT_HINT = re.compile(
    r"\b(?:how much|what is|size of|level of|total|amount of|value of)\s+"
    r"(?:is\s+|are\s+)?(?:the\s+)?(?:us\s+|american\s+)?"
    r"(?:government|federal|national|public)\s+debt\b"
    r"|\bdebt\s+ceiling\b|\bhow much debt\b",
    re.I,
)
_DEFICIT_HINT = re.compile(
    r"\b(?:budget|fiscal)\s+deficit\b|\bfederal deficit\b"
    r"|\b(?:how much|what is|size of)\b[^.?]*\bdeficit\b",
    re.I,
)
_REVENUE_HINT = re.compile(
    r"\b(?:government|federal)\s+(?:revenue|receipts)\b"
    r"|\bhow much\b[^.?]*\b(?:revenue|receipts)\b",
    re.I,
)

_DEBT = {"name": "US Total Public Debt Outstanding", "unit": "USD", "page": _DEBT_PAGE}
_DEFICIT = {
    "name": "US Federal Monthly Deficit or Surplus", "unit": "USD", "page": _MTS_PAGE,
}
_REVENUE = {"name": "US Federal Monthly Gross Receipts", "unit": "USD", "page": _MTS_PAGE}

# The US fiscal year runs October to September, so "month 1" is October. Used
# both to recognise a genuine monthly row and to order them, since sorting by
# month NAME would put April before August correctly but October after May.
_FISCAL_MONTH_NUMBER: dict[str, int] = {
    name: index for index, name in enumerate(
        (
            "October", "November", "December", "January", "February", "March",
            "April", "May", "June", "July", "August", "September",
        ), start=1,
    )
}


def _definition_for_query(query: str) -> dict | None:
    # This connector answers DOLLAR figures only. A question that frames the
    # debt, deficit or revenue as a share/percent/ratio of GDP is about the
    # relative size, and fred.py owns those series (GFDEGDQ188S, FYFSGDA188S,
    # FYFRGDA188S); answering "debt to GDP" with the dollar level would be the
    # same category error FRED's ordering fix was written to prevent. The ratio
    # signal is checked before any hint so "as a share of GDP" never reaches
    # the dollar pattern below.
    if not is_country_scoped(query, _COUNTRY):
        return None
    if re.search(r"\b(?:gdp|share of|percent(?:age)?|%\s+of|ratio|relative to)\b", query or "", re.I):
        return None
    if _DEBT_HINT.search(query or ""):
        return _DEBT
    if _DEFICIT_HINT.search(query or ""):
        return _DEFICIT
    if _REVENUE_HINT.search(query or ""):
        return _REVENUE
    return None


def _as_float(text: object) -> float | None:
    """A Treasury amount as a float, or None if it is not one.

    Fiscal Data returns every amount as a JSON STRING, not a number, and
    publishes the literal "null" on days a statement has no figure. Accepting
    only real JSON numbers made the connector silently return nothing for every
    question — the amounts are quoted, and a quoted figure is still a figure.
    """
    if isinstance(text, bool) or text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    raw = str(text).strip().replace(",", "")
    if raw in {"", "null", "NULL", "None", "nan", "-", "NA", "N/A"}:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


@dataclass
class TreasuryMatch:
    """One matched Treasury figure.

    `points` is a short real history so the value can be charted and checked
    for direction, not just asserted once. `period_label` is the honest label
    for the single figure being reported, because "the deficit" is ambiguous
    between a month, a quarter and a fiscal year and the Monthly Treasury
    Statement's own basis is stated rather than assumed.
    """

    name: str
    value: float
    unit: str
    period: str
    period_label: str
    points: list[tuple[str, float]]
    url: str


async def _get_json(client: httpx.AsyncClient, path: str, params: dict) -> dict:
    response = await client.get(f"{_base()}{path}", params=params)
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {}


async def _find_treasury_figure(query: str) -> TreasuryMatch | None:
    definition = _definition_for_query(query)
    if definition is None:
        return None

    try:
        async with httpx.AsyncClient(timeout=15.0, headers={"User-Agent": _user_agent()}) as client:
            if definition is _DEBT:
                return await _fetch_debt(client, definition)
            return await _fetch_mts(client, definition)
    except Exception:
        return None


async def _fetch_debt(client: httpx.AsyncClient, definition: dict) -> TreasuryMatch | None:
    payload = await _get_json(
        client, _DEBT_PATH,
        {"fields": "record_date,tot_pub_debt_out_amt", "page[size]": "90", "sort": "-record_date"},
    )
    rows = payload.get("data") or []
    points: list[tuple[str, float]] = []
    for row in rows:
        raw_date = str(row.get("record_date") or "")[:10]
        value = _as_float(row.get("tot_pub_debt_out_amt"))
        if not raw_date or value is None:
            # The "Debt to the Penny" file genuinely publishes null on federal
            # holidays. That is a non-publication day, not a zero debt, and
            # charting it at y=0 would be a catastrophic misreading.
            continue
        points.append((raw_date, value))
    if not points:
        return None
    points.sort(key=lambda point: point[0])
    latest_date, latest_value = points[-1]
    return TreasuryMatch(
        name=definition["name"], value=latest_value, unit=definition["unit"],
        period=latest_date, period_label=latest_date, points=points, url=definition["page"],
    )


async def _fetch_mts(client: httpx.AsyncClient, definition: dict) -> TreasuryMatch | None:
    field = (
        "current_month_dfct_sur_amt" if definition is _DEFICIT
        else "current_month_gross_rcpt_amt"
    )
    payload = await _get_json(
        client, _MTS_PATH,
        {
            "fields": f"record_date,classification_desc,{field},data_type_cd",
            "page[size]": "120", "sort": "-record_date",
        },
    )
    rows = payload.get("data") or []
    # `data_type_cd` is load-bearing and is not optional to check. Every
    # publication of table 1 mixes THREE kinds of row under the same date:
    #   "D" discrete — one calendar month of the fiscal year, the only kind
    #       that answers "the deficit in a month";
    #   "T" total    — a "Year-to-Date" CUMULATIVE figure, which for FY2026
    #       was $3.74 trillion against a latest monthly figure of $198 billion;
    #   "S" snapshot — a prior-fiscal-year comparison row.
    # Reading the table without filtering puts a cumulative number in a
    # monthly series, where it is both the wrong period and the wrong
    # magnitude, and nothing about the response looks wrong. Only "D" rows are
    # accepted.
    #
    # The sort key and the period are also kept separate on purpose:
    # `record_date` is the end of the reporting period, while
    # `classification_desc` is which month OF THE FISCAL YEAR the row reports
    # (October is month 1). Conflating the two produced a report reading
    # "2026-05-31, month March of the fiscal year" — a date and a fiscal month
    # that contradict each other — because the label was taken from the first
    # row while the date was taken from the last.
    collected: list[tuple[str, str, str, float]] = []
    for row in rows:
        if str(row.get("data_type_cd") or "").strip().upper() != "D":
            continue
        raw_date = str(row.get("record_date") or "")[:10]
        value = _as_float(row.get(field))
        label = str(row.get("classification_desc") or "").strip()
        if not raw_date or value is None or label not in _FISCAL_MONTH_NUMBER:
            continue
        collected.append((raw_date, raw_date, label, value))
    if not collected:
        return None

    # Oldest first, by reporting date, then by fiscal-month number so the final
    # point is the last month actually reported rather than whichever month
    # name happens to sort last alphabetically.
    collected.sort(key=lambda item: (item[0], _FISCAL_MONTH_NUMBER[item[2]]))

    points = [(period, value) for _, period, _, value in collected]
    latest_date, latest_period, latest_label, latest_value = collected[-1]
    period_label = (
        f"{latest_label} of fiscal year {latest_period[:4]}, "
        f"reporting period ending {latest_period}"
    )
    return TreasuryMatch(
        name=definition["name"], value=latest_value, unit=definition["unit"],
        period=latest_date, period_label=period_label, points=points,
        url=definition["page"],
    )


def _build_source(match: TreasuryMatch) -> WebSource:
    value = match.value
    magnitude = (
        f"${abs(value) / 1_000_000_000_000:,.3f} trillion"
        if abs(value) >= 1_000_000_000_000
        else f"${abs(value) / 1_000_000_000:,.2f} billion"
    )
    direction = "deficit" if value < 0 else "surplus"
    lines = [
        f"U.S. Department of the Treasury — {match.name}, from the "
        f"{'Daily' if match is not None and 'Debt' in match.name else 'Monthly'} "
        f"Treasury Statement. {match.period_label}: "
        f"{'a ' + direction + ' of ' if match.name.endswith(('Deficit or Surplus',)) else ''}"
        f"{magnitude} ({value:,.0f} USD).",
        f"{len(match.points)} published observations retrieved, "
        f"{match.points[0][0]} to {match.points[-1][0]}.",
        "Treasury restates prior months, so earlier figures here may differ from "
        "the same month's original release.",
    ]
    return WebSource(
        title=f"US Treasury — {match.name} ({match.period})",
        url=match.url,
        snippet=" ".join(lines),
        provider=PROVIDER,
        freshness="monthly" if "Monthly" in match.name else "daily",
        series=match.points,
        observation=LiveObservation(
            observation_id=f"obs_{uuid.uuid4().hex}",
            indicator=match.name, value=str(value), unit=match.unit,
            period=match.period, provider=PROVIDER, source_url=match.url,
            freshness="monthly" if "Monthly" in match.name else "daily",
        ),
    )
