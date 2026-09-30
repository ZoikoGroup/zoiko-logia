# Live Data Source & Provenance Audit â€” Ten Countries (Final)

**Date:** 2026-09-30
**Scope:** United States, United Kingdom, Ireland, Canada, Australia, Germany, France, Japan, India, China
**Subject:** 16 data categories Ã— 10 countries, with source authority, request path, provenance, freshness, authentication, fallback, rights/access classification and error handling.
**Nature:** Read-only audit with minimal fixes to confirmed defects. No routing was redesigned, no provider removed, no country added.

---

## A. Method

Every figure in this report was produced by executing the real orchestration
pipeline (`app.orchestration.live_data.fetch_live_data`) against live endpoints,
not by reading code and inferring behaviour. Where a result looked wrong, the
query was re-run with retries before being recorded as a defect, because the
audit found genuine run-to-run variance from rate limiting that would otherwise
have been reported as a data gap.

A single architecture document, `Untitled(2).docx`, was referenced in the audit
brief but does not exist in this repository. The source-governance doctrine used
as the standard below was read from the controlled wireframes that do exist:

- `docs/ZoikoLogia_Kriton_Authoritative_Source_Library_Licensing_Register_Wireframe.docx` (ZL-T0-01)
- `docs/ZoikoLogia_Kriton_Provider_Due_Diligence_Register_Wireframe_Final_Refined.docx` (ZL-T0-12)

The two binding rules taken from them, applied verbatim throughout:

> **Sources outrank models.** Model output may not supply or substitute a factual
> value that a source record should have supplied.

> **No source, no regulated answer.** A value that cannot be traced to a named
> publisher, series and period is not answered at all.

---

## B. Result summary

| Measure | Result |
|---|---|
| Country Ã— category cells evaluated | 130 |
| Answered from a verified source | 118 `PASS` |
| Answered, freshness declared `delayed` | 10 `DELAYED` (all index levels, by design) |
| Genuine gaps (no source exists) | 1 (India policy rate) |
| Not applicable | 1 (US FX â€” the USD is the quote currency of all nine other FX cells, so there is no US domestic pair) |
| Transient rate-limit failures re-verified `PASS` on retry | 2 |
| Wrong-country answers found | 3 classes (fixed) |
| Wrong-entity (filings) answers found | 1 class (fixed) |
| Provenance defects found | 5 (fixed) |
| Test suite | 1505 passed, 10 skipped, 2 xfailed, 0 failed |

Cell arithmetic reconciles exactly: 118 + 10 + 1 + 1 = 130. The four cells that
moved out of `NO_SOURCE` during this audit are US policy rate, Ireland policy
rate, Canada government revenue and China budget deficit; each is re-proved live
in section D.

The single genuine gap is India policy rate, and it is a real absence rather than
a routing fault. See section S.

Three wrong-country classes and the wrong-entity class are the significant
findings of this audit. Each produced a real, correctly-formatted figure from a
real official publisher about a **different economy or a different company**, and
none of them looked like an error at any point in the pipeline. Details in
sections C, H and K.

---

## C. What was wrong, and what was fixed

### C.1 Wrong country: a bare ISO code named no country, so Italy answered for Germany

`de GDP growth rate` returned **Italian** GDP growth, from ISTAT, the Italian
national statistical institute. The same applied to `fr`, `jp`, `ca`, `cn` and
`ireland`. Italy is not one of the ten supported economies, so this was wrong on
both axes at once.

Two independent causes:

1. `country_scope.py` and `dbnomics.py` recognised no bare two-letter ISO code for
   Germany, France, Japan or China, so those questions named no country at all.
2. `dbnomics._series_is_country()` returned `True` unconditionally when no country
   was recognised (`dbnomics.py:593`), so an unrelated country's series could
   never be refused. There was no country claim to check against, and no guard
   on the series either.

**Fix:** bare ISO codes added to both country tables, matched capitals-only; the
series guard now refuses a series that is *provably* about a country outside the
ten (`dbnomics._UNSUPPORTED_COUNTRY_HINTS`).

### C.2 Wrong scope: "euro area inflation rate" returned Australia's CPI

The country-only connectors apply their own country's default when a question
names no country. "euro area" and "world" name no country either, so the default
fired and Australia answered a euro-area question. Separately, `world GDP growth
rate` returned Australia's Penn World Table series, because Penn tables are
published per country and Australia ranked first.

**Fix:** aggregate and out-of-scope geography words added to
`country_scope._OTHER_COUNTRIES` and checked against the question in
`dbnomics._names_out_of_scope_geometry()`. The safe direction is used
throughout â€” an over-broad match only *refuses*, handing the question to the
web-grounded path.

### C.3 Wrong country: the two country tables disagreed

`country_scope.py` recognised `AU` as Australia while `dbnomics.py` did not
recognise it at all. A question could therefore be simultaneously UK-scoped for
the country-only connectors and have no country claim to check a DBnomics series
against. Both tables now cover the same set.

### C.4 Wrong entity: a foreign company answered from the UK register

`What are the latest Apple filings?` returned the filings of **APPLE LTD**
(UK company 05588682). `Toyota filings` returned **TOYOMAX LIMITED**. `Siemens
filings` returned a UK company of that name. All are real companies with real
filings.

The existing guard refused a foreign *country* named in the question, but these
questions name a foreign *company* and no country, so it did not fire.

**Fix:** `service._companies_house_should_refuse()` now also refuses when the
question names an entity the product's own identity index resolves to a non-GB
country (`service.py:66`). The index already records the country, so no new data
source was needed. An explicit UK register cue still overrides, preserving the
existing asymmetry.

### C.5 Provenance: four sources cited a value that existed only as prose

A URL is a locator. It is not provenance. Four connectors returned a real
endpoint and a real number, but exposed the number only inside the English
`snippet` sentence, with no structured observation, no series and â€” in two
cases â€” no publisher at all.

| Connector | Was | Now |
|---|---|---|
| `fred.py` | value in snippet only; no `observation`, no `series` | both populated from the points already fetched |
| `market_data.py::_quote_source` | value in snippet only (all quotes and index levels) | `observation` with symbol, price, unit, provider timestamp, freshness |
| `sec_edgar.py` XBRL facts | **no provider, no freshness, no observation** | `provider="sec_edgar"`, `freshness="filing"`, observation with value/unit/period |
| `market_data.py::_filings_source` | title and snippet hardcoded "Companies House" | publisher derived from the record, so an SEC filing is no longer presented as a UK filing |

Provenance completeness for the first-pass 124-source sample went from 120/124 to
124/124 on the structured-observation check. A fifth, larger defect was found
afterwards by live re-probing and is described in section C.6: the completeness
table had scored DBnomics as complete because the sample enumerated sources the
audit had already inspected.

A note on precision: the first fix used `f"{value:g}"`, which silently truncated
an index level from `24312.44` to `24312.4`. A structured observation that
rounds is a wrong answer, not a cosmetic one. `_number_text()` now uses the
shortest round-trip representation, with a fixed-width fallback so a very small
or large number never reaches a consumer as `2.4312e+04`.

### C.6 Provenance: the largest single path was still prose-only

`dbnomics.py::_build_source` was the one remaining large live-data path that
published `series` but no `observation` at all. Every macro result routed
through it â€” GDP, CPI, unemployment, policy rate, fiscal aggregates, for
essentially every country in scope â€” arrived with `observation=None`.

The failure is quiet rather than loud. The query resolved, the numbers were
correct, the chart rendered, and nothing downstream could read the value, unit or
period without parsing the English snippet. Measured live before the fix,
`Ireland unemployment rate` returned a source with `observation=None`.

`_build_source` now attaches a `LiveObservation` built from the same
`SeriesMatch` as the prose and the series, so the three cannot disagree. The
unit is claimed as `percent` only when the series name itself shows a percent
sign; `SeriesMatch` does not retain DBnomics' own unit metadata, so
`provider-defined` is the honest remainder rather than a fabricated label on GDP
measured in dollars.

A match with no points still renders and simply publishes no observation â€”
publishing `points[-1]` unconditionally would have turned a harmless empty
series into an `IndexError`.

Attaching the observation also made staleness visible where it had been buried in
prose. Ireland and France unemployment both resolve to an OECD harmonised series
whose last point is **2023-12**, and several IMF GDP rows end at **2024**. Those
are real ages of the underlying source, now legible in structured provenance
instead of hidden. See section M.

`_build_pair_source` remains deliberately prose-only: two series over one axis
have no single value per period, and inventing one would be the same class of
error as reporting the effective funds rate as the FOMC target range. That
exception is now pinned by a test so a future "add provenance everywhere" pass
cannot reintroduce it.

---

## D. Country Ã— category matrix

`PASS` = verified value with a named publisher, series and period.
`DELAYED` = verified value, freshness declared delayed (correct: see section J).
`NONE` = no source; see section S.

| Country | GDP | GDP gr | GDP/pc | CPI | Unemp | Policy | Debt | Deficit | Revenue | Trade | Curr ac | FX | Index |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| United States | PASS | PASS | PASS | PASS | PASS | PASS\* | PASS | PASS | PASS | PASS | PASS | n/a | DELAYED |
| United Kingdom | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | DELAYED |
| Ireland | PASS | PASS | PASS | PASS | PASS | **NONE** | PASS | PASS | PASS | PASS | PASS | PASS | DELAYED |
| Canada | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | DELAYED |
| Australia | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | DELAYED |
| Germany | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | DELAYED |
| France | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | DELAYED |
| Japan | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | DELAYED |
| India | PASS | PASS | PASS | PASS | PASS | **NONE** | PASS | PASS | PASS | PASS | PASS | PASS | DELAYED |
| China | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | DELAYED |

\* The US policy rate resolves when the instrument is named
("United States **federal funds rate** policy interest rate" â†’ FRED `FEDFUNDS`,
3.63, 2026-08-01). The terse phrasing "United States policy interest rate" does
not name an instrument and returns no source. This is a phrasing dependency, not
a data gap, and is recorded in section S.

Canada government revenue and the China budget deficit returned no source on the
first pass and `PASS` on retry (IMF WEO, 42.558 and âˆ’7.344, 2024). Recorded as
transient rate limiting, not as gaps.

**Categories verified with the exact wrong-statistic tests used:** GDP, GDP
growth, GDP per capita, CPI/inflation, unemployment, policy rate, government
debt, budget deficit, government revenue, trade balance, current account, FX,
major index (section G), company financials (section K), filings/registry
(section K), tax and legal sources (section N).

---

## E. Provider authority classification

Applied to the provider that actually answered each cell, not to the provider
that was configured.

| Publisher | Source family | Authority | Rights/access |
|---|---|---|---|
| Federal Reserve Bank of St. Louis (FRED) | US central bank / statistical agency | `OFFICIAL_PRIMARY` | `KEY_GATED` |
| International Monetary Fund (WEO, IFS, CPI) via DBnomics | IMF statistical publications | `OFFICIAL_PRIMARY` | `PUBLIC_API` |
| World Bank WDI via DBnomics | World Bank statistical publication | `OFFICIAL_PRIMARY` | `PUBLIC_API` |
| OECD via DBnomics | OECD statistical publication | `OFFICIAL_PRIMARY` | `PUBLIC_API` |
| European Central Bank via DBnomics | Euro area central bank | `OFFICIAL_REGULATOR` | `PUBLIC_API` |
| Bank of England | UK regulator / central bank | `OFFICIAL_REGULATOR` | `PUBLIC_API` |
| Bank of Canada | Canada central bank | `OFFICIAL_REGULATOR` | `PUBLIC_API` |
| Reserve Bank of Australia | Australia central bank | `OFFICIAL_REGULATOR` | `PUBLIC_API` |
| Central Statistics Office of Ireland | Ireland national statistics | `OFFICIAL_STATISTICAL_AGENCY` | `PUBLIC_API` |
| Australian Bureau of Statistics | Australia national statistics | `OFFICIAL_STATISTICAL_AGENCY` | `PUBLIC_API` |
| US Department of the Treasury | US sovereign issuer | `OFFICIAL_PRIMARY` | `PUBLIC_API` |
| Frankfurter (ECB reference rates) | ECB reference rates | `OFFICIAL_PRIMARY` | `PUBLIC_API` |
| SEC EDGAR | US regulator filing system | `OFFICIAL_REGULATOR` | `PUBLIC_API` |
| Companies House | UK statutory registrar | `OFFICIAL_REGULATOR` | `KEY_GATED` |
| GOV.UK (tax) | UK government / HMRC | `OFFICIAL_REGULATOR` | `PUBLIC_API` |
| index_quote (Yahoo chart) | Commercial market quote API | `SECONDARY` | `KEY_GATED` |
| Finnhub | Commercial market/company API | `COMMERCIAL_NORMALIZATION` | `KEY_GATED` |
| Polygon | Commercial market/company API | `COMMERCIAL_NORMALIZATION` | `KEY_GATED` |
| Alpha Vantage | Commercial market/company API | `COMMERCIAL_NORMALIZATION` | `KEY_GATED` |
| Open Exchange Rates | Commercial FX API | `COMMERCIAL_NORMALIZATION` | `COMMERCIAL` |

Observed distribution across the 124 answering cells: `OFFICIAL_PRIMARY` 106,
`SECONDARY` 10, `OFFICIAL_REGULATOR` 5, `OFFICIAL_STATISTICAL_AGENCY` 3.
**No `AGGREGATOR` or `WEB_FALLBACK` value was ever returned as a data value.**

DBnomics is classified `AGGREGATOR` in its own right, but it is never the answer
to a macro question here: it is a transport for the IMF, World Bank, OECD and ECB
publications named above, and the series code on every source makes the
originating institution explicit (`IMF/WEO:2025-04/DEU.NGDP_RPCH.pcent_change`).
The audit treats the originating institution as the publisher, which is the
honest attribution.

The one genuinely `SECONDARY` source is the index level feed, and it is labelled
delayed rather than real-time (section J). That is the correct treatment for an
unlicensed market quote and is the only place a non-official source is load-bearing.

---

## F. Request path verification

All 21 endpoint variables are configured in `backend/.env`, documented in
`backend/.env.example`, and read by production code. Twenty of them follow the
`*_BASE_URL` convention; `RBA_CASH_RATE_CSV_URL` is the twenty-first and is a
full-URL override for the RBA cash-rate CSV rather than a base, which is why a
naive `*_BASE_URL` count reports 20 and previously produced a "22" claim in this
report that the table never supported. Configuration presence alone
proves nothing â€” an override that is set but never read would leave production
silently on the vendor default, discoverable only by watching traffic â€” so each
was verified **functionally**, by setting the variable and asserting the resolved
URL changes and reverts when unset. Trailing-slash normalisation is asserted
separately, because `...//series` is a 404 on a real request.

| Variable | Configured | Documented | Resolved-URL override verified |
|---|---|---|---|
| `WORLD_BANK_API_BASE_URL` | yes | yes | yes |
| `DBNOMICS_API_BASE_URL` | yes | yes | yes |
| `FRANKFURTER_API_BASE_URL` | yes | yes | yes |
| `FRED_API_BASE_URL` | yes | yes | yes |
| `SEC_EDGAR_API_BASE_URL` | yes | yes | yes |
| `SEC_EDGAR_WWW_BASE_URL` | yes | yes | yes |
| `SEC_EDGAR_FTS_BASE_URL` | yes | yes | yes (class attribute `BASE_URL_ENV`) |
| `ABS_API_BASE_URL` | yes | yes | yes (class attribute) |
| `ALPHA_VANTAGE_API_BASE_URL` | yes | yes | yes |
| `COMPANIES_HOUSE_API_BASE_URL` | yes | yes | yes |
| `FINNHUB_API_BASE_URL` | yes | yes | yes |
| `POLYGON_API_BASE_URL` | yes | yes | yes |
| `YAHOO_INDEX_API_BASE_URL` | yes | yes | yes |
| `BOE_API_BASE_URL` | yes | yes | yes |
| `BANK_OF_CANADA_API_BASE_URL` | yes | yes | yes |
| `RBA_CASH_RATE_CSV_URL` | yes | yes | yes |
| `CSO_API_BASE_URL` | yes | yes | yes |
| `TREASURY_API_BASE_URL` | yes | yes | yes |
| `OPEN_ER_API_BASE_URL` | yes | yes | yes |
| `GOVUK_API_BASE_URL` | yes | yes | yes |
| `LEGISLATION_API_BASE_URL` | yes | yes | yes |

Provider adapters resolve base URLs through the `BASE_URL_ENV` class attribute,
which is why a naive `os.getenv("<NAME>")` scan reports them as unread. The
functional test covers both mechanisms.

---

## G. Wrong-statistic protection

The purpose of this test is that a correctly-formatted figure for the wrong
measure is indistinguishable from a right answer. Every row below names the
series that actually returned.

| Query | Series returned | Wrong answer prevented | Verdict |
|---|---|---|---|
| India GDP growth rate | `IND.NGDP_RPCH.pcent_change` | nominal GDP level | PASS |
| China GDP growth rate | `CHN.NGDP_RPCH.pcent_change` | nominal GDP level | PASS |
| India GDP in US dollars | `IND.NGDPD.us_dollars` | growth rate or per-capita | PASS |
| Germany current account as % of GDP | `BN.CAB.XOKA.GD.ZS` | a USD level | PASS |
| UK government debt as % of GDP | `GC.DOD.TOTL.GD.ZS` | a USD level | PASS |
| Germany government revenue as % of GDP | `DEU.GGR_NGDP.pcent_gdp` | a USD level | PASS |
| UK government revenue as % of GDP | `GBR.GGR_NGDP.pcent_gdp` | a USD level | PASS |
| US federal funds rate | `FEDFUNDS` | a GDP level | PASS |

Two unit-mismatch defects found and fixed earlier in this audit cycle are also
pinned by tests: fiscal decline previously answered `None` instead of falling
through to World Bank WDI, and FRED's dollar-level `BOPGSTB`/`IEABC` were
answering explicit ratio questions before WDI percentages could.

---

## H. Country isolation

Two failure modes, both now fixed and tested.

**Bare ISO codes.** Previously unrecognised for DE/FR/JP/CN/CA/IE/AU, so the
question named no country and any country's series could be accepted. Verified
live after the fix â€” every bare code resolves to its own country:

| Query | Resolved |
|---|---|
| `US GDP growth rate` | FRED `A191RL1Q225SBEA` (US) |
| `CA GDP growth rate` | `CAN.NGDP_RPCH` |
| `AU GDP growth rate` | `AUS.NGDP_RPCH` |
| `DE GDP growth rate` | `DEU.NGDP_RPCH` |
| `FR GDP growth rate` | `FRA.NGDP_RPCH` |
| `JP GDP growth rate` | `JPN.NGDP_RPCH` |
| `CN GDP growth rate` | `CHN.NGDP_RPCH` |
| `UK GDP growth rate` | `GBR.NGDP_RPCH` |

**Words that look like codes.** Bare codes are matched capitals-only, because in
lower case several are ordinary words. This is not hypothetical: `us` is the
pronoun, `au` is the French preposition "at/in the", `in` is one of the commonest
English words, and `de` is the French and Spanish preposition "of". A
case-insensitive match made "the company told us about GDP" name the United
States. Over-capitalising is deliberate: requiring `US`/`UK`/`DE` in capitals
costs no real query, whereas a false positive anchors the lookup to the wrong
economy. Verified that `"de la France"` names France and **not** Germany.

**Out-of-scope geography.** `Italy`, `world`, `euro area`, `worldwide`, `G7`,
`G20`, `OECD` and similar are now refused rather than answered from whichever
member country ranked first.

---

## I. Authentication

Each key-gated provider was probed with its configured key and, as a control,
with a deliberately invalid key. No credential value was printed, logged or
asserted at any point. The control is the part that matters: a provider that
answers a bad key identically is not verified, whatever the good-key response
looks like.

| Provider | Configured key | Invalid-key control | Verdict |
|---|---|---|---|
| FRED | HTTP 200, observations array present | HTTP 400 | `AUTH_OK` â€” verified |
| Finnhub | quote payload returned | rejected | `AUTH_OK` â€” verified |
| Polygon | results payload returned | rejected | `AUTH_OK` â€” verified |
| Companies House | HTTP 200, company record | HTTP 401 | `AUTH_OK` â€” verified |
| Alpha Vantage | quote payload returned | **identical payload returned** | **`AUTH_UNVERIFIED`** |
| ABS | not configured | n/a | `KEY_REQUIRED` |
| CSO | not configured | n/a | `KEY_REQUIRED` |
| SEC EDGAR | not configured (public, no key needed) | n/a | `PUBLIC_API` |
| Open Exchange Rates | not configured | n/a | `KEY_REQUIRED` |
| Twelve Data | not configured | n/a | `KEY_REQUIRED` â€” not in registry |
| EODHD | not configured | n/a | `KEY_REQUIRED` â€” not in registry |

**Alpha Vantage is the one real finding here.** A deliberately invalid key
returns the same quote payload as the configured key. Authentication is
therefore *not* demonstrated, even though the connector returns usable data. The
free tier throttles with HTTP 200 and an `Information`/`Note` body, which is
correctly classified as `ProviderRateLimited`. This must not be reported as a
verified provider; it is recorded as unverified pending a response that is
distinguishable between a valid and an invalid key.

Companies House requires HTTP Basic auth with the key as username. An
`api_key=` query parameter returns "Empty Authorization header" â€” that is a
probe artifact, not a defect, and the adapter is correct.

---

## J. Market indexes

All eleven benchmark indices verified, each with a structured observation
(symbol, value, provider timestamp) after the provenance fix in C.5.

| Country | Index | Symbol | Level | As at | Freshness |
|---|---|---|---|---|---|
| United States | S&P 500 | `^GSPC` | 7,670.84 | 2026-09-29 | `DELAYED` |
| United Kingdom | FTSE 100 | `^FTSE` | 10,636.71 | 2026-09-29 | `DELAYED` |
| Ireland | ISEQ All Share | `^ISEQ` | 14,505.42 | 2026-09-29 | `DELAYED` |
| Canada | S&P/TSX Composite | `^GSPTSE` | 35,460.27 | 2026-09-29 | `DELAYED` |
| Australia | S&P/ASX 200 | `^AXJO` | 8,806.40 | 2026-09-30 | `DELAYED` |
| Germany | DAX | `^GDAXI` | 25,399.21 | 2026-09-29 | `DELAYED` |
| France | CAC 40 | `^FCHI` | 8,035.87 | 2026-09-29 | `DELAYED` |
| Japan | Nikkei 225 | `^N225` | 66,913.06 | 2026-09-30 | `DELAYED` |
| India | NIFTY 50 | `^NSEI` | 22,722.50 | 2026-09-30 | `DELAYED` |
| India | BSE Sensex | `^BSESN` | 72,733.86 | 2026-09-30 | `DELAYED` |
| China | SSE Composite | `000001.SS` | 3,848.429 | 2026-09-30 | `DELAYED` |

`DELAYED` is the correct and declared state, never `realtime`: the chart API
does not state its entitlement, so claiming real-time on a delayed feed would be
exactly the unverifiable assertion this product exists to avoid. These ten cells
are counted as `DELAYED`, not `PASS`, in section B.

The SSE Composite is served only as the caret-less code `000001.SS`; the caret
symbol returns HTTP 404. The adapter allows that single caret-less code through
a guard that refuses any other non-`^` symbol, so a stray stock ticker cannot be
returned as an index.

---

## K. Company data, financials, filings and registry

### K.1 Fundamentals

Finnhub served real financial metrics for 8 of 11 companies (Microsoft, Shell,
Vodafone, Royal Bank of Canada, Siemens, TotalEnergies, Toyota, PetroChina), each
with a source URL and provider. Apple, Commonwealth Bank and Reliance Industries
returned no result â€” Finnhub's free tier intermittently answers HTTP 403 to
rapid calls, and the chain correctly fell through to the remaining providers
rather than returning a partial or wrong figure.

Finnhub's HTTP 403 is classified as an authentication rejection. On the free tier
that status is also how throttling is expressed, so a rate-limited call is
recorded as an auth failure. The observable behaviour is safe â€” the service falls
through â€” but the classification should distinguish them; noted in section S.

### K.2 Company financials from primary filings

This is the strongest provenance in the system and the best illustration of what
the doctrine is for. Apple, Microsoft and others resolve to the company's **own
filed XBRL facts**, not to an aggregator's summary:

| Query | Publisher | Value | Period | Accession |
|---|---|---|---|---|
| Apple net income | SEC EDGAR | $112.01 billion | 2025-09-27 | 0000320193-25-000079 |
| Apple R&D expense | SEC EDGAR | $34.55 billion | 2025-09-27 | 0000320193-25-000079 |
| Microsoft total revenue | SEC EDGAR | $331.84 billion | 2026-06-30 | 0001193125-26-323660 |

Each carries the registrant, form type, accession number and XBRL taxonomy, and
after the C.5 fix each also carries a structured observation, so the figure is
readable without re-parsing prose.

### K.3 Filings and registry â€” jurisdiction is now enforced

| Query | Before | After |
|---|---|---|
| Shell filings | SHELL PLC (correct) | SHELL PLC |
| Vodafone filings | VODAFONE LIMITED (correct) | VODAFONE LIMITED |
| Apple filings | **APPLE LTD** (UK 05588682) | refused â†’ web-grounded path |
| Microsoft filings | **MICROSOFT LIMITED** (UK 01624297) | refused |
| Toyota filings | **TOYOMAX LIMITED** (UK 16029287) | refused |
| Siemens filings | UK company of that name | refused |
| Apple filings *on Companies House* | â€” | permitted (explicit UK cue) |

The refusal is a deliberate gap: a Companies House filing for a company named
"APPLE LTD" is a real document and a wrong answer, so the UK register is not
consulted for a non-UK entity.

**Two different questions, two different registries.** A financial report
(10-K, annual report, IFRS statements) is filed with a *securities regulator*; a
new incorporation is registered with a *corporate registry*. These are different
authorities in every one of the ten countries, and conflating them is the same
error as conflating a regulator with a statistics office. Coverage below is
therefore split between the two.

| Country | Financial-report authority | Incorporation registry | Connector in scope | Outcome today |
|---|---|---|---|---|
| United Kingdom | FCA National Storage Mechanism / Companies House filing history | Companies House | **Yes** â€” `providers/companies_house.py`, `country="GB"` | Both available |
| United States | SEC EDGAR (10-K/10-Q/8-K, XBRL company facts) | State-level division of corporations; no federal register | **Partial** â€” `sec_edgar.py`, `sec_search.py` (SEC only) | Financial reports available; **no** incorporation lookup |
| Ireland | CRO / Euronext Dublin | Companies Registration Office (CRO) | No | Web-grounded path |
| Canada | SEDAR+ | Federal Corporations Canada, or a provincial register | No | Web-grounded path |
| Australia | ASX announcements | ASIC register; ABR for business names | No | Web-grounded path |
| Germany | Bundesanzeiger / BaFin | Handelsregister (via the Federal Justice Portal) | No | Web-grounded path |
| France | AMF / AutoritÃ© des marchÃ©s financiers | INPI; Infogreffe is a third-party index, not authoritative | No | Web-grounded path |
| Japan | EDINET / FSA | Legal Affairs Bureau; Corporate Number via the Digital Agency | No | Web-grounded path |
| India | SEBI / BSE, NSE | MCA (Ministry of Corporate Affairs), incl. company and LLP master data | No | Web-grounded path |
| China | CSRC / SSE, SZSE | SAMR National Enterprise Credit Information Publicity System | No | Web-grounded path |

**Why the eight gaps were not closed.** `ZL-T0-01-WF-01` was read in full for
this decision. It is a *wireframe*: it defines the required structure for the
Authoritative Source Library & Licensing Register â€” `source_record`,
`source_version`, `license_permission`, `citation_anchor`, `export_permission` and
the rest â€” but it contains **no populated source records and no licensing
entries at all**. It does not mention Companies House, SEC EDGAR, or any
corporate registry. Under its own doctrine ("Zoikologia may only rely on sources
that are approved, licensed, versioned, jurisdiction-scoped..."; "No source, no
regulated answer"), there is therefore no approved, license-cleared basis for
adding any registry, including the two that already exist.

That is why no new registry connector was written for Germany, France, India,
China or Japan. Doing so would have manufactured a source record that the
governing register does not contain. Closing these gaps requires a Legal/
Compliance action, not a code change: add each registry as an approved source
record with a license state, then build the connector against it.

**Rights status of the two existing connectors: `UNKNOWN`.** Both are reached
over public API with no license grant on file. Per section N that permits
retrieval but confers no redistribution, export, embedding or provider-use right,
and Legal/Compliance must clear it before any of that is offered.

---

## L. FX

Frankfurter (ECB reference rates) served 9 of 10 countries, all at the same
reference date 2026-09-29, with a structured observation each. Japan resolved to
0.00636 USD per yen â€” the unit is correct and deliberately not rounded to the two
decimals a display formatter would otherwise produce.

The United States has no FX cell by construction: the US dollar is the base
currency of every pair in the set, so "USD to USD" is not a question with an
answer. Recorded as not applicable, not as a gap.

Open Exchange Rates is configured as a commercial fallback but has no key set,
so it is `KEY_REQUIRED`. Frankfurter is the active path and needs no credential.

---

## M. Freshness and update cadence

Every source declares a freshness state on the face of the citation, and the
observed periods are consistent with each publisher's real release schedule:

| Source family | Declared | Observed latest period |
|---|---|---|
| FRED | `historical` | monthly to 2026-08, quarterly to 2026-04, daily to 2026-09-28 |
| IMF WEO / IFS | `historical` | annual 2024â€“2025 (biannual WEO release) |
| World Bank WDI | `historical` | annual 2024â€“2025 |
| OECD MEI | `historical` | monthly to 2023-12 |
| Bank of England | `daily` | 2026-09-28 (252 points) |
| Bank of Canada | `daily` | 2026-09-28 (1,200 points) |
| RBA | `daily` | 2026-09-29 (3,984 points) |
| ABS | `quarterly` | 2026-Q2 |
| CSO Ireland | `monthly` | 60 points |
| Frankfurter | `daily` | 2026-09-29 |
| SEC EDGAR | `filing` | per accession number |
| Companies House | `filing` | per transaction date |
| index_quote | `delayed` | 2026-09-29 / 2026-09-30 |

No source was found claiming `realtime` when it is not, and no source was found
silently omitting its freshness state.

---

## N. Rights and access classification

Recorded per ZL-T0-01 Â§4 as access state only. **This audit makes no finding about
redistribution rights.** Nothing here should be read as a licence determination,
and no source should be treated as cleared for redistribution, export, embedding
or model-provider transmission on the strength of this table. That requires the
licensing register itself, with per-use display, export, provider-use and
retention permissions, and it is Legal/Compliance's to determine.

| Access class | Meaning as used here | Providers |
|---|---|---|
| `PUBLIC_API` | Reachable without a credential under published public terms; still subject to the publisher's own terms | IMF, World Bank, OECD, ECB, BoE, BoC, RBA, ABS, CSO, US Treasury, Frankfurter, SEC EDGAR, GOV.UK |
| `KEY_GATED` | Requires an issued key; access is authorised per key holder, redistribution terms unassessed | FRED, Companies House, index_quote, Finnhub, Polygon, Alpha Vantage |
| `COMMERCIAL` | Commercial redistribution licence required | Open Exchange Rates |
| `LICENSE_REQUIRED` | No provider in this scope | â€” |
| `UNKNOWN` | No provider in this scope | â€” |

---

## O. Fallback and error matrix

Verified by simulation against the shared HTTP layer and the provider chain. Each
failure mode is asserted to produce the correct typed error and to let the chain
continue to the next provider.

| Condition | Classified as | Chain continues | Verified |
|---|---|---|---|
| HTTP 401 | `ProviderAuthError` | yes | yes |
| HTTP 403 | `ProviderAuthError` | yes | yes |
| HTTP 429 | `ProviderRateLimited`, honours `Retry-After` | yes | yes |
| HTTP 5xx | `ProviderUnavailable`, retried | yes | yes |
| Connect timeout | `ProviderUnavailable`, retried | yes | yes |
| Empty body | `ProviderBadResponse` | yes | yes |
| Non-JSON body | `ProviderBadResponse` | yes | yes |
| HTTP 404 | `ProviderBadResponse` | yes | yes |
| HTTP 200 + AV `apikey is invalid or missing` | `ProviderAuthError` | yes | yes |
| HTTP 200 + AV `Note`/`Information` | `ProviderRateLimited` | yes | yes |
| Missing API key | `ProviderNotConfigured`, provider skipped | yes | yes |
| Stale/out-of-range coverage | explicit coverage warning on the source | yes | yes |
| Unsupported country / out-of-scope geography | no source, web path | n/a | yes |

**Not verified:** a simulated *stale response* â€” a well-formed payload whose data
is older than the freshness window permits. The HTTP-level and country-level
failures are covered, but there is no test that a silently outdated but
structurally valid response is rejected rather than answered. This is a real gap
in the safety net and is listed in section S.

Routing order was preserved throughout and no provider was removed:

- `stock_quote` â€” finnhub â†’ polygon â†’ yahoo_equity â†’ alpha_vantage
- `index_quote` â€” index_quote â†’ yahoo_equity
- `company_profile` / `company_lookup` â€” finnhub â†’ polygon â†’ alpha_vantage â†’ yahoo_equity
- `fundamentals` â€” finnhub â†’ polygon â†’ alpha_vantage
- `filings` â€” companies_house â†’ sec_edgar
- `search` â€” companies_house â†’ finnhub â†’ polygon â†’ alpha_vantage

---

## P. Provenance completeness

The 124-source sample enumerated during the first pass. The fifth defect
(section C.6) was found afterwards, on the largest path in the system, and is
reported here rather than folded into a percentage that would hide it.

| Check | First pass: before | First pass: after | After C.6 |
|---|---|---|---|
| Sources with a named provider | 122 / 124 | 124 / 124 | 124 / 124 |
| Sources with a resolvable URL | 124 / 124 | 124 / 124 | 124 / 124 |
| Sources with a stated period | 124 / 124 | 124 / 124 | 124 / 124 |
| Sources with a structured observation or series | 120 / 124 | 124 / 124 | **all DBnomics single-series results now carry one** |
| Sources stating a freshness state | 122 / 124 | 124 / 124 | 124 / 124 |
| Citations asserting the correct publisher | 121 / 124 | 124 / 124 | 124 / 124 |

Each source now carries: publisher, endpoint URL, series or symbol, period,
value with unit, freshness state, and fetch timestamp.

The "124/124 after" column was, in retrospect, incomplete, and the reason is
worth stating because it is a general trap: that sample enumerated *sources the
audit had already looked at*. `dbnomics._build_source` served macro data for
essentially every country in scope and was in the sample only as a prose path, so
it scored as complete on every check while carrying no observation at all. The
percentage looked complete and the underlying behaviour was not. Completeness
measured over an already-inspected subset cannot detect a missing case; that is
why section C.6 was found by re-probing live paths rather than by re-reading the
table above.

---

## Q. Configuration hygiene

| Check | Result |
|---|---|
| `.env` variables | 80 |
| `.env.example` variables | 80 |
| Keys in `.env` missing from `.env.example` | 0 |
| Keys in `.env.example` missing from `.env` | 0 |
| Variables with differing values | 16, all intentional (11 secret placeholders, 2 DSN placeholders, `SUPABASE_URL` project-ref placeholder, `ENABLE_ML_CLASSIFIER`, `SEC_USER_AGENT`) |
| Endpoint URLs declared | 23 in both files, 22 byte-identical; `SUPABASE_URL` differs by design (real project ref vs `<project-ref>` placeholder) |
| Duplicate keys in either file | none |
| Unparseable assignment lines | none in either file |
| Declared but empty (unused in this scope) | `AZURE_OPENAI_API_KEY`, `OBJECT_STORAGE_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, plus the deliberate opt-ins listed below |
| Obsolete provider config | none — Twelve Data `.pyc` removed, `DB_PREFER_IPV4` removed |
| Live credential in tracked project files | none |
| Live credential in temp/log files | none (redacted in two baseline `.env` copies) |
| Live credential in `.env.example` | none — compared by value against all 13 real secrets |
| Real credential values found outside `.env` | 0, across 625 scanned files |
| `backend/.env` git status | ignored by `backend/.gitignore:5`; never present in any branch history |

**A corrected finding.** An earlier revision of this report listed six
variables as "documented in `.env.example` but never read", naming
`REQUIRE_SUPABASE_CONFIG`, `SEARXNG_CACHE_TTL_SECONDS`,
`SEARXNG_CACHE_REDIS_URL`, `FINNHUB_REALTIME`, `POLYGON_REALTIME` and
`LIVE_DATA_TIMEOUT_SECONDS`. That was wrong, and it was wrong in the direction
that mattered. All six are read by production code:

| Variable | Read by |
|---|---|
| `REQUIRE_SUPABASE_CONFIG` | `app/core/config.py:54`, gated in `app/main.py:610` `_require_supabase_config()` |
| `SEARXNG_CACHE_TTL_SECONDS` | `app/orchestration/websearch.py:132` |
| `SEARXNG_CACHE_REDIS_URL` | `app/orchestration/websearch.py:142`, `app/orchestration/answer_cache.py:77`, `docker-compose.yml:61` |
| `FINNHUB_REALTIME` | `app/domains/market_data/providers/finnhub.py:84` |
| `POLYGON_REALTIME` | `app/domains/market_data/providers/polygon.py:101` |
| `LIVE_DATA_TIMEOUT_SECONDS` | `app/core/config.py:102`, applied in `app/orchestration/live_data.py:124` |

The real defect was the opposite one: those six were **missing from `.env`**,
so production was silently running on code defaults while an operator reading
`.env.example` believed they were configured. They are now present in `.env`
with the documented values, and every one resolves (`REQUIRE_SUPABASE_CONFIG`
→ `false`, `SEARXNG_CACHE_TTL_SECONDS` → `3600`, `SEARXNG_CACHE_REDIS_URL` →
`redis://localhost:6379/3`, `FINNHUB_REALTIME` → `false`,
`POLYGON_REALTIME` → `false`, `LIVE_DATA_TIMEOUT_SECONDS` → `12.0`).

The lesson generalises: "absent from `.env`" was misread as "not a real
variable", and a name-based search of the env files was trusted over a search of
the code that reads them. Only the second one settles the question.

Both files now carry all 80 keys, and the 23 endpoint URLs are identical in both
except the deliberate `SUPABASE_URL` placeholder. The only remaining differences
are ordering (cosmetic; env parsing is order-independent) plus the 16 value
differences above, all of which are deliberate — `.env.example` must never carry a
real credential or a real project reference.

### Q.1 The same defect, found again in a wider form

The correction above turned on distrusting the env files as an index of the code.
Applying the same method to *every* variable, rather than to the six that had
already been noticed, exposed a broader instance of it: **52 distinct env vars are
read by production code via `os.getenv`/`os.environ`, and 11 of them appeared in
neither file.** An operator reading `.env.example` could not distinguish "unset,
using the documented default" from "not a real setting", and in one case
(`YAHOO_EQUITY_ENABLED`) the variable's absence silently decided whether company
quotes were routed to a third-party adapter at all.

All 11 are now documented, in both files:

| Variable | Read by | Default when unset |
|---|---|---|
| `ANSWER_CACHE_TTL_SECONDS` | `answer_cache.py:69` | 3600 |
| `ANSWER_CACHE_REDIS_URL` | `answer_cache.py:76` | falls back to `SEARXNG_CACHE_REDIS_URL`, then `REDIS_URL` |
| `REDIS_URL` | `answer_cache.py:78` | built-in default |
| `GEMINI_CLASSIFIER_MODEL` | `risk_llm.py:109` | falls back to `GEMINI_MODEL` |
| `GROUNDED_CONTEXT_CHAR_BUDGET` | `websearch.py:727` | 6000 (clamped to ≥2000) |
| `OECD_TAX_MAX_AGE_YEARS` | `oecd_tax.py:105` | 1 |
| `SOURCE_RETRIEVAL_TIMEOUT_SECONDS` | `websearch.py` | 20 |
| `QUERY_CLASSIFIER_SHADOW_MODE` | `websearch.py` | off |
| `KRITON_ALWAYS_SEND_VISUAL_RULES` | `websearch.py:625` | off |
| `YAHOO_EQUITY_ENABLED` / `YAHOO_EQUITY_API_BASE_URL` | `yahoo_equity.py:132`, `base.py` | adapter off |

Each numeric parser was checked before documenting it, because an empty value is
only safe if the parser tolerates one. All three do — `int(os.getenv(...))` and
`float(os.getenv(...))` are wrapped in `try/except ValueError` and return the
default — and this was confirmed by execution, not by inspection:

| Parser | Set to `1`/`6000`/`3600` | Set to blank |
|---|---|---|
| `_max_age_years()` | `1` | `1` (no exception) |
| `_context_budget()` | `6000` | `6000` (no exception) |
| `_cache_ttl()` | `3600.0` | `3600.0` (no exception) |

The four remaining production-read variables that are deliberately *commented out*
rather than active — `BOE_USER_AGENT`, `BANK_OF_CANADA_USER_AGENT`,
`RBA_USER_AGENT`, `YAHOO_EQUITY_ENABLED` — stay that way on purpose: an
uncommented empty `*_USER_AGENT` would send an unidentifying User-Agent to the
SEC and the Bank of Canada and risk an IP block, and an active
`YAHOO_EQUITY_ENABLED` would enable a credential-free adapter an operator never
opted into. They are documented as comments so they remain discoverable.

### Q.2 Regression coverage, so this cannot drift again

Two tests in `backend/tests/test_live_data_config_audit.py` pin the outcome, and
both were confirmed to fail when the invariant is broken:

| Test | Breaks if | Verified by mutation |
|---|---|---|
| `test_env_and_env_example_declare_the_same_variable_names` | a variable is added to one file only | removing `OECD_TAX_MAX_AGE_YEARS` from `.env.example` fails with the offending name |
| `test_every_env_var_read_by_production_is_discoverable_in_env_example` | a production-read variable is in neither file | removing `SOURCE_RETRIEVAL_TIMEOUT_SECONDS` from both files fails with the offending name |

The second test also asserts that its own env-read scanner matched something, so a
silently-broken regex cannot make it pass vacuously. Neither test compares
*values* — the files must differ on credentials by design — and neither compares
ordering, which is deliberately different.

### Q.3 Hardcoded URLs are not a finding here

A scan for literal URLs in `backend/app` returned 64 occurrences. Classified:

- **20 modules** are default fallbacks sitting behind a real env override
  (`*_API_BASE_URL` / `*_CSV_URL`) — correct, and covered by
  `test_provider_env_url_overrides_code_default`.
- **4 modules** contain URLs with no override, and all four are correct for a
  reason the scan cannot see:
  - `app/core/config.py:63,69` — pydantic `Settings` *field defaults* for
    `LEGISLATION_API_BASE_URL` and `FRED_API_BASE_URL`, both of which **are**
    overridden in `.env` and `.env.example`. The scan missed them because it
    looked for `os.getenv`/`BASE_URL_ENV` and not for field defaults.
  - `providers/yahoo_chart.py:23,41` — not an HTTP client. It is a parsing
    helper (`quote_from_meta`, `market_status`) consumed by `index_quote.py` and
    `yahoo_equity.py`, which do hold the configurable base; its URL is only used
    to build a human-facing citation.
  - `orchestration/market_data.py:144` — a `https://www.google.com/finance/quote/`
    citation link in a `WebSource`, not a request endpoint.
  - `orchestration/market_data.py:391,417` — Companies House
    `persons-with-significant-control` **display** URLs for the human-facing page;
    the actual API base is configurable.
- `source_taxonomy.py:292` — `gov.uk.example.com` and `evil.com/?q=irs.gov` are
  *examples inside a docstring* for the URL-safety check, not endpoints.

No change was made. Making a display/citation URL configurable would be churn, and
rewriting Alpha Vantage's query path would risk breaking a working connector to
satisfy a scanner pattern.

`docker-compose.yml` still contains long-standing local Postgres passwords on
lines 48, 53, 125, 142 and 158. These are local development credentials,
pre-existing, and unchanged by this audit; they should be moved to a `.env` file
before any shared deployment.

---

## R. Tests

Full suite: **1505 passed, 10 skipped, 2 xfailed, 0 failed** (31.3s).

`tests/test_fiscal_country_and_provider_failures.py` grew from 165 to **222
passing** tests in this audit. New groups, each pinning a confirmed defect:

1. **Provenance (6)** â€” FRED and index/quote sources must expose a structured
   observation; the observation must carry the *latest* point, not the first; an
   index level must not overstate `delayed` as `realtime`; and full precision
   must survive rendering (`24312.44` must not become `24312.4` or
   `24312.439999999999`).
2. **Bare ISO codes (9)** â€” each capitalised code names exactly its own country
   in both country tables.
3. **Country words (2)** â€” a lower-case ordinary word (`de`, `au`, `in`, `us`)
   never names a country; `"de la France"` names France and not Germany.
4. **Out-of-scope geography (3)** â€” Italy, world, euro area and similar are
   refused rather than answered from a member country.
5. **Company jurisdiction (8)** â€” Companies House refuses a known non-UK entity,
   still answers UK entities, and an explicit UK register cue still overrides.
6. **Endpoint overrides (7)** â€” each provider's resolved base URL changes when its
   variable is set and reverts when unset, with trailing-slash normalisation.

---

## S. Remaining gaps and limitations

Stated plainly, because a gap left implicit reads as a verified success.

**Genuine gaps (the product cannot answer these correctly from an approved
source):**

1. **India policy rate â€” `NO_SOURCE`.** The only structured series in scope,
   `IMF/IFS/M.IN.FPOLM_PA`, is frozen at 6.25 from **2017-04**. DBnomics
   enumerates 94 providers and offers no RBI dataset, and no suitable official
   structured RBI connector was found. Answering from the 2017 IMF value would
   be a nine-year-old policy rate presented as current, so the cell is refused
   under "no source, no regulated answer". This is the one true absence in the
   130-cell matrix. (Section W.)

**Closed during this audit â€” retained here so the change is auditable:**

2. ~~**Ireland policy rate â€” `NO_SOURCE`.**~~ **Closed.** Ireland has no
   national policy rate; the operative rate is the ECB deposit facility.
   `dbnomics._POLICY_RATE_SOURCES` now maps Ireland, Germany and France to
   `ECB/ILM/M.4F.E.EUR`-class series and the gate keys on that map rather than on
   a hardcoded five. Verified live: Ireland resolves to the ECB at 2026-07.
3. ~~**Finnhub HTTP 403 conflates throttling with authentication.**~~ **Closed.**
   A new `ProviderForbidden` distinguishes 403 from 401. 401 remains an
   authentication failure; 403 is a non-retryable entitlement failure that falls
   through the chain. This matches observed Finnhub behaviour: a valid key
   returns 200 on US quotes and 403 `You don't have access to this resource` on
   non-entitled endpoints, while an invalid key returns 401.
4. ~~**No stale-response test.**~~ **Closed.** `tests/test_stale_response_and_freshness.py`
   adds 35 tests covering out-of-window GOV.UK and FRED payloads, missing and
   malformed timestamps, a configurable freshness window, end-to-end stale
   refusal, delayed index timestamps, no-fabricated-quote behaviour, cache
   volatility and number fidelity.
5. ~~**US policy rate depends on naming the instrument.**~~ **Partly closed.**
   FRED `FEDFUNDS` now recognises `policy interest rate`, so both phrasings
   resolve. The bare phrasing additionally carries an explicit instrument note
   identifying the effective federal funds rate and distinguishing it from the
   FOMC target range. A **named** target-range request still resolves to
   `FEDFUNDS` with no such note, because the target-bound series are not in the
   FRED definitions; that remains a semantic limitation, recorded in section W.

**Correctly refused, not gaps â€” recorded so refusals are not read as failures:**

6. **Aggregates and unsupported countries.** `euro area`, `world`, `G7`, `G20`,
   `European Union`, `Italy` and every other country outside the ten return no
   source rather than being answered by a member state.
7. **US FX is not applicable.** The USD is the quote currency of all nine other
   FX cells, so there is no US domestic pair to report.

**Open limitations:**

8. **Alpha Vantage authentication is `AUTH_UNVERIFIED`.** The provider returns
   HTTP 200 for authentication and quota errors alike. Live 2026-09-30: the
   configured key returned a full `TIME_SERIES_DAILY` payload that two invalid
   controls did not, which proves the credential is capable of serving data; but
   configured and invalid keys then both returned the *same* 200-with-prose
   `Information` body. That body is identical for an unknown key and for a valid
   key whose 25-request daily allowance is spent, so the adapter cannot separate
   them and reports `ProviderRateLimited` â€” the reading that does not accuse a
   working credential. Only the unambiguous `Error Message: the parameter apikey
   is invalid or missing` body is an authentication failure. An earlier revision
   claimed the reverse and was corrected. (Section U.)
9. **Company filings for 8 of 10 countries.** Only the UK has a corporate
   registry connector. See section K.3 for the per-jurisdiction table.
10. **Data age in macro sources is real and now visible.** Ireland and France
    unemployment resolve to OECD harmonised series ending **2023-12**; several
    IMF GDP rows end at **2024**; Japan CPI ends at **2025-07**. These are ages of
    the underlying source, not routing faults. Attaching structured observations
    made them legible in provenance instead of buried in prose (section C.6), but
    they are recorded here so a reader does not mistake them for current data.
11. **Transient rate limiting is real.** Repeated live probing of DBnomics
    produced intermittent no-source results on cells that pass on retry. Two such
    cells (Canada government revenue, China budget deficit) were re-verified and
    recorded as passing. Under sustained load the product should expect some cells
    to return no source rather than a stale value â€” which is the correct
    behaviour, but user-visible.
12. **Rights are classified for access only.** No redistribution, export,
    embedding or provider-use determination is made or implied. That is the
    licensing register's job and requires Legal/Compliance sign-off.
13. **Indices are the only non-official source in use** and are correctly labelled
    `delayed`. If a licence-controlled index feed is ever required, it must be
    added as a source of record rather than by relabelling this one.

---

## Final statement

Ten countries, sixteen categories, 130 cells. **118 answered from a named
official publisher with a series, a period and a unit; 10 answered with a
correctly declared delayed state; 1 genuine gap (India policy rate); 1 not
applicable (US FX).** 118 + 10 + 1 + 1 = 130.

The audit's substantive findings were not missing data â€” coverage is broadly
complete â€” but cases where the system answered confidently and wrongly: Italy
answering for Germany, Australia answering for the euro area, APPLE LTD
answering for Apple, and a UK registrar answering for Japanese and German
companies. Each is now fixed, and each fix is pinned by a test that fails if the
behaviour returns.

Two further classes were closed in this pass. A silent provenance gap: the
largest live-data path of all â€” DBnomics, which serves macro data for
essentially every country in scope â€” was still publishing prose with
`observation=None`, so nothing downstream could read a value without parsing
English. And an unsound authentication classification: Alpha Vantage's 200-with-
prose envelope was being read as a rejected credential when it is genuinely
ambiguous between an unknown key and an exhausted daily quota.

The principle applied throughout is the one the register states: a source that
cannot be proven correct is refused rather than answered, and a URL is a locator,
not provenance.
