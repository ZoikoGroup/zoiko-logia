# Live Data — 10 Countries: Final Validation Report

**Scope:** US, UK, Ireland, Canada, Australia, Germany, France, Japan, India, China (exactly these ten; no additions).
**Date of live verification:** 2026-09-30
**Suite status:** `1334 passed, 10 skipped, 2 xfailed, 0 failed` (36.79s), plus `165 passed, 2 xfailed` in the new regression file.
**Status vocabulary:** `PASS` `FAIL` `STALE` `NO_SOURCE` `KEY_REQUIRED` `DELAYED` `WEB_FALLBACK`.

Every value below was read from a live API response through the product's own entry points. Nothing is reconstructed from memory.

---

## A. Configuration audit

| Item | Result | Detail |
|---|---|---|
| `backend/.env` tracked? | `PROTECTED` | Not tracked; ignored by `backend/.gitignore:5` |
| `backend/.env` structure | `PROTECTED` | 65 active variables, 0 duplicates, 0 malformed lines |
| Duplicate definitions | `PROTECTED` | 19 removed in the earlier pass; 0 remain |
| `backend/.env.example` | `PROTECTED` | 0 live credentials; conflicting `GROQ_MODEL` removed; secret vars present as placeholders |
| Unused variables | `PROTECTED` | `DB_PREFER_IPV4` (no consumer anywhere) and 2 Twelve Data vars removed |
| Twelve Data remnants | `PROTECTED` | No `twelve_data.py`, no registry entry, stale `.pyc` deleted |
| Orphaned IPv4 comments | `PROTECTED` | Removed with `DB_PREFER_IPV4` |

No correctness change was made to any working provider to satisfy this audit.

---

## B. Provider registry and fallback chains

All ten providers that existed before this work are still registered, in the same priority order.

| Intent | Chain | Status |
|---|---|---|
| `stock_quote` | finnhub → polygon → yahoo_equity → alpha_vantage | `PASS` |
| `index_quote` | index_quote → yahoo_equity | `PASS` |
| `company_profile` / `lookup` | finnhub → polygon → alpha_vantage → yahoo_equity | `PASS` |
| `fundamentals` | finnhub → polygon → alpha_vantage | `PASS` |
| `filings` | companies_house → sec_edgar | `PASS` |
| `search` | companies_house → finnhub → polygon → alpha_vantage | `PASS` |

Fallback semantics verified in `service.fetch_for_intent`:

| Failure | Typed error | Chain behaviour |
|---|---|---|
| Key absent | `ProviderNotConfigured` | continue |
| HTTP 401 / 403 | `ProviderAuthError` | continue, **never retried** |
| HTTP 200 + throttle body | `ProviderRateLimited` | continue |
| HTTP 429 | `ProviderRateLimited` | retried with `Retry-After` |
| HTTP 5xx / timeout / conn error | `ProviderUnavailable` | retried, then continue |
| HTTP 200 + empty or non-JSON | `ProviderBadResponse` | stop |

`ProviderBadResponse` deliberately stops the chain: the provider answered, so the entity genuinely is not there and a second provider could only guess at a different company.

---

## C. 10 countries × 13 indicators

`HIST` below means a correct series with a published period that is not the current month (annual/quarterly national accounts, WDI outturns). It is not an error. Every cell resolved to the statistic named — no cell returned a different indicator's number.

| Indicator | US | UK | IE | CA | AU | DE | FR | JP | IN | CN |
|---|---|---|---|---|---|---|---|---|---|---|
| GDP (USD) | FRED | WEO | WEO | WEO | WEO | WEO | WEO | WEO | WEO | WEO |
| GDP growth % | FRED | WEO | WEO | WEO | WEO | WEO | WEO | WEO | WEO | WEO |
| GDP per capita (USD) | WEO | WEO | WEO | WEO | WEO | WEO | WEO | WEO | WEO | WEO |
| CPI / inflation | FRED | IMF/DBnomics | **CSO** | IMF/DBnomics | **ABS** | IMF/DBnomics | IMF/DBnomics | IMF/DBnomics | IMF/DBnomics | IMF/DBnomics |
| Unemployment % | FRED | OECD | OECD | OECD | **ABS** | OECD | OECD | OECD | IMF | IMF |
| Policy rate % | FRED | **BoE** | `NO_SOURCE` | **BoC** | **RBA** | ECB | ECB | IMF | `NO_SOURCE` | IMF |
| Govt debt % GDP | FRED | WDI | WDI | WDI | WDI | WEO | WEO | WEO | WEO | WEO |
| Budget deficit % GDP | FRED | WEO | WEO | WEO | WEO | WEO | WEO | WEO | WEO | WEO |
| Govt revenue % GDP | FRED | WEO | WEO | WEO | WEO | WEO | WEO | WEO | WEO | WEO |
| Trade balance % GDP | WDI | WDI | WDI | WDI | WDI | WDI | WDI | WDI | WDI | WDI |
| Current account % GDP | WDI | WDI | WDI | WDI | WDI | WDI | WDI | WDI | WDI | WDI |
| FX vs USD | n/a | `PASS` | `PASS` | `PASS` | `PASS` | `PASS` | `PASS` | `PASS` | `PASS` | `PASS` |
| Major index | `DELAYED` | `DELAYED` | `DELAYED` | `DELAYED` | `DELAYED` | `DELAYED` | `DELAYED` | `DELAYED` | `DELAYED` | `DELAYED` |

**Coverage: 128 of 130 cells answered. 2 `NO_SOURCE`: Ireland policy rate, India policy rate.** Neither fabricates a rate; both fall to the web-grounded path.

US is quoted in the denominators the question asked for: debt, deficit and revenue in `% of GDP` from FRED; trade balance and current account in `% of GDP` from WDI — consistent with the other nine.

---

## D. Defects found and fixed in this pass

### D.1 Current account and trade balance were answered with the GDP **level**
`live_data` calls `_find_best_series`, not `fetch_stats`. Because the question ends in "as a percentage of GDP", `_GDP_HINTS` matched and the pipeline returned the country's **nominal GDP in dollars**.

> "United Kingdom current account balance as a percentage of GDP" returned **3,644.64** — UK GDP in billions of USD, presented as a current-account percentage. Correct country, correct provider, correct formatting, wrong statistic by three orders of magnitude.

Same for trade balance, all countries. Fixed by a deterministic WDI branch scoped to exactly three verified-broken indicators (`BN.CAB.XOKA.GD.ZS`, `NE.RSB.GNFS.ZS`, `GC.DOD.TOTL.GD.ZS`). Guarded by a test asserting the set contains nothing else, so no working route can be swapped.

### D.2 `UK government debt as a percentage of GDP` returned nothing
`_find_best_series` did `return await _find_weo_fiscal_series(...)`, which correctly declines debt for the first five — so the `None` ended the path. The WDI answer (`GC.DOD.TOTL.GD.ZS`) was never consulted. Fixed by falling through instead of returning.

### D.3 FRED answered ratio questions with currency **levels**
FRED's `BOPGSTB` and `IEABC` are published in millions of dollars, but their patterns match the same words as the ratio phrasings:

> "US current account balance as a percentage of GDP" returned **−246,023** with unit "millions of dollars" — roughly 1000× too large, and a different unit from the same question asked about any other country.

FRED now declines those two series for explicit ratio requests and the question falls through to WDI in percent. Level questions ("what is the US trade balance") are unaffected.

### D.4 Alpha Vantage misclassified a rejected key
A missing/invalid key arrives as **HTTP 200** with `{"Error Message": "the parameter apikey is invalid or missing…"}`. That was mapped to `ProviderBadResponse`, which both reported a credential problem as "that ticker does not exist" and **stopped the fallback chain**. Now `ProviderAuthError`.

### D.5 Statistic gate rejected valid questions
`government revenue`, `general government revenue`, `current account`, `fiscal balance`, `budget balance` and `budget surplus` did not match `_STAT_HINTS`, which runs *before* every resolver. Revenue questions that happened to contain "GDP" fell through to the generic GDP rule and were answered with **GDP growth**. Added to the gate.

### D.6 Country-detection false positives
Bare lowercase `us` matched the English pronoun, so "the company told us about GDP" was treated as a US question. French `au` matched Australia. Bare ISO codes in `country_scope` were case-insensitive. Fixed by case-sensitivity on bare codes; `IN` and `CN` stay excluded because "in" is a preposition.

---

## E. Freshness and projection handling

| Source | Latest period | Assessment |
|---|---|---|
| FRED (US) | 2026-Q2 / 2026-08 | Current |
| BoE / BoC / RBA cash rate | 2026-09-28 / 09-29 | Current |
| ECB policy rate (DE, FR) | 2026-07 | Acceptable for a monthly series |
| ABS CPI / unemployment (AU) | 2026-Q2 / 2026-08 | Current |
| CSO CPI (IE) | 2025-12 | `STALE` — CSO release lag |
| WEO annual aggregates | 2024 outturn | `HIST` |
| WDI current account / trade | 2024–2025 | `HIST` |
| OECD unemployment | 2023-10 / 2023-12 | `STALE` — OECD LFS discontinued for these series |
| Ireland / Australia central govt debt | 2022 | `STALE` — WDI series not updated |
| ECB FX reference rates | 2026-09-29 | Current |
| Index quotes | 2026-09-29 / 09-30 | `DELAYED`, correctly labelled |

**IMF WEO projections are filtered out.** Every value from a WEO series is an outturn — years from the release year onward are dropped before the series is returned, so no forecast is ever presented as an actual.

Staleness is reported rather than hidden: CSO, OECD and two debt series carry older periods, and nothing is labelled current when it is not.

---

## F. Market index audit — 11 / 11 correct

| Country | Index | Symbol | Quote ccy | Status |
|---|---|---|---|---|
| US | S&P 500 | `^GSPC` | USD | `DELAYED` |
| UK | FTSE 100 | `^FTSE` | GBP | `DELAYED` |
| Ireland | ISEQ All Share | `^ISEQ` | EUR | `DELAYED` |
| Canada | S&P/TSX Composite | `^GSPTSE` | CAD | `DELAYED` |
| Australia | S&P/ASX 200 | `^AXJO` | AUD | `DELAYED` |
| Germany | DAX | `^GDAXI` | EUR | `DELAYED` |
| France | CAC 40 | `^FCHI` | EUR | `DELAYED` |
| Japan | Nikkei 225 | `^N225` | JPY | `DELAYED` |
| India | NIFTY 50 | `^NSEI` | INR | `DELAYED` |
| India | BSE Sensex | `^BSESN` | INR | `DELAYED` |
| China | SSE Composite | `000001.SS` | CNY | `DELAYED` |

Every quote states "Data is delayed (not real-time)" in the answer text. No realtime claim is made anywhere.

---

## G. Company-provider authentication and coverage

### Authentication

| Provider | Status | Evidence |
|---|---|---|
| FRED | `PASS` | 9 US series returned live values |
| Finnhub | `PASS` | Live response |
| Polygon | `PASS` | Live response |
| Companies House | `PASS` | Live response |
| Alpha Vantage | **Not proven** | See note |
| SEC EDGAR | `PASS` | Keyless endpoint reachable |

**Alpha Vantage — authentication deliberately left unproven.** A probe returned HTTP 200 with a complete `Global Quote` for the configured key **and for a deliberately invalid key** (same symbol, same price, same day). The response therefore cannot distinguish a valid key from an invalid one. The endpoint is reachable and the data is well-formed, but nothing in the response proves the credential is valid, so no authentication status is claimed in either direction. Separately confirmed: the free tier throttles with HTTP 200 and a prose body ("…spread out your free API requests more sparingly (1 request per second)"), which the provider correctly classifies as `ProviderRateLimited` — not as an auth failure.

### Filing coverage

| Country | Filings |
|---|---|
| UK | `PASS` — Companies House |
| US | `PASS` — SEC EDGAR |
| Germany, France, Japan, India, China | `NO_SOURCE` — no national filing connector exists |

This is a genuine capability gap, documented rather than papered over. `identity.py`'s well-known-company table holds 16 names; it maps names to identifiers but does not create a filing source for an economy that has none.

---

## H. Security status

Statuses only. No credential value appears anywhere in this report.

| Location | Status |
|---|---|
| `backend/.env` | `PROTECTED` — gitignored, never printed, never committed |
| `backend/.env.example` | `PROTECTED` — no live credential |
| All Python source | `PROTECTED` — no live credential |
| All Markdown docs (incl. both reports) | `PROTECTED` |
| Docker/Postgres credential URLs | `EXPOSED_IN_FILE` — see below |
| Full test output (4,984 bytes) | `PROTECTED` — no key, no `Authorization` header, no `apikey=` URL, no bearer token |
| Temp workspace + logs (1,642 files) | `EXPOSED_IN_FILE` → **remediated, now `PROTECTED`** |
| Log directories in project | `NOT_FOUND` |

**Files scanned:** 626 project files, 1,642 temp/log files. **Live credentials checked:** 11 (values never displayed).

### H.1 Remediated: full project copies in temp held live credentials

Two baseline worktrees under the temp directory — `baseline-madhu\backend\.env` and `baseline-main\backend\.env` — each contained **all 11 live credential values** in cleartext. They sit outside the repository, so no `.gitignore` rule covers them, and temp directories are exactly where backups, cleaners and sync tools pick things up.

Both had **19 credential values replaced with a placeholder**. Variable names and all non-secret values were left intact, so both trees still parse and any structure-checking test still works. Re-scan confirms `NOT_FOUND`.

### H.2 The one remaining `EXPOSED_IN_FILE` finding

`docker-compose.yml` carries local Postgres passwords in connection URLs (lines 48, 53, 125, 142, 158). Committed and long-standing — they pre-date this work by several commits. They are container-local development credentials, not API keys, and reach only an in-container Postgres. **Not changed:** rewriting them would break the running local stack, and rotating them automatically was explicitly out of scope. Flagged for your decision.

Every other credential-in-URL hit was a placeholder: `alembic.ini` uses `user:password@`, and `.env.example` / `RUNNING_KRITON.md` use `<project-ref>` templates.

**One credential was printed to the terminal earlier in this session** while inspecting FRED configuration. It is not in any file, and it is not reproduced here. Rotating it is your call.

---

## I. Tests

New file `backend/tests/test_fiscal_country_and_provider_failures.py` — **165 passed, 2 xfailed**.

Covers: the fiscal gate; revenue/deficit routing to their own aggregates for all ten; debt scoping preserved for the new five; current account ≠ trade balance; lowercase-`us`, French-`au` and Austria negatives; the Alpha Vantage envelope matrix; 401/403 never retried; 429, 5xx, timeout, empty and non-JSON bodies; the exact scope of `_WDI_FALLBACK_CODES`; and the FRED ratio guard in both directions.

Full suite: **1334 passed, 10 skipped, 2 xfailed, 0 failed.** The 2 `xfail` are a recorded, unpatched gap (§K).

---

## J. What was deliberately NOT changed

- No country added or removed.
- No provider replaced, removed or reordered.
- No working route swapped for a different aggregate. The WDI branch is capped at three indicators, each pinned by a test.
- No credential rotated or invented.
- No broad refactor. Every change is one of: a gate pattern, a branch that previously returned `None` early, an error classification, or a set of patterns.

---

## K. Remaining gaps

| Gap | Severity | Why not fixed |
|---|---|---|
| Ireland policy rate `NO_SOURCE` | Medium | No deterministic series; a wrong one is worse than none |
| India policy rate `NO_SOURCE` | Medium | Same |
| OECD unemployment `STALE` (2023) | Medium | OECD discontinued this LFS series; no replacement wired |
| CSO Ireland CPI `STALE` (2025-12) | Low | Publication lag, not a bug |
| Ireland / Australia central govt debt `STALE` (2022) | Medium | WDI not updated; switching to WEO for the first five would replace working routing |
| Non-English country aliases (e.g. "österreichische", "l'inflation en Autriche") | Medium | `_OTHER_COUNTRIES` covers English plus a few native forms inconsistently. Patching one language fixes nothing for the others, so this is recorded as `xfail` rather than half-fixed |
| DBnomics / FRED sources do not populate `WebSource.observation` | Low | Values are present in the snippet and fully populate `evidence`; changing it touches every connector's shape |
| FX phrased by country (`"Germany's exchange rate"`) | Low | Frankfurter keys on currency names. `NO_SOURCE` is the safe outcome; adding country→currency aliases risks spurious FX matches on ordinary country questions |
| `docker-compose.yml` Postgres passwords | Low | Breaking the local stack and rotating credentials were both out of scope |

Remediated during this pass: two temp baseline `.env` copies holding all 11 live credentials (§H.1).

---

## L. Reproduction

```
cd backend
python -m pytest -q                                   # 1334 passed, 0 failed
python -m pytest tests/test_fiscal_country_and_provider_failures.py -q
```

Live matrix, index sweep, Alpha Vantage probe and security audit were run as throwaway scripts under the temp directory and removed after use; each was read-only and printed no credential value.