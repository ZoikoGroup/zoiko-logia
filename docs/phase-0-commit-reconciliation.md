# Phase 0 — Naresh-new commit reconciliation

**Date:** 2026-10-01
**Scope:** the 24 commits on `Naresh-new` (`3901c3e..d8119d5`) compared with the code after the main merge (PR #31) and PR #34.

## Why

Merging `main` into `Naresh-new` resolved overlapping changes automatically, and features from some branch commits disappeared without any test failing. Before restoring anything, each commit was checked against the current code. This avoids reintroducing an old implementation that a later change deliberately replaced.

## Method

1. For each commit, every substantive line it added (application code, not comments) was looked up in the current file.
2. A line with no exact match was compared with the current file by similarity (≥ 75%). A close match means the line was **reworked later**, not lost.
3. Lines with no close match were checked by hand: was the feature removed, moved elsewhere, or replaced on purpose?

## Result per commit

| Commit | Feature | Present | Outcome |
|---|---|---|---|
| `07832ae` | Versioned tool registry, FX and economic tools | 90% | Present (reworked: validators, docstrings) |
| `317d58a` | Governed agent loop | 86% | Present (superseded by the `559f16b` rewrite) |
| `dc3a99e` | Green test suite, safety metrics | 99% | Present |
| `70467a1` | Dev script uses project venv | — | No app code |
| `455dd77` | Token tenant self-repair | 100% | Present |
| `7d9cafa` | LOW-risk answers without governed evidence (pm_1.1) | 78% | **Caveat text lost → restored** |
| `13ae7b8` | Risk classifier fix, learning questions | 77% | **"No sources retrieved" caveat lost → restored** |
| `ded1842` | MEDIUM general-method answers (pm_1.2) | 75% | Present (policy constant reworded) |
| `67e2639` | KaTeX typography warnings | 43% | Superseded (moved to `lib/math-delimiters.ts` by `219a543`) |
| `219a543` | All KaTeX warnings removed | 97% | Present |
| `d251aa1` | AI Safety endpoint auth, startup hardening | 98% | Present (RLS setup now wrapped in DDL retry) |
| `188a6ad` | ChatGPT-parity fixes | 71% | **Integrity refusal and follow-up calculation history lost → restored**; country aliases, prompt rules present in reworked form |
| `7e9b920` | Merge of main | — | Merge commit |
| `3c93cf1` | Follow-up crash, risk ratings | 78% | Present (reworked) |
| `6b3199b` | Evidence bundles saved, LaTeX escalations | 93% | Present |
| `38f97e9` | Chart answers (24-question run) | 87% | Present (`routeLabel` folded into main's version) |
| `1f69f7e` | Answer every question in a message | 89% | **Prompt rule lost → restored** |
| `031572d` | Chained working, own-figure charts | 100% | Present |
| `22b0e4d` | Show working, Indian grouping | 86% | **Prompt rule lost → restored** |
| `590b4ea` | Answer checker false refusals | 100% | Present |
| `bb893a5` | Per-question search, reading official pages | 94% | Present (page reader later rewritten as a streaming reader) |
| `0495cd3` | Tax computation escalation, fast-model retry | 89% | Present |
| `559f16b` | Reliable agent mode | 88% | **Arithmetic self-correction and HIGH-risk guidance lost → restored**; cause filter moved to `evidence_narrative.py` |
| `d8119d5` | Verify shown calculations, data periods | 92% | Present (arithmetic-in-scope rule reworded in `groq_adapter.py`) |

## Restored features

| # | Feature | From | Where now |
|---|---|---|---|
| 1 | Arithmetic self-correction: wrong arithmetic is corrected once before validation, instead of escalating the whole answer | `559f16b`, `d8119d5` | `service.ask_kriton`, standard composition path |
| 2 | HIGH-risk questions answered as general guidance, plus the "General guidance only" notice | `559f16b` | Prompt context and limitations |
| 3 | Fraud/concealment refusals carry the legitimate alternative (`ACCOUNTING_INTEGRITY`) | `188a6ad` | Refusal path |
| 4 | Follow-up calculations use figures from earlier turns (screened history) | `188a6ad` | `build_calculation` call |
| 5 | Answer every question in a multi-question message | `1f69f7e` | `websearch._CORE_FORMATTING` |
| 6 | Show working for every calculation; Indian grouping for rupee amounts; lead with the answer | `22b0e4d`, `188a6ad` | `websearch._CORE_FORMATTING` |
| 7 | Caveat stating what an unsourced answer rests on | `7d9cafa`, `13ae7b8` | Limitations |

## Tests

Of 188 tests added on the branch, 187 still exist; the missing one was replaced by a later registry test. The loss went unnoticed because no test exercised these seven behaviours. `backend/tests/test_restored_branch_features.py` now covers them:

- follow-up calculation with history (behaviour: no result without history, 29.6% with it);
- the integrity refusal template;
- the formatting rules;
- pipeline wiring checks for the steps that need the full `ask_kriton` stack, until the baseline evaluation harness exists.

Backend suite after restoration: 1768 passed, 13 skipped.
