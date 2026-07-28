"""
PayrollTax API adapter — read-only wrapper around payrolltaxapi.com's US
payroll-tax rate lookup. Unlike the Treasury adapter, this API is keyed and
metered (free tier: 1,000 requests/month, 20/min) — see
app.core.config.Settings.PAYROLL_TAX_API_KEY.

Nothing outside app/domains/reference_data/ should import this module
directly. Kriton's retrieval layer (and everything else) goes through
service.py instead, which is what gives every external call the audit
trail and caching the reference-data doctrine requires.
"""
from __future__ import annotations

import httpx

from app.core.config import get_settings

_RATES_LOOKUP_PATH = "/rates/lookup"
# Wider than Treasury's 10s (app/domains/reference_data/adapters/treasury_adapter.py)
# — this API's real-world latency is far more variable, observed ranging
# from ~1.1s to ~7.3s for the same endpoint, with at least one request
# exceeding 10s outright. A too-tight timeout here silently drops the live
# chunk (the caller's try/except swallows it per the failure-isolation
# doctrine), degrading to document-only answers even though the API would
# have answered given a bit more time.
_REQUEST_TIMEOUT_SECONDS = 20.0


class PayrollTaxAPIError(Exception):
    """Raised for any non-200 response or transport failure not covered by
    the subclasses below. Never includes the API key — only status code and
    a truncated response body."""


class PayrollTaxAuthError(PayrollTaxAPIError):
    """401/403 — API key missing, invalid, or revoked."""


class PayrollTaxRateLimitError(PayrollTaxAPIError):
    """429 — free-tier quota/rate limit exceeded (1,000 req/month, 20/min)."""


async def get_payroll_tax_rates(
    work_state: str,
    pay_date: str,
    filing_status: str | None = None,
    gross_wages: float | None = None,
    pay_period: str | None = None,
) -> dict:
    settings = get_settings()
    params: dict = {"workState": work_state, "payDate": pay_date}
    if filing_status:
        params["filingStatus"] = filing_status
    if gross_wages is not None:
        params["grossWages"] = gross_wages
    if pay_period:
        params["payPeriod"] = pay_period

    headers = {"Authorization": f"Bearer {settings.PAYROLL_TAX_API_KEY}"}

    try:
        async with httpx.AsyncClient(
            base_url=settings.PAYROLL_TAX_API_BASE_URL, timeout=_REQUEST_TIMEOUT_SECONDS
        ) as client:
            response = await client.get(_RATES_LOOKUP_PATH, params=params, headers=headers)
    except httpx.TimeoutException as exc:
        raise PayrollTaxAPIError(
            f"PayrollTax API timed out after {_REQUEST_TIMEOUT_SECONDS}s"
        ) from exc
    except httpx.HTTPError as exc:
        raise PayrollTaxAPIError(f"PayrollTax API request failed: {exc}") from exc

    if response.status_code in (401, 403):
        raise PayrollTaxAuthError(
            f"PayrollTax API rejected the request (status {response.status_code}) — "
            "API key invalid or revoked"
        )
    if response.status_code == 429:
        raise PayrollTaxRateLimitError(
            "PayrollTax API rate/quota limit exceeded (free tier: 1,000 req/month, 20/min)"
        )
    if response.status_code != 200:
        raise PayrollTaxAPIError(
            f"PayrollTax API returned {response.status_code}: {response.text[:200]}"
        )

    try:
        return response.json()
    except ValueError as exc:
        raise PayrollTaxAPIError(f"Unexpected PayrollTax API response shape: {exc}") from exc
