# Five-More-Country Live-Data Expansion — Final Report

Companion to `FIVE_COUNTRY_LIVE_DATA_REPORT.md` (US, UK, Ireland, Canada, Australia).
This covers the ten-supported-country milestone: Germany, France, Japan, India, China.

## A. Problem under investigation

The live-data pipeline handled seven countries with dedicated official connectors
(after the prior expansion) plus DBnomics/IMF/WDI/OECD/FRED/ECB for statistics and
Frankfurter/Yahoo for FX/index quotes. Germany, France, Japan, India and China were
**supported countries** in `country_scope`, but their "headline figure" questions had
gaps and, worse, several could return the *wrong statistic* for the right country:

| Question | Before | After |
|---|---|---|
| "What is the German inflation rate?" | generic DBnomics search | **IMF CPI, explicit all-items series** |
| "What is the Japanese policy rate?" | generic DBnomics search / IFS probe needed | **IMF IFS FPOLM_PA (0.5%, 2025-07)** |
| "What is the German/Dutch interest rate?" | same generic noise | **ECB deposit facility (0.0%, 2026-07)** |
| "What is the Indian employment rate?" | generic search (sometimes an unrelated tax dataset) | **WEO LUR, outturns only (4.9%, 2024)** |
| "What is China's government debt to GDP?" | fuzzy full-text (WDI carries no China debt) | **WEO GGXWDG (88.3% of GDP, 2024)** |
| "What is the German budget deficit as a share of GDP?" | **WDI GDP *growth*** (0.24%!) — generic WDI rule grabbed "GDP" | **WEO net lending/borrowing (−2.8% of GDP, 2024)** |
| "What is the French government revenue as a share of GDP?" | **WDI GDP growth** (0.84%!) | **WEO GGR_NGDP (51.4% of GDP, 2024)** |
| "Japan general government central debt to GDP" | **WDI GDP growth** (1.19%!) | **WEO GGXWDG (outturn %, of GDP)** |
| "What is the level of the NIFTY / SENSEX / SSE Composite?" | nothing (unknown symbols) | **index_quote: 22,685.35 / 72,429.26 / 3,830.45** |
| "German registries filing / Toyota filings" | fell through; per-country registry unclear | **deterministic guard: not UK/Companies House** |
| "What is India's policy rate?" | IFS FPOLM_PA frozen at 6.25 since 2017-07 (misleading) | **deliberate "no source" → web-grounded answer** |

## B. Root causes

1. **No deterministic routing for the five.** Only CPI and GDP had targeted resolvers
   (`_find_cpi_series`, `_find_gdp_series`); fiscal (debt/deficit/revenue), policy rate
   and per-capita GDP relied on generic full-text DBnomics ranking, which returned
   unrelated slices or nothing.
2. **The WDI path ran before the targeted resolvers and swallowed fiscal questions.**
   `fetch_stats` consults `_wdi_sources` first; the generic WDI GDP rule matches any
   query containing "GDP" — so "budget deficit as a share of GDP" and "government
   central debt as a share of GDP" were answered with GDP **growth**.
3. **WEO forecast leakage.** WEO series embed IMF projections for the current/future
   years; naive fetching served 2029/2030 "history" for India unemployment.
4. **GDP per-capita conflation.** "Germany GDP per capita" resolved to total GDP
   (NGDPD, ~10<sup>9</sup> USD) instead of the per-capita indicator.
5. **Stale/frozen misleading sources.** IFS India policy rate was never updated
   (6.25% since 2017). OECD MEI unemployment still ends 2023-12 for DE/FR/JP, but that
   is *consistent* with the first five (deliberate, see E).
6. **Yahoo index symbols.** `^SSEC` (Shanghai Composite) is obsolete (HTTP 404); NIFTY,
   SENSEX and SSE Composite were not in the identity symbol set at all.
7. **Market cross-country leak.** Companies House filings answers had to be guarded for
   the new five exactly as for IE/CA/AU/US: a "registry filings" question naming Germany
   or Japan must not resolve to the UK register.

## C. Changes made

All in `app/orchestration/dbnomics.py`, `app/orchestration/country_scope.py`,
`app/domains/market_data/{registry.py,identity.py,service.py,providers/index_quote.py}`.

### Statistics resolvers (dbnomics.py)
- **WEO units table** — `_WEO_UNITS` updated with `NGDPDPC.us_dollars`, `GGREV_NGDP`,
  `GGR_NGDP`, `GGXWDG_NGDP`, `GGXWDN_NGDP`, `BCA_NGDPD` (WEO series carry a third
  "unit" dimension; dropping it 404s).
- **`_find_weo_fiscal_series`** — deterministic WEO fiscal aggregates (gross debt
  `GGXWDG_NGDP`, net lending/borrowing `GGXCNL_NGDP`, revenue `GGR_NGDP`, all
  percent-of-GDP) **scoped to the new five**, with the release-year outturns cutoff.
- **`_find_policy_rate_series`** — JP/CN → IMF IFS `FPOLM_PA`; DE/FR → ECB deposit
  facility (the ECB's near-cash rate; IFS DE FR data is frozen pre-2023 for FR).
- **Fiscal-first precedent in `fetch_stats`** — for a new-five country + fiscal hint,
  the WEO fiscal resolver runs **before** `_wdi_sources`, so a query that also contains
  "GDP" can never be rerouted to WDI GDP growth.
- **Debt phrasing broadened** — `_FISCAL_DEBT_HINT` now matches "general government
  central debt", "national debt", "federal debt", etc., not only "government debt".
- **`_find_gdp_series` per-capita** — "per capita"/"per head" → `NGDPDPC.us_dollars`
  instead of `NGDPD`.
- **Unemployment** — IN/CN → WEO `LUR.pcent_total_labor_force` with release-year
  outturns-only cutoff; DE/FR/JP stay on OECD MEI (`LRHUTTTT.STSA.M`).
- **`_CPI_COUNTRIES` adjective aliases** added: german, french, canadian, japanese,
  indian, american (plus existing deutschland/chinese/prc) — so "German inflation" now
  resolves the country.

### Country scope (country_scope.py)
- `_DE`/`_FR`/`_JP`/`_IN`/`_CN` word-boundary patterns and `_DISPLAY` names
  (twelve-character trick for China), docstring updated to ten supported countries.
  Bare `IN`/`CN` are not used as patterns (too many false hits).

### Market data
- `registry.py` — `_macro_question_refusal` now refuses macro-stat questions for all ten
  countries; `INTENT_INDEX` pattern extended with `nifty|sensex|shanghai` and
  `sse\s*(composite|index)`.
- `identity.py` — **NIFTY 50 (`^NSEI`), SENSEX (`^BSESN`), SSE Composite
  (`000001.SS`, not obsolete `^SSEC`)**.
- `providers/index_quote.py` — `_chart` guard allows `^`-prefixed symbols plus the one
  caret-less `000001.SS`; labelled `delayed`.
- `service.py` — `_companies_house_should_refuse` tuple extended to
  (`US`,`IE`,`CA`,`AU`,`DE`,`FR`,`JP`,`IN`,`CN`).

### Configuration
- `.env.example` already carried `DBNOMICS_API_BASE_URL` and `YAHOO_INDEX_API_BASE_URL`;
  **no new variables and no new keys are required** for any of the ten countries'
  statistics, policy, fiscal, FX or index coverage (unlike company financials/filings,
  see F).

## D. Verification

**Offline tests:** `tests/test_five_more_countries.py` (47 tests) — country aliases,
WEO units table, outturns-only GDP/unemployment, per-capita indicator selection, OECD-vs-WEO
unemployment routing, policy-rate sources (incl. India→None), fiscal subject selection for
the new five and its refusal for the original five, `fetch_stats` fiscal-before-WDI
precedence (deficit/revenue/debt answered by WEO, WDI never called; original-five debt
stays on WDI), NIFTY/SENSEX/SSE identity + INTENT_INDEX, SSE Composite provider guard,
Companies House cross-country guards, CPI phrase routing.

**Full suite:** `1025 passed, 10 skipped` (0 failures).

**Live verification (2026-09-29):**

| Category | Query | Provider / series | Value |
|---|---|---|---|
| GDP | Japan GDP, China GDP | IMF WEO NGDPD (outturns only) | 4,026.2 / 18,748.0 bn USD (2024) |
| GDP growth | China GDP growth | IMF WEO NGDP_RPCH (outturns only) | 5.0% (2024) |
| GDP per capita | Germany/France/China GDP per capita | IMF WEO NGDPDPC | 54,989.76 / 46,203.68 / 13,312.70 USD (2024) |
| CPI | Germany/China inflation | IMF CPI all-items | 2.0% / 0.02% (2025-07) |
| Unemployment | India/China; Japan | WEO LUR (2024 outturn); OECD MEI (2023-12) | 4.9% / 5.1%; 2.4% |
| Policy rate | Japan; China; Germany/France | IFS FPOLM_PA; ECB deposit facility | 0.5% (2025-07); 1.4% (2025-06); 0.0% (2026-07) |
| Govt debt | China; Japan "general government central debt" | WEO GGXWDG | 88.3% (2024) of GDP |
| Deficit | Germany budget deficit | WEO GGXCNL_NGDP | −2.8% of GDP (2024) |
| Revenue | France government revenue | WEO GGR_NGDP | 51.4% of GDP (2024) |
| Trade balance | Germany/China/Japan | WDI NE.RSB.GNFS.ZS | 2.36% / 4.19% / −0.89% of GDP |
| Current account | Japan/France/India | WDI BN.CAB.XOKA.GD.ZS | 4.86% / −0.27% / −0.42% of GDP |
| FX | EUR/USD, EUR/JPY, EUR/CNY, EUR/INR, USD/INR | Frankfurter (ECB reference rates) | 0.8789; 178.5; 7.6352; 109.21; 95.98 (2026-09-28) |
| Indices | NIFTY 50; SENSEX; SSE Composite; DAX; CAC 40; Nikkei 225 | index_quote (delayed) | 22,685.35; 72,429.26; 3,830.45; 25,478.53; 8,092.19; 65,481.27 |
| Country guard | German registry filings; Japan filings; UK Hargreaves | `_companies_house_should_refuse` | True / True / False (UK kept) |

One regression found by the routing probe and fixed (section B #2); the per-capita
conflation (B #4) was also found live and is pinned by a test. The India policy-rate
"no source" is intentional (B #5 / E).

## E. Deliberate decisions

- **Fiscal-first beats WDI for the new five.** A fiscal question about Germany to China
  resolves to WEO general-government measures (gross debt / net lending / revenue as
  % of GDP); the original five keep their WDI central-government paths untouched. This
  is a guard against the confirmed wrong-statistic outcomes in section A.
- **WEO projections are never served as history.** Any WEO series (GDP, per-capita,
  fiscal, unemployment) drops every period ≥ the *release* year — WEO:2025-04's 2025
  value is a projection even though 2025 is in the past.
- **India policy rate is a deliberate "no source".** IFS's India rate has been frozen
  at 6.25% since 2017-07; serving it would fabricate a current rate. The question falls
  to the web-grounded path.
- **DE/FR/JP unemployment stays on OECD MEI (2023-12).** Consistent with the first five;
  the taxonomy is "recent published outturn", not "monthly", and the same source is used
  for all seven.
- **ECB deposit facility, not MRO, as the German/French policy rate.** The deposit rate
  (0.0%) is the rate governing overnight money; IFS/German "repo" series IIRC are stale
  or panel-scoped. Arbitrary per-country wholesale-rate naming is the type of guess this
  module refuses elsewhere.
- **`000001.SS` over obsolete `^SSEC`.** Yahoo's `^SSEC` returns HTTP 404; the SSE
  Composite is served under the caret-less `000001.SS`, admitted as the single exception
  to the `^`-only index rule.
- **Index data labelled `delayed`** (as with the first five) — Yahoo does not state an
  entitlement; never claiming realtime keeps the honesty rule intact.

## F. Notes / remaining

- **Company financials & official filings for DE/FR/IN/CN have no deterministic country
  cable (and were not part of this work's keyless mandate).** The key-gated providers
  (finnhub, polygon, alpha_vantage, companies house) are present and configured in this
  repo's `.env` from the earlier market-data feature, so company questions for the five
  resolve by ticker where the identity layer can find one. But there is no *official
  national* filing source wired for DE/FR/IN/CN: Companies House (UK) still refuses
  foreign-country filings via the guard, and Japan's EDINET could be built keyless
  (EDINET API publishes XBRL filings) but is not built. Questions that do not resolve a
  ticker flow to the web-grounded answer.
- **Corporate tax rates for DE/FR/IN/CN** have no structured series in this pipeline;
  country+tax-rate questions route to `_macro_question_refusal` → web-grounded answer.
- **AX = "Australian" vs the new five**: `_OTHER`/`_AU` patterns are unchanged; "Austria"
  does not map to Australia and remains unsupported.
- **OECD MEI unemployment staleness** (2023-12) is a source-side fact, visible in snapshots;
  IN/CN get fresher WEO outturns (2024).
- Frankfurter now mirrors ECB daily reference rates for INR, so the open.er-api fallback
  was not needed for EUR/INR or USD/INR (both served by Frankfurter/ECB on the probe day).
- `.env` still contains operator keys and must never be printed; this report contains none.