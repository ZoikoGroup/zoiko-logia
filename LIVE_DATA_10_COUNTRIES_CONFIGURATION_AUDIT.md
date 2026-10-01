# Live Data Configuration Audit — 10 Countries

**Date:** 2026-09-30
**Scope:** `backend/.env`, `backend/.env.example`, provider configuration, key wiring, base URLs, routing, and live reachability for US, UK, Ireland, Canada, Australia, Germany, France, Japan, India, China.
**Countries:** unchanged. No country was added or removed.
**Secret policy:** no key, token, password, or credential value appears in this document. Credential names are referenced by variable name only.

---

## A. `backend/.env` — duplicates and incorrect configuration

### A.1 Duplicate variable definitions removed (19)

Every one of these names was defined **more than once** in `backend/.env`. In all 19 cases the two (or more) definitions carried **identical values**, so the duplicates were redundant rather than conflicting. The earliest definition was kept and the later copies removed.

| Variable | Kept at | Removed duplicate(s) |
|---|---|---|
| `OBJECT_STORAGE_PROVIDER` | storage section | later storage repeat |
| `DOCUMENT_STORAGE_BUCKET` | storage section | later storage repeat |
| `ARTIFACT_STORAGE_BUCKET` | storage section | later storage repeat |
| `SIGNED_URL_EXPIRY_SECONDS` | storage section | later storage repeat |
| `CELERY_BROKER_URL` | celery section | later celery repeat |
| `DBNOMICS_API_BASE_URL` | live-data section | later live-data repeat |
| `FRANKFURTER_API_BASE_URL` | live-data section | later live-data repeat |
| `FRED_API_KEY` | live-data section (L101) | later live-data repeat |
| `FRED_API_BASE_URL` | live-data section (L103) | later live-data repeat |
| `SEC_USER_AGENT` | live-data section | later SEC repeat (L197) |
| `COMPANIES_HOUSE_API_KEY` | live-data section | later live-data repeat |
| `FINNHUB_API_KEY` | live-data section | later live-data repeat |
| `POLYGON_API_KEY` | live-data section | later live-data repeat |
| `ALPHA_VANTAGE_API_KEY` | live-data section | later live-data repeat |
| `OBJECT_STORAGE_URL` | storage section | later storage repeat |
| `OPENAI_API_KEY` | LLM section | later LLM repeat |
| `ANTHROPIC_API_KEY` | LLM section | later LLM repeat |
| `GOOGLE_API_KEY` | LLM section | later LLM repeat |
| `AZURE_OPENAI_API_KEY` | LLM section | later LLM repeat |

That is all **19**. All carried identical values, so each was redundant rather than conflicting, and removing the later copies changed no behaviour.

**Result:** `backend/.env` now defines **65 active variables, 0 duplicates, 0 malformed lines.**

### A.2 FRED duplicates — explicit finding (as requested)

`FRED_API_KEY` and `FRED_API_BASE_URL` were each declared **twice**. This is the specific duplication most likely to cause confusion, because FRED is the only key-gated macro provider in the set while every neighbouring macro provider is keyless.

- **Canonical definition retained** in the *Exact-figure grounding* section:
  - `FRED_API_KEY` → `backend/.env:101`
  - `FRED_API_BASE_URL` → `backend/.env:103`
- The later duplicate block was removed.
- Both remaining values were verified unchanged from the original.
- `FRED_API_BASE_URL` points at the public FRED REST host; the key is passed as a **query parameter** (`api_key`), not a header. This is confirmed correct for FRED.
- **Section comment corrected.** The header at `backend/.env:89` read `Exact-figure grounding (free, keyless, public URLs)`, which was inaccurate because FRED is free but **requires a key**. It now reads `Exact-figure grounding (free publisher URLs; FRED is free but key-gated)`.

### A.3 Unused variables removed (2)

| Variable | Reason |
|---|---|
| `TWELVE_DATA_API_KEY` | No code reads it. The Twelve Data provider source was reverted in commit `4be63d6`. |
| `TWELVE_DATA_REALTIME` | Same. |

- No `twelve_data.py`, no registration in the provider registry, and the stale `twelve_data.cpython-314.pyc` artefact has since been deleted. Twelve Data is now absent from the tree entirely.
- Verified: `TWELVE_DATA_API_KEY` appears in **no** `.py` file and in **no** test.
- **No fallback was removed.** Twelve Data was already non-functional (its source was reverted before this audit), so its removal changes no routing behaviour.

### A.4 Unused variable removed after this audit (1)

| Variable | Status | Note |
|---|---|---|
| `DB_PREFER_IPV4` | **REMOVED** | Had no consumer anywhere in the codebase - no `os.getenv`, no Pydantic field, no reference. Removed from `.env` together with its orphaned IPv4 comments. It had no effect on any request. |

---

## B. `backend/.env` ↔ `backend/.env.example` drift

### B.1 Fixed in `.env.example`

| Issue | Resolution |
|---|---|
| Duplicate `GROQ_MODEL` with **conflicting** values (a stale entry at L34 plus the canonical entry later in the file) | Removed the stale L34 entry. The canonical model declaration is now the only one. This was a genuine config conflict, not merely redundant. |
| `FRED_API_KEY` / `FRED_API_BASE_URL` undocumented | Added with safe placeholders (`FRED_API_KEY=YOUR_FRED_API_KEY`, `FRED_API_BASE_URL=https://api.stlouisfed.org/fred`). |
| `YAHOO_EQUITY_ENABLED` / `YAHOO_EQUITY_API_BASE_URL` undocumented | Added as **commented** opt-in guidance, because the equity path is disabled by default. |

`.env.example` now defines **71 active variables, 0 duplicates.**

### B.2 Remaining, intentional drift

| Variable | Status | Rationale |
|---|---|---|
| `DB_PREFER_IPV4` | **removed** | Had no consumer; deleted (see A.4). |

### B.3 Example-only variables that legitimately have no `.env` entry

These are read by code and carry safe in-code defaults; `.env` does not need to set them.

`FINNHUB_REALTIME`, `POLYGON_REALTIME`, `LIVE_DATA_TIMEOUT_SECONDS`, `REQUIRE_SUPABASE_CONFIG`, `SEARXNG_CACHE_REDIS_URL`, `SEARXNG_CACHE_TTL_SECONDS`.

### B.4 Secret-leak verification (`.env.example`)

- Every populated credential value in `.env` (11 of them) was compared against **every** value in `.env.example`.
- **Result: `NONE`.** No credential value is present in `.env.example`.
- Values that *do* match are public base URLs, booleans, model-name strings, and numeric defaults — expected, and not secrets.
- `FRED_API_KEY` in the example is verified to be a `YOUR_…` placeholder.

---

## C. API key configuration (names only — no values)

| Variable | Consumed by | Reads | Status |
|---|---|---|---|
| `FRED_API_KEY` | `app/orchestration/fred.py` | yes | **PASS** (live) |
| `FINNHUB_API_KEY` | `providers/finnhub.py` | yes | **PASS** (live) |
| `POLYGON_API_KEY` | `providers/polygon.py` | yes | **PASS** (live) |
| `COMPANIES_HOUSE_API_KEY` | `providers/companies_house.py` | yes | **PASS** (live) |
| `ALPHA_VANTAGE_API_KEY` | `providers/alpha_vantage.py` | yes | **FAIL — provider rate limit** (not an auth rejection) |
| `GROQ_API_KEY` | LLM layer | yes | populated |
| `GEMINI_API_KEY` | LLM layer | yes | populated |
| `OPENAI_API_KEY` | LLM layer | yes | populated (optional provider) |
| `ANTHROPIC_API_KEY` | LLM layer | yes | populated (optional provider) |
| `GOOGLE_API_KEY` | LLM layer | yes | populated (optional provider) |
| `AZURE_OPENAI_API_KEY` | LLM layer | yes | **empty** — optional provider, correctly unset |
| `TWELVE_DATA_API_KEY` | — | no | **removed** (unused) |

### C.1 Live authentication result detail

Every authenticated provider was exercised against its real API.

| Provider | Outcome | Detail |
|---|---|---|
| FRED | **PASS** | Series fetched successfully with 20 observations. |
| Finnhub | **PASS** | Live response received. |
| Polygon | **PASS** | Live response received. |
| Companies House | **PASS** | Live response received. |
| Alpha Vantage | **FAIL** | Returned the provider's own **"call frequency limit reached"** message. This is a quota/throttle response, **not** an invalid-key response. The key is correctly named and wired; the failure is upstream rate limiting. Alpha Vantage is the **last** fallback in every chain, so this does not degrade normal answers. |

**Conclusion:** 4 of 5 authenticated providers verified working. The single failure is a provider-side quota condition on a terminal fallback provider, not a configuration defect. No key rename, misplacement, or misrouting was found.

---

## D. Base URL / endpoint verification

Every live-data URL variable was traced end-to-end: `.env` → config loader → provider module → the actual URL used in the HTTP call.

### D.1 Env override precedence verified live

Override precedence (`env` value beats the hardcoded default) was confirmed by temporarily setting each variable to a sentinel value and asserting the constructed URL contained the sentinel. Verified for:

`FINNHUB_API_BASE_URL`, `POLYGON_API_BASE_URL`, `ALPHA_VANTAGE_API_BASE_URL`, `COMPANIES_HOUSE_API_BASE_URL`, `DBNOMICS_API_BASE_URL`, `WORLD_BANK_API_BASE_URL`, `FRANKFURTER_API_BASE_URL`, `FRED_API_BASE_URL`, `YAHOO_INDEX_API_BASE_URL`.

All **9 PASS**.

### D.2 Malformed-value handling

| Case | Result |
|---|---|
| `FRED_API_BASE_URL` set to a malformed / concatenated value | **PASS** — falls back to the safe public default rather than issuing a broken request. |

### D.3 Hardcoded URLs contradicting the env variable

**None found.** No provider hardcodes a base URL that silently overrides its corresponding environment variable.

### D.4 Provider base URLs in use

| Provider | Variable | Host class |
|---|---|---|
| DBnomics | `DBNOMICS_API_BASE_URL` | public, keyless |
| World Bank | `WORLD_BANK_API_BASE_URL` | public, keyless |
| Frankfurter | `FRANKFURTER_API_BASE_URL` | public, keyless |
| Open ER FX | `OPEN_ER_API_BASE_URL` | public, keyless fallback FX |
| FRED | `FRED_API_BASE_URL` | public, **key-gated** |
| SEC EDGAR | `SEC_EDGAR_API_BASE_URL`, `SEC_EDGAR_WWW_BASE_URL`, `SEC_EDGAR_FTS_BASE_URL` | public, keyless, User-Agent required |
| Companies House | `COMPANIES_HOUSE_API_BASE_URL` | public, key-gated |
| Finnhub | `FINNHUB_API_BASE_URL` | public, key-gated |
| Polygon | `POLYGON_API_BASE_URL` | public, key-gated |
| Alpha Vantage | `ALPHA_VANTAGE_API_BASE_URL` | public, key-gated |
| Yahoo index | `YAHOO_INDEX_API_BASE_URL` | public, keyless |
| Yahoo equity | `YAHOO_EQUITY_API_BASE_URL` | public, opt-in, **no key available** |
| BoE | `BOE_API_BASE_URL` | public, keyless |
| Bank of Canada | `BANK_OF_CANADA_API_BASE_URL` | public, keyless |
| RBA | `RBA_CASH_RATE_CSV_URL` | public, keyless |
| ABS | `ABS_API_BASE_URL` | public, keyless |
| CSO Ireland | `CSO_API_BASE_URL` | public, keyless |
| US Treasury | `TREASURY_API_BASE_URL` | public, keyless |
| GOV.UK | `GOVUK_API_BASE_URL` | public, keyless |
| legislation.gov.uk | `LEGISLATION_API_BASE_URL` | public, keyless |
| SearXNG | `SEARXNG_URL` | self-hosted |

---

## E. Provider classification

Registered market-data providers, in registry order:
`companies_house`, `finnhub`, `polygon`, `alpha_vantage`, `index_quote`, `yahoo_equity`.

Resolved routing chains (unchanged by this audit):

| Intent | Order |
|---|---|
| `stock_quote` | finnhub → polygon → yahoo_equity → alpha_vantage |
| `stock_history` | polygon → yahoo_equity → alpha_vantage |
| `stock_fundamentals` | finnhub → alpha_vantage |
| `stock_company_profile` | finnhub → polygon → alpha_vantage |
| `company_filings` | companies_house |
| `company_lookup` | companies_house → finnhub → polygon → yahoo_equity → alpha_vantage |
| `index_quote` | index_quote |

**All 6 providers remain registered and every fallback remains in place.**

### E.1 Macro / official-statistics classification

| Provider | Class | Role |
|---|---|---|
| DBnomics | **PRIMARY** | Macro cross-country aggregator; general statistical fallback |
| Frankfurter | **PRIMARY** | FX (ECB reference rates) |
| World Bank | **SPECIALIZED / FALLBACK** | Cross-country WDI indicators; publisher-direct before mirrors |
| FRED | **SPECIALIZED** | US-only macro |
| SEC EDGAR | **SPECIALIZED** | US registrant filings / fundamentals |
| Companies House | **SPECIALIZED** | UK company filings |
| Bank of England | **SPECIALIZED** | UK policy rate |
| Bank of Canada | **SPECIALIZED** | Canada policy rate |
| RBA | **SPECIALIZED** | Australia cash rate |
| ABS | **SPECIALIZED** | Australia CPI and labour |
| CSO Ireland | **SPECIALIZED** | Ireland CPI |
| US Treasury | **SPECIALIZED** | US debt and fiscal data |
| GOV.UK | **SPECIALIZED** | UK tax rates and guidance |
| legislation.gov.uk | **SPECIALIZED** | UK legal text |
| Open ER FX | **FALLBACK** | FX for currencies the ECB does not publish |
| SearXNG | **FALLBACK** | web-grounded answers |
| Yahoo index | **SPECIALIZED** | keyless index levels (delayed) |
| Yahoo equity | **SPECIALIZED / DISABLED** | opt-in; requires an unavailable API key |
| Twelve Data | **LEGACY (removed)** | source reverted in `4be63d6`; no live code, no registration |

### E.2 Duplicate provider registration

**None.** No provider name is registered twice. Twelve Data is absent from the tree entirely - no source, no registration, no compiled artefact.

---

## F. Market index live verification — all 11 requested

| Index | Symbol | Country | Result |
|---|---|---|---|
| S&P 500 | `^GSPC` | US | **live, delayed** |
| FTSE 100 | `^FTSE` | GB (UK) | **live, delayed** |
| TSX Composite | `^GSPTSE` | CA | **live, delayed** |
| ASX 200 | `^AXJO` | AU | **live, delayed** |
| ISEQ All Shares | `^ISEQ` | IE | **live, delayed** |
| DAX | `^GDAXI` | DE | **live, delayed** |
| CAC 40 | `^FCHI` | FR | **live, delayed** |
| Nikkei 225 | `^N225` | JP | **live, delayed** |
| NIFTY 50 | `^NSEI` | IN | **live, delayed** |
| S&P BSE SENSEX | `^BSESN` | IN | **live, delayed** |
| SSE Composite | `000001.SS` | CN | **live, delayed** |

All 11 of the 11 explicitly requested indices returned data through `index_quote`. Symbols are taken from the authoritative `_INDEX_PATTERNS` table in `backend/app/domains/market_data/identity.py:39`. `000001.SS` is the one caret-less code in the table and is explicitly allow-listed in `index_quote.py:78` so an ordinary Shanghai-listed stock ticker can never be mistaken for the index. All values are correctly labelled **delayed** rather than real-time — Yahoo free tier, which is the accurate label.

---

## G. Code defects found and fixed

These are genuine runtime/correctness bugs, each reproduced and then covered by a regression test.

### G.1 Australia CPI raised `KeyError` — fixed

**File:** `backend/app/orchestration/dbnomics.py`, `_find_cpi_series`

- **Symptom:** `country_code = _CPI_COUNTRY_CODES[country]` raised `KeyError` for Australia.
- **Why it was hidden:** `live_data.py`'s result fan-out swallows exceptions, so the crash was invisible — Australia was only ever answered correctly *by accident*, because another connector happened to win.
- **Fix:** use `_CPI_COUNTRY_CODES.get(country)` and `return None` when absent.
- **Correct behaviour now:** Australia is deliberately recognised in `_CPI_COUNTRIES` so this connector *claims* the question (stopping a fall-through to generic full-text search, which had been returning ABS **energy** inflation instead of headline CPI) while publishing no IMF series. Returning `None` yields an honest gap that `abs_australia.py` fills from the statistical agency itself. This matches the documented intent in the adjacent comment.
- **Regression test added.**

### G.2 FRED nominal GDP claimed per-capita questions — fixed

**File:** `backend/app/orchestration/fred.py`, `GDP` series definition

- **Symptom:** the pattern's bare `GDP` alternative also matched `US GDP per capita`, so a per-capita question was answered with the **total** GDP — off by roughly three orders of magnitude, confidently formatted, with a real FRED URL attached.
- **Fix:** added a negative lookahead so the nominal-GDP definition declines `per capita`, `per head`, `per person`, and `income per`.
- **Correct behaviour now:** per-capita phrasing declines FRED and is answered by the DBnomics `NGDPDPC` resolver in `_find_gdp_series`.
- **Verified live** for US, Germany, India, and UK: per-capita now resolves to `NGDPDPC`, not total `GDP`.
- **Regression test added.**

---

## H. Country cross-contamination audit

| Finding | Severity | Status |
|---|---|---|
| A named country must be demonstrably the country answered for; DBnomics full-text search ranks on text alone and could return a real, well-formed series for a **different** country | high | **Guarded** by `_series_is_country` + `_COUNTRY_NAME_HINTS` / `_COUNTRY_ISO3`; word-boundary matching prevents a short code matching inside unrelated words |
| "Northern Ireland" series could be returned for an **Ireland** question | high | **Guarded** — explicit `northern ireland` rejection |
| "Latin America" / "North America" treated as `America` → United States | high | **Guarded** — "America" is deliberately *not* a US hint; only explicit forms match |
| `Ireland` matching "Irish Sea" shipping series | medium | **Guarded** — word-boundary matching |
| FRED answering a non-US country question (e.g. `Canadian policy rate` → US federal funds rate, since `FEDFUNDS` matches the bare words "policy rate") | high | **Guarded** — `_definition_for_query` now refuses when another *supported* country or any *unsupported* country is named, and this check runs even for implicit-US series |
| `_STAT_HINTS` does not recognise **government revenue** or **current account balance**, so `France government revenue` and `Japan current account balance` return no structured series | medium | **Reported, not changed** — verified reproducible. Closing it means new WDI/WEO indicator mappings, which is routing work and out of scope for a configuration audit. Not a regression; these phrasings were never supported. |
| Bare token `us` (case-insensitive) matches ordinary English "us" | low | **Reported, not changed** |
| French `au taux` (`at the rate of`) can match country code `AU` | low | **Reported, not changed** |

The three "reported, not changed" items are all pre-existing behaviour. None is a regression introduced by this audit, and none was fixed because doing so requires either keyword-tokeniser changes or new indicator routing — both of which would alter behaviour beyond the stated scope of preserving working routing.

---

## I. Wrong-statistic routing

| Finding | Severity | Status |
|---|---|---|
| `US government debt to GDP` contains the literal word `GDP`, so the catch-all GDP pattern matched first and returned the GDP **level** | high | **Guarded** — dedicated `GFDEGDQ188S` / `FYFSGDA188S` / `FYFRGDA188S` / `BOPGSTB` / `IEABC` definitions placed **above** the GDP definition, with load-bearing ordering documented inline |
| `budget deficit as a share of GDP` for the five later countries grabbed GDP **growth** | high | **Guarded** — `_FISCAL_HINTS` fires before the generic GDP rule in both `_find_best_series` and `fetch_stats` |
| `trade balance as a share of GDP` matched the generic GDP-growth WDI rule | medium | **Guarded** — dedicated `NE.RSB.GNFS.ZS` rule ordered before the generic rule |
| "How much is the US government debt" answered with a **percentage** instead of the dollar level | medium | **Guarded** — the level pattern `GFDEBTN` is tested before the ratio pattern; ordering is documented inline |
| India / China unemployment had no OECD MEI series (neither is an OECD member), so the OECD lookup 404s | medium | **Guarded** — routed to IMF WEO `LUR` with outturns-only filtering |
| WEO series carry IMF **projections** for the release year onward | medium | **Guarded** — release year used as a cutoff in the GDP, fiscal, and WEO-unemployment resolvers, leaving published outturns only |
| IMF WEO series codes carry a third **unit** dimension; dropping it 404s every series | high | **Guarded** — `_WEO_UNITS` map supplies exact verified units |

---

## J. Freshness and staleness

| Item | Status |
|---|---|
| IMF WEO is published as **dated releases** (`WEO:2025-04`, …) rather than rolling series | Release resolved at call time; pinning one would silently go stale. |
| WEO projections excluded | Enforced across the GDP, fiscal, and WEO-unemployment resolvers. |
| India policy rate | `None` returned by design. The IMF IFS series is frozen at 6.25% since 2017, so it is **not** presented as today's rate; the question flows to the web-grounded path. |
| Market index values | Correctly labelled **delayed** (Yahoo free tier). No real-time mislabel. |
| `YAHOO_EQUITY_API_BASE_URL` | Opt-in and disabled by default — no stale data path is live. |
| Freshness across the official-statistics connectors (BoE, BoC, RBA, ABS, CSO, Treasury) | Each fetches from the publisher's own current release; no caching layer introduces staleness. |

---

## K. Error handling and fallback behaviour

| Failure mode | Behaviour |
|---|---|
| Provider HTTP error | `raise_for_status()` → caught → that connector returns `None` → the chain advances to the next provider. |
| Provider network/timeout error | Caught; connector returns `None`; chain advances. |
| Empty / no-observation response | Guarded (`if not points: return None`); chain advances rather than reporting an empty series. |
| Malformed base URL | Falls back to the safe hardcoded default (verified for FRED). |
| Wrong-country series returned by full-text search | Now rejected by `_series_is_country`; the question is handed to a country-keyed connector instead. |
| Alpha Vantage throttle | Live-observed; because it is terminal in every chain, throttling there cannot degrade the primary answer. |

No fallback provider was removed or reordered by this audit.

---

## L. `.env` comment accuracy

| Line | Was | Now |
|---|---|---|
| `backend/.env:89` | `Exact-figure grounding (free, keyless, public URLs).` | `Exact-figure grounding (free publisher URLs; FRED is free but key-gated).` |

The original comment was inaccurate because the section's canonical `FRED_API_KEY` and `FRED_API_BASE_URL` are key-gated. All other per-provider comments (SEC, FX, GOV.UK, BoC, RBA, ABS, CSO, Treasury) were checked and correctly describe their own provider as keyless.

---

## M. Verification results

### M.1 Complete test suite — final

```
1169 passed, 10 skipped, 4 warnings in 32.69s
```

- **0 failures.**
- Regression suite added by this audit: `backend/tests/test_live_data_config_audit.py` — **123 passed**.
- Baseline before the new tests (and again after the two code fixes): `1046 passed, 10 skipped`.
- Arithmetic: 1046 + 123 = 1169. Consistent.

### M.2 Skips — all pre-existing and environmental, none related to this audit

| Count | Reason |
|---|---|
| 8 | `test_massarius_license_gate.py`, `test_massarius_tenant_scope.py`, `test_tenant_isolation.py` — require `RUN_DB_INTEGRATION_TESTS=1` with an isolated Postgres database |
| 2 | `test_query_intent_classifier.py` — require `RUN_LIVE_LLM_TESTS=1` with an LLM key |

No skip is new and no skip conceals a failure. No data-provider test is skipped — provider behaviour is covered by non-skipped tests plus the live checks recorded above.

### M.3 Other verification performed

| Check | Result |
|---|---|
| `.env` → config loader → provider → endpoint tracing | **PASS** for all live-data URL variables |
| Env override precedence over code defaults | **PASS**, 9/9 |
| Malformed URL fallback | **PASS** |
| Provider authentication (live) | **4 PASS, 1 rate-limited** |
| Market index fetch (live) | **11/11** |
| Per-capita GDP routing (live) | **PASS**, correct series for US, DE, IN, UK |
| India policy-rate refusal | **PASS** |
| Australia CPI no longer raises | **PASS** |
| `.env.example` credential leak | **PASS** — none |
| Provider registry integrity | **PASS** — 6 registered, no duplicates |
| Country count | **PASS** — unchanged at 10 |

---

## N. Files changed by this audit

| File | Change |
|---|---|
| `backend/.env` | **Not tracked** (ignored by `backend/.gitignore:5`). Removed 19 duplicate definitions, 2 unused Twelve Data variables and the unused `DB_PREFER_IPV4`; corrected the FRED section comment. Now 65 active variables, 0 duplicates, 0 malformed entries. |
| `backend/.env.example` | Removed the conflicting duplicate `GROQ_MODEL`; added `FRED_API_KEY` / `FRED_API_BASE_URL` with safe placeholders; added commented `YAHOO_EQUITY_ENABLED` / `YAHOO_EQUITY_API_BASE_URL`. 71 active variables, 0 duplicates, no credential leakage. |
| `backend/app/orchestration/dbnomics.py` | Fixed the Australia `_find_cpi_series` `KeyError` (`.get` + `None` guard). |
| `backend/app/orchestration/fred.py` | Added the per-capita negative lookahead to the nominal-GDP definition. |
| `backend/tests/test_live_data_config_audit.py` | **New.** 123 regression tests covering every issue above. |
| `LIVE_DATA_10_COUNTRIES_CONFIGURATION_AUDIT.md` | **New.** This report. |

`backend/.env` was modified but is **gitignored and untracked** — confirmed with `git check-ignore -v` and `git ls-files`. No credential was written to any tracked file.

---

## O. Remaining gaps and recommendations

Nothing below is a regression; all were either pre-existing or are deliberate design choices.

### O.1 Worth fixing

| Gap | Recommendation |
|---|---|
| `_STAT_HINTS` does not recognise **government revenue** or **current account balance**, so `France government revenue` and `Japan current account balance` return no structured series | Add WDI/WEO indicator mappings. Verified reproducible. |
| Bare token `us` matches ordinary English "us"; French `au taux` can match `AU` | Tighten `country_scope` tokenisation to avoid matching inside ordinary words. Low severity. |
| ~~`DB_PREFER_IPV4` set in `.env` with no consumer~~ | **Resolved** - removed; it had no consumer. |
| ~~Stale `twelve_data.cpython-314.pyc` in `__pycache__`~~ | **Resolved** - the artefact was deleted; no Twelve Data trace remains. |
| Alpha Vantage free-tier throttle | Since it is the terminal fallback and observed to throttle, consider whether a rate-limited final fallback is worth keeping, or use a throttling-aware retry/backoff. |

### O.2 Deliberate, and correct as-is

| Behaviour | Why it should stay |
|---|---|
| Yahoo equity disabled / keyless | An unavailable key must not silently produce an unreliable path. |
| Index quotes labelled **delayed** | Accurate for the Yahoo free tier. |
| India policy rate returns `None` | The IMF series has been frozen since 2017; an eight-year-old figure presented as current would be the worse failure. |
| Projection-year data excluded from WEO | Only published outturns should be presented as facts. |
| FRED declines non-US countries | FRED holds US series only; answering a Canadian question with US data is the exact failure mode to prevent. |
| 10 test skips | All gated behind explicit opt-in env vars, per project convention. |

---

## P. Final safety checks

| Check | Result |
|---|---|
| Any credential value written to a tracked file | **No** |
| Any credential value present in `.env.example` | **No** — verified against all 11 populated credentials |
| Any credential value in this report | **No** |
| Any credential value printed to the console during this audit | **Yes — see the note below** |
| `backend/.env` tracked by git | **No** — ignored by `backend/.gitignore:5`, confirmed with `git check-ignore -v` and `git ls-files` |
| Country count changed | **No** — still 10 |
| Provider removed from the registry | **No** — all 6 still registered |
| Fallback removed or reordered | **No** |
| Authentication weakened | **No** — FRED's country refusal guards make refusal *stricter* |
| Test failures introduced | **No** — 0 failures |

**Note on console output.** During the initial exploratory inventory of `backend/.env`, before value-masking was in place, credential values were written to the terminal transcript. They were not written to any file, and nothing was committed. The later phases used masked reads throughout. **Recommendation: rotate the affected credentials**, since a value that has appeared in any transcript or log should be treated as disclosed.

---

## Q. Conclusion

| Question | Answer |
|---|---|
| Duplicates removed | 19 duplicate `.env` definitions + 2 unused Twelve Data variables + 1 unused `DB_PREFER_IPV4`; 1 conflicting `.env.example` declaration |
| Code bugs fixed | 2 — Australia CPI `KeyError`; FRED claiming per-capita questions |
| Authentication | 4 of 5 verified live working; Alpha Vantage throttled by the provider, not misconfigured |
| URL issues | None found; 9/9 override precedence and malformed-URL fallback verified |
| Routing issues | 3 low/medium pre-existing gaps reported, none introduced; all high-severity cross-contamination and wrong-statistic traps already guarded |
| Tests | 1169 passed, 0 failed, 10 pre-existing environmental skips |
| Countries | unchanged at 10 |
| Providers / fallbacks | all preserved |
| Secrets in tracked files | none |

**Scope was honoured:** no country added, no working provider removed, no fallback deleted, and no authentication relaxed. Every change was either a verified redundancy, a verified documentation error, or a reproduced runtime bug with a regression test.