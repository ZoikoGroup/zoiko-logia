# Live-Data URL Audit — 10 Supported Countries

Date: 2026-09-29. Scope: `backend/app/orchestration/`, `backend/app/domains/market_data/`,
all provider modules, country routing, `backend/.env`, `backend/.env.example`.
Countries: US, UK, Ireland, Canada, Australia, Germany, France, Japan, India, China.

No routing, provider selection or precedence was changed. Two base-URL reads were
made configurable (World Bank direct, SEC full-text search) because they were
hardcoded; the resolved values are byte-identical to the previous constants.

## 1. Country × category × provider × URL

Legend for "Verified live": ✅ probed and returning data · ⚠️ endpoint correct, no data
for the probe (key/absent service/staleness policy) · ❌ not reachable from this host.

| Country | Data category | Provider | Live URL | Env variable | API key required? | Configured? | Verified live? |
|---|---|---|---|---|---|---|---|
| US | debt/GDP, trade, CPI ratios | FRED | `https://api.stlouisfed.org/fred` | `FRED_API_BASE_URL` | **Yes** (`FRED_API_KEY`) | yes (pre-existing) | ✅ `GFDEGDQ188S` returned |
| US | debt (dollars), budget deficit | US Treasury Fiscal Data | `https://api.fiscaldata.treasury.gov/services/api/fiscal_service` | `TREASURY_API_BASE_URL` | No | yes (pre-existing) | ✅ debt_to_penny → 40,097,178,119,750.91 USD @2026-09-25 |
| US | company financials (XBRL) | SEC EDGAR data | `https://data.sec.gov` | `SEC_EDGAR_API_BASE_URL` | No (User-Agent required) | **added** | ✅ companyfacts + frames returned |
| US | company filings (FTS, peer rank) | SEC EDGAR full-text search | `https://efts.sec.gov` | `SEC_EDGAR_FTS_BASE_URL` | No (User-Agent required) | **added** | ✅ `/LATEST/search-index` returned hits |
| US | ticker index / filing URLs | SEC EDGAR www | `https://www.sec.gov` | `SEC_EDGAR_WWW_BASE_URL` | No (User-Agent required) | **added** | ✅ `company_tickers.json` returned |
| US | company financials (provider layer) | Finnhub / Polygon / Alpha Vantage | `https://finnhub.io/api/v1` · `https://api.polygon.io` · `https://www.alphavantage.co` | `FINNHUB_API_BASE_URL` · `POLYGON_API_BASE_URL` · `ALPHA_VANTAGE_API_BASE_URL` | **Yes** (all three keys set) | **added** | ⚠️ 401/placeholder-key — endpoints correct |
| UK | bank rate | Bank of England (IADB) | `https://www.bankofengland.co.uk/boeapps/database` | `BOE_API_BASE_URL` | No (User-Agent required) | yes (pre-existing) | ✅ IUDBEDR → 3.75 @2026-09-25/28 |
| UK | corp tax / VAT / NI / SDLT rates | GOV.UK Content API | `https://www.gov.uk` | `GOVUK_API_BASE_URL` | No | yes (pre-existing) | ✅ `/api/search.json` + `/api/content` returned; VAT page served; **corporation-tax page refused by the 12-month staleness guard** (page reports no `public_updated_at` — deliberate policy, not a URL fault) |
| UK | legislation | legislation.gov.uk | `https://www.legislation.gov.uk` | `LEGISLATION_API_BASE_URL` | No | yes (pre-existing) | ❌ HTTP 202 + empty body (known CloudFront block from this egress; documented in `.env.example`; connector degrades to SearXNG) |
| UK | company filings/registers | Companies House | `https://api.company-information.service.gov.uk` | `COMPANIES_HOUSE_API_BASE_URL` | **Yes** (`COMPANIES_HOUSE_API_KEY`) | **added** | ⚠️ 401 without auth — endpoint correct; key set in `.env` |
| UK | inflation, GDP | IMF CPI / IMF WEO via DBnomics | `https://api.db.nomics.world/v22` | `DBNOMICS_API_BASE_URL` | No | yes (pre-existing) | ✅ `M.GB.PCPI_PC_CP_A_PT` |
| Ireland | CPI | CSO Ireland (PxStat JSON-stat) | `https://ws.cso.ie/public/api.restful/PxStat.Data.Cube_API.ReadDataset` | `CSO_API_BASE_URL` | No | yes (pre-existing) | ✅ `CPM01/JSON-stat/2.0/en` → 2.76% @2025-12 |
| Ireland | GDP, unemployment | IMF WEO / OECD MEI via DBnomics | `https://api.db.nomics.world/v22` | `DBNOMICS_API_BASE_URL` | No | yes (pre-existing) | ✅ (DBnomics) |
| Canada | policy rate | Bank of Canada (Valet) | `https://www.bankofcanada.ca/valet` | `BANK_OF_CANADA_API_BASE_URL` | No | yes (pre-existing) | ✅ `/observations/V39079/json` → 2.25 @2026-09-25 |
| Canada | CPI, GDP | IMF via DBnomics | `https://api.db.nomics.world/v22` | `DBNOMICS_API_BASE_URL` | No | yes (pre-existing) | ✅ `M.CA.PCPI_PC_CP_A_PT` |
| Canada | debt/GDP, trade balance | World Bank WDI | `https://api.worldbank.org/v2` | `WORLD_BANK_API_BASE_URL` | No | **added** | ✅ verified live (see §2) |
| Australia | cash rate | RBA (table F1 CSV) | `https://www.rba.gov.au/statistics/tables/csv/f1-data.csv` | `RBA_CASH_RATE_CSV_URL` | No | yes (pre-existing) | ✅ 4.35 @2026-09-25/28 |
| Australia | CPI, unemployment | ABS (own Data API) | `https://data.api.abs.gov.au` | `ABS_API_BASE_URL` | No | yes (pre-existing) | ✅ `/rest/data/ABS,CPI_Q,1.0.0/...` → CPI 3.6% 2026-Q2; U 4.90% 2026-08 |
| Australia | GDP | IMF WEO via DBnomics | `https://api.db.nomics.world/v22` | `DBNOMICS_API_BASE_URL` | No | yes (pre-existing) | ✅ |
| Germany | CPI | IMF CPI via DBnomics | `https://api.db.nomics.world/v22` | `DBNOMICS_API_BASE_URL` | No | yes (pre-existing) | ✅ `M.DE.PCPI_PC_CP_A_PT` → 2.00% @2025-07 |
| Germany | GDP, GDP growth, GDP p.c. | IMF WEO via DBnomics | `https://api.db.nomics.world/v22` | `DBNOMICS_API_BASE_URL` | No | yes (pre-existing) | ✅ `DEU.NGDPD` 4,658.5bn @2024; `DEU.NGDPDPC` 54,989.76 @2024 |
| Germany | debt, deficit, revenue | IMF WEO via DBnomics | `https://api.db.nomics.world/v22` | `DBNOMICS_API_BASE_URL` | No | yes (pre-existing) | ✅ `GGXWDG_NGDP`, `GGXCNL_NGDP`, `GGR_NGDP` |
| Germany | unemployment | OECD MEI via DBnomics | `https://api.db.nomics.world/v22` | `DBNOMICS_API_BASE_URL` | No | yes (pre-existing) | ✅ `OECD/MEI/DEU.LRHUTTTT.STSA.M` (last obs 2023-12) |
| Germany | policy rate | ECB ILM via DBnomics | `https://api.db.nomics.world/v22` | `DBNOMICS_API_BASE_URL` | No | yes (pre-existing) | ✅ `ECB/ILM/M.4F.E.L020200.U2.EUR` → 0.0 @2026-07 |
| Germany | trade balance, current account | World Bank WDI (direct + mirror) | `https://api.worldbank.org/v2` · `https://api.db.nomics.world/v22` | `WORLD_BANK_API_BASE_URL` · `DBNOMICS_API_BASE_URL` | No | **added** / pre-existing | ✅ trade 2.36% @2025 |
| Germany | FX | Frankfurter (ECB reference) | `https://api.frankfurter.dev/v1` | `FRANKFURTER_API_BASE_URL` | No | yes (pre-existing) | ✅ |
| Germany | index (DAX) | Yahoo index_quote | `https://query1.finance.yahoo.com/v8/finance` | `YAHOO_INDEX_API_BASE_URL` | No | yes (pre-existing) | ✅ `^GDAXI` 25,501.75 (delayed) |
| Germany | company financials/filings | — | — | — | — | — | ❌ **unimplemented** (no DE national filing API wired) |
| France | CPI / GDP / fiscal / unemployment | IMF + OECD via DBnomics | `https://api.db.nomics.world/v22` | `DBNOMICS_API_BASE_URL` | No | yes (pre-existing) | ✅ CPI 1.00%; GDP 3,162.0bn; U 7.3% (2023-12) |
| France | policy rate | ECB ILM via DBnomics | `https://api.db.nomics.world/v22` | `DBNOMICS_API_BASE_URL` | No | yes (pre-existing) | ✅ 0.0 @2026-07 |
| France | current account | World Bank WDI | `https://api.worldbank.org/v2` | `WORLD_BANK_API_BASE_URL` | No | **added** | ✅ −0.27% @2025 |
| France | FX, index (CAC 40) | Frankfurter, Yahoo index_quote | see Germany rows | `FRANKFURTER_API_BASE_URL`, `YAHOO_INDEX_API_BASE_URL` | No | yes (pre-existing) | ✅ `^FCHI` 8,089.84 (delayed) |
| France | company financials/filings | — | — | — | — | — | ❌ **unimplemented** |
| Japan | CPI / GDP / unemployment | IMF CPI + WEO, OECD MEI via DBnomics | `https://api.db.nomics.world/v22` | `DBNOMICS_API_BASE_URL` | No | yes (pre-existing) | ✅ CPI 3.04%; GDP 4,026.2bn; U 2.4% (2023-12) |
| Japan | policy rate | IMF IFS via DBnomics | `https://api.db.nomics.world/v22` | `DBNOMICS_API_BASE_URL` | No | yes (pre-existing) | ✅ `M.JP.FPOLM_PA` → 0.5 @2025-07 |
| Japan | debt | IMF WEO via DBnomics | `https://api.db.nomics.world/v22` | `DBNOMICS_API_BASE_URL` | No | yes (pre-existing) | ✅ `GGXWDG_NGDP` |
| Japan | trade balance, current account | World Bank WDI | `https://api.worldbank.org/v2` | `WORLD_BANK_API_BASE_URL` | No | **added** | ✅ trade −0.89% @2024; CA 4.86% @2025 |
| Japan | FX, index (Nikkei 225) | Frankfurter, Yahoo index_quote | see Germany rows | see Germany rows | No | yes (pre-existing) | ✅ `^N225` 65,481.27 (delayed) |
| Japan | company filings | — (EDINET not built) | — | — | — | — | ❌ **unimplemented** (EDINET is keyless and buildable) |
| India | CPI / GDP / unemployment | IMF CPI + WEO (LUR) via DBnomics | `https://api.db.nomics.world/v22` | `DBNOMICS_API_BASE_URL` | No | yes (pre-existing) | ✅ CPI 1.55%; GDP 3,909.1bn; U 4.94% @2024 |
| India | policy rate | — | — | — | — | — | ❌ **deliberate refusal** (IFS frozen at 6.25% since 2017-07) |
| India | trade balance, current account | World Bank WDI | `https://api.worldbank.org/v2` | `WORLD_BANK_API_BASE_URL` | No | **added** | ✅ trade −1.74% @2025; CA −0.42% @2025 |
| India | FX (INR), indices (NIFTY 50, SENSEX) | Frankfurter (ECB now publishes INR), Yahoo index_quote | see Germany rows | see Germany rows | No | yes (pre-existing) | ✅ EUR/INR 109.21; `^NSEI` 22,716.20; `^BSESN` 72,402.50 (delayed) |
| India | company financials/filings | — | — | — | — | — | ❌ **unimplemented** |
| China | CPI / GDP / unemployment | IMF CPI + WEO via DBnomics | `https://api.db.nomics.world/v22` | `DBNOMICS_API_BASE_URL` | No | yes (pre-existing) | ✅ CPI 0.02%; GDP 18,748.0bn; U 5.12% @2024 |
| China | policy rate | IMF IFS via DBnomics | `https://api.db.nomics.world/v22` | `DBNOMICS_API_BASE_URL` | No | yes (pre-existing) | ✅ `M.CN.FPOLM_PA` → 1.4 @2025-06 |
| China | debt, deficit, revenue | IMF WEO via DBnomics (WDI carries no China debt) | `https://api.db.nomics.world/v22` | `DBNOMICS_API_BASE_URL` | No | yes (pre-existing) | ✅ `GGXWDG_NGDP` → 88.33% @2024 |
| China | trade balance, GDP | World Bank WDI | `https://api.worldbank.org/v2` | `WORLD_BANK_API_BASE_URL` | No | **added** | ✅ trade 4.19% @2025; GDP 19,498.0bn @2025 |
| China | FX, index (SSE Composite `000001.SS`) | Frankfurter, Yahoo index_quote | see Germany rows | see Germany rows | No | yes (pre-existing) | ✅ EUR/CNY 7.6352; 3,830.45 (delayed) |
| China | company financials/filings | — | — | — | — | — | ❌ **unimplemented** |
| All | FX fallback (non-ECB currencies) | open.er-api | `https://open.er-api.com/v6` | `OPEN_ER_API_BASE_URL` | No | yes (pre-existing) | ✅ `/latest/EUR` |
| All | web grounding backend | SearXNG | `http://localhost:8888` | `SEARXNG_URL` | No | yes (pre-existing) | ⚠️ connection refused in this shell — the compose service, not started here |

## 2. URLs newly added to `backend/.env`

Appended as one commented block at **lines 308–337** (file was 307 lines):

| Line | Variable | Value |
|---|---|---|
| 316 | `WORLD_BANK_API_BASE_URL` | `https://api.worldbank.org/v2` |
| 321 | `SEC_EDGAR_API_BASE_URL` | `https://data.sec.gov` |
| 322 | `SEC_EDGAR_WWW_BASE_URL` | `https://www.sec.gov` |
| 325 | `SEC_EDGAR_FTS_BASE_URL` | `https://efts.sec.gov` |
| 332 | `FINNHUB_API_BASE_URL` | `https://finnhub.io/api/v1` |
| 333 | `POLYGON_API_BASE_URL` | `https://api.polygon.io` |
| 334 | `ALPHA_VANTAGE_API_BASE_URL` | `https://www.alphavantage.co` |
| 337 | `COMPANIES_HOUSE_API_BASE_URL` | `https://api.company-information.service.gov.uk` |

(No API keys were added, changed or invented. No existing variable was duplicated.)

## 3. URLs already present in `backend/.env`

`DBNOMICS_API_BASE_URL`, `FRANKFURTER_API_BASE_URL`, `OPEN_ER_API_BASE_URL`,
`BOE_API_BASE_URL`, `BANK_OF_CANADA_API_BASE_URL`, `RBA_CASH_RATE_CSV_URL`,
`ABS_API_BASE_URL`, `CSO_API_BASE_URL`, `TREASURY_API_BASE_URL`,
`YAHOO_INDEX_API_BASE_URL`, `GOVUK_API_BASE_URL`, `LEGISLATION_API_BASE_URL`,
`FRED_API_BASE_URL`, `SEARXNG_URL`.

Post-change presence check: **22 / 22 base URLs present, 0 missing** (script output
`MISSING_TOTAL 0`), each resolving at runtime to the value above.

## 4. Providers that use code defaults

All of the above ship the same value as a code default, so removing a variable
degrades to today's behaviour rather than to a broken request. The audit added the
explicit entries for visibility and proxy-override, not to change behaviour.

Two endpoints were **hardcoded with no variable at all** and are now configurable:

- `dbnomics._fetch_world_bank` used a literal `https://api.worldbank.org/v2` →
  `_world_bank_base()` reading `WORLD_BANK_API_BASE_URL`.
- `sec_search._ft_base()` / `_data_base()` returned literals →
  `SEC_EDGAR_FTS_BASE_URL` / `SEC_EDGAR_API_BASE_URL`.

## 5. Providers requiring API keys (no key invented)

| Provider | Key variable | State |
|---|---|---|
| FRED | `FRED_API_KEY` | set in `.env`, untouched |
| Finnhub | `FINNHUB_API_KEY` | set in `.env`, untouched |
| Polygon | `POLYGON_API_KEY` | set in `.env`, untouched |
| Alpha Vantage | `ALPHA_VANTAGE_API_KEY` | set in `.env`, untouched |
| Companies House | `COMPANIES_HOUSE_API_KEY` | set in `.env`, untouched |

Also key-gated but **blank in `.env`** (intentionally inactive): `OPENAI_API_KEY`
is set, `ANTHROPIC_API_KEY` is set; the LLM fallbacks are outside the live-data
categories audited here.

## 6. Missing / unimplemented providers

- **Company filings: DE, FR, IN, CN** — no national registry connector. Companies
  House is UK-only and its guard refuses every other supported country.
- **Company filings: Japan** — EDINET is keyless and buildable, not built.
- **Company financials for the five new countries** — no deterministic country
  cable; ticker-based providers can serve a company only if identity resolves a
  ticker. No official national XBRL equivalent of SEC for these five is wired.
- **India policy rate** — deliberately refused (source frozen since 2017).
- **Corporate tax rates for DE/FR/IN/CN** — no structured series; those questions
  route to web grounding.

## 7. Delayed rather than realtime

- All **index levels** (`index_quote`/Yahoo) are labelled `delayed`, never
  realtime — the source states no entitlement.
- **FRED** debt/GDP ratios are quarterly and restated; US debt *dollars* come from
  Treasury (daily) and deliberately outrank FRED.
- **OECD MEI** unemployment (DE/FR/JP and the other OECD members) ends 2023-12 —
  source-side staleness, surfaced in the snapshot.
- **WEO** series are outturns-only by construction (projections from the release
  year are dropped).
- Finnhub/Polygon/Alpha Vantage are configured with `*_REALTIME=false`, so their
  quotes are labelled delayed.

## 8. Files changed

- `backend/.env` — 8 variables appended (lines 308–337). No secrets touched.
- `backend/.env.example` — added `WORLD_BANK_API_BASE_URL`,
  `SEC_EDGAR_FTS_BASE_URL` and the four market-provider base URLs as documented
  optional overrides.
- `backend/app/orchestration/dbnomics.py` — added `_world_bank_base()` and used it
  in `_fetch_world_bank` (same resolved URL).
- `backend/app/orchestration/sec_search.py` — `_data_base()`/`_ft_base()` now read
  the two SEC variables (same resolved URLs); added `import os`.

## 9. Verification

- Endpoint probe of all 22 configured bases: every one returned a real API
  response (200) except the two documented cases — legislation.gov.uk (CloudFront
  202 from this network) and `localhost:8888` (SearXNG container not running in
  this shell). Key-gated providers returned 401/"Invalid API key" when probed
  without a key, which is the correct signature of a working endpoint.
- Four first-pass 404/403s (BoC, CSO, ABS, GOV.UK) were **my guessed paths**, not
  the code's; re-probed with the exact construction each connector uses
  (`/observations/V39079/json`, `/CPM01/JSON-stat/2.0/en`,
  `/rest/data/ABS,CPI_Q,1.0.0/…`, `/api/search.json`) — all 200.
- Import check: `app.core.config`, `dbnomics`, `sec_search`, `live_data` import
  cleanly; the three new resolvers return the configured values.
- Tests: live-data subset **163 passed**; full suite **1025 passed, 10 skipped**.
- Live all-country probe through the app's own resolvers: 10 countries × the
  categories in the table above returned real data with correct provider and source
  URL, including 11 index quotes and direct World Bank WDI fetches
  (India trade −1.74% @2025, Germany growth 0.24% @2025, China GDP 19.50tn @2025).

No secret value from `backend/.env` appears in this report, in terminal output or in
any probe script.
