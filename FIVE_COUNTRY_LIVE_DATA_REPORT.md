# Five-Country Live-Data Expansion — Final Report

## A. Problem under investigation

The live-data orchestrator (_`app/orchestration/live_data.py`_) only grounded US, UK,
European and FX/statistics questions (FRED, DBnomics, ECB/Frankfurter, BoE, GOV.UK, SEC).
The other four supported countries — Ireland, Canada, Australia — had **no dedicated
official connector**, and several "headline figure" questions for the US were either
unanswerable or answered from the wrong level:

| Question | Before | After |
|---|---|---|
| "What is the Irish inflation rate?" | DBnomics (secondary, sometimes wrong slice) | **CSO Ireland (primary publisher)** |
| "What is the Canadian policy rate?" | FRED **FEDFUNDS — the US rate**, matched via bare words "policy rate" | **Bank of Canada (own source)** |
| "What is Australia's cash rate?" | FRED/DBnomics noise | **RBA (own table F1)** |
| "Australian inflation / unemployment" | DBnomics generic search | **ABS (own Data API)** |
| "How much is the US government debt?" | FRED GFDEBTN only (quarterly, restated) | **US Treasury (daily, primary)** |
| "What is the US budget deficit?" | no/GDP-% only | **Treasury MTS (monthly, correct fiscal-month label)** |
| "What is the S&P 500 / FTSE 100 / TSX / ASX 200 / ISEQ level?" | **nothing — intent mis-bailed as educational** | **index_quote provider (keyless Yahoo chart)** |

## B. Root causes

1. **No national connectors** — the coverage-gap do-list's country block was unimplemented.
2. **FRED implicit-US leak** — `FEDFUNDS` matches the bare words "policy rate" and is an
   implicit-US series, so "the Canadian policy rate" returned the US effective federal
   funds rate: a real, correctly-formatted number for the wrong economy.
3. **Market-intent bail-out** — `detect_intent` classified "What is the S&P 500?" as an
   educational question (`what is`), so index questions returned *nothing at all*.
4. **Market fundamentals over-match** — "US government revenue" matched `INTENT_FUNDAMENTALS`
   and a provider search resolved the phrase to a company.
5. **Treasury MTS conflated row kinds and periods** — table 1 mixes discrete-month ("D"),
   Year-to-Date cumulative ("T", billions-to-trillions different) and prior-FY snapshot
   ("S") rows under the same `record_date`, and the fiscal-month label was taken from a
   different row than the date.
6. **Companies House cross-country leak** — filings questions naming CA/IE/AU/US without a
   UK cue could be answered from the UK register.

## C. Changes made

### New connectors (each keyless & primary-publisher)
- `bank_of_canada.py` — Valet series V39079 (Policy Interest Rate), step-function "latest change" reporting.
- `rba.py` — F1 cash-rate CSV, header located by the "Title" row and the value column **by name** (position-reading would silently turn the cash rate into a bond yield).
- `abs_australia.py` — ABS own Data API, national CPI (YoY) + unemployment rate, keyed by exact measure codes (not the "all" cube) and refused for the wrong slice.
- `cso_ireland.py` — PxStat JSON-stat; selects the **newest base year** statistic (rebase-safe) and the "All items" slice; period labels normalised, internal codes refused.
- `us_treasury.py` — Daily Treasury Statement (debt to the penny) + MTS table 1; **filters `data_type_cd` to "D" only**, keeps `record_date` and fiscal-month label from the *same* row, sorts by date then fiscal month; rejects any share/percent/GDP phrasing so FRED's ratios own those.
- `country_scope.py` — one shared scope guard (`is_country_scoped`, `named_countries`) for all five connectors; naming a different country is a refusal, naming two is a refusal, an unsupported country is a refusal.
- `uk_scope.py` — the pre-existing UK guard kept in its own module.

### Precendence / wiring (live_data.py)
- All five connectors fetched exactly once in the fan-out (`results[13:18]`), added to chart evidence identically to the BoE series.
- Treasury dollar figures **outrank** FRED (daily primary beats quarterly restated — a category error to show both as one series); FRED ratio phrasings stay with FRED because Treasury refuses GDP/percent/share.
- A country specialist suppresses the DBnomics/FRED mirror (`specialist_matched`), so "Ireland CPI" shows only CSO.

### Market index path
- `registry.py`: new `INTENT_INDEX` intent checked **before** the educational bail-out (only fires for named benchmarks — "what is an index" still returns None), priority `("index_quote",)`.
- `identity.py`: `resolve_index()` → closed symbol set (^GSPC, ^FTSE, ^GSPTSE, ^AXJO, ^ISEQ, +13 others), never guessed symbols.
- `providers/index_quote.py`: keyless Yahoo chart adapter; **refuses any non-^ symbol**; labelled `delayed`, never realtime; verified live for all five indices. (Earlier code comments claiming Finnhub/Alpha served indices for free were wrong and are corrected — the gates there genuinely 403/zero/reject indices.)
- `service.py`: `_companies_house_should_refuse()` — refuses foreign-country filings without a UK cue; wired into INTENT_FILINGS.
- `registry.py`: `_macro_question_refusal()` — country + macro-stat word + no company ⇒ not a market question ("US government revenue" no longer attaches a company's fundamentals).

### FRED guard
- `fred.py::_definition_for_query` now refuses when the query names any supported non-US country — even for implicit-US series — so "Canadian policy rate" can never resolve to FEDFUNDS again.

### Config (backend/.env.example)
- Added documented, keyless block for BoC, RBA, ABS, CSO, Treasury base URLs + user agents (+ optional `YAHOO_INDEX_API_BASE_URL`). No new secrets are required for any of the five countries.

## D. Verification

**Offline tests:** added `tests/test_five_country_connectors.py` (25 tests, refusal-focused) alongside the existing `test_live_data_coverage_gaps.py`.

**Full suite:** `978 passed, 10 skipped` (0 failures).

**Live verification (`fetch_live_data`), one provider per category, correct country:**

```
Canada        policy rate → Bank of Canada;  inflation → IMF;  GDP → IMF
Australia     cash rate   → RBA;             inflation → ABS;  unemployment → ABS;  GDP → IMF
Ireland       inflation   → CSO;             GDP → IMF;        unemployment → OECD
US            debt/deficit/revenue → US Treasury (dollar, fiscal-month-labelled);
              debt/gdp, trade balance, GDP growth → FRED
UK            bank rate → Bank of England;   inflation → IMF
Indices       S&P 500, FTSE 100, TSX Composite, ASX 200, ISEQ → index_quote (live levels)
```

Two regressions from the first live pass (Canada GDP and Ireland GDP/U/E returned nothing)
were **transient DBnomics outages**, not code faults — re-running produced correct IMF/OECD
sources. The Canadian-policy-rate FRED leak and the "US government revenue" market
false-positive were reproduced, fixed, and are pinned by tests.

## E. Deliberate decisions

- **No new API keys required.** Registration-gated Canada/EU statistical APIs (e.g.
  StatCan) were avoided; current coverage uses Bank of Canada's keyless Valet, the RBA
  CSV, ABS's keyless own-API, CSO's keyless PxStat and Treasury's keyless Fiscal Data —
  so the expansion needs zero new entries in `.env` for the five countries.
- Indices deliberately gated to a closed symbol set; a guessed symbol returning *some other*
  benchmark's level is the error class being designed out.
- Yahoo index data labelled **delayed** (entitlement not stated by the source) rather than
  realtime — same honesty rule as every other connector.
- Treasury reports the **single latest reported fiscal month** and says which month it is,
  rather than summing the twelve months of a fiscal year into a 12×-wrong "deficit".
- ABS M15/3/1599 codes chosen over "the whole cube" and over the female-only/level variants.

## F. Notes / remaining

- **`CENSUS_API_KEY`** was not adopted: US statistics are covered by FRED + DBnomics/IMF
  on existing keys, and the Census key needed registration (would be a *new* member of the
  disputed "keys actually added" set). American Community Survey / decennial questions
  still flow to the web-grounded path.
- Public filing APIs for CRO (IE), SEDAR+/ASIC (CA/AU) are not exposed publicly —
  Companies House (UK) and SEC (US) remain the only direct filing registries.
- GOV.UK tax pages and legislation.gov.uk connectivity issues noted previously are
  unchanged; both degrade to SearXNG rather than guessing.
- `.env` still contains operator keys and must never be printed; this report contains none.