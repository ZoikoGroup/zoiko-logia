# Kriton reliability: baseline, conversation resolver and evidence policy — 22 October 2026

Scope of this round under the Kriton Reliability Engineering specification: Phase 0 (baseline), Phase 1 (conversation resolver), the Phase 2 shortcut and reference defects, a first Phase 4 evidence-policy correction, and a Phase 7 regression and paraphrase suite. Phases 3, 5, 6 and 8, the model-assisted rewriter, source loading and the shared migration are **not done** (see "Not done").

No live model calls, no shared-database writes, no shared-setting changes, no commits. Original benchmark files are unchanged.

## Phase 0 — Baseline

| Item | Finding |
|---|---|
| Branch / commit | `Naresh-new` at `1984fa9`; dirty tree (101 modified files before this work plus untracked) |
| Running build (port 8010) | `/health/version` 200, source hash `54ef3d7e…`, captured 2026-10-22 04:33 UTC. **Does not match the current tree** (`c009e7a9…` before this round's edits), so the running server does not include this work. |
| Health endpoints | `/health` and `/api/v1/health*` return 404 because no such routes exist. The defined routes `/health/live`, `/health/ready` (0.72 s) and `/health/agent` return 200. There is no health failure, only a missing route name. |
| Agent | Active, `openai/gpt-oss-120b`, 7 tools. **Tavily web search paused: HTTP 432 "exceeds your plan's set usage limit".** Web evidence is unavailable until the plan is restored. |
| Budgets | `AGENT_MAX_REQUEST_TOKENS=8000` (input + output), `AGENT_MAX_COMPLETION_TOKENS=4096`, `AGENT_MAX_STEPS=8`, `AGENT_MAX_SECONDS=75` |
| Shared DB | Alembic `z5s6t7u8v9w0`, head `a6t7u8v9w0x1`; `conversation_turns` table absent |
| Baseline tests (offline) | 3,362 passed, **1 failed** (`test_production_standard_path_uses_compact_grounding`: compact prompt 8,545 chars > 6,000), 13 skipped, 2 xfailed |
| Benchmarks | All tracked `backend/evals/*.json` unchanged against git (agent 50, baseline 30, India GST 15, intelligence 13, session 59, UK VAT 32 + holdout 20). No single file numbered 1–178 was found; the cases are preserved as they stand. |
| Fixture | `backend/tests/fixtures/reliability_20261022.json`: the 22 Oct transcript's user messages verbatim, assistant replies summarised, expected answers derived by hand, two paraphrases per follow-up, root-cause tags |

## Root-cause-to-test matrix

| ID | Root cause | Change | Tests (`tests/test_reliability_conversation_resolution.py`) | Status |
|---|---|---|---|---|
| RC1 | Earlier turns reached the model only through a narrow phrase gate; 10/10 scenario follow-ups lost their scenario | New `conversation_resolver.py`; all six gates in `service.py` use it (retrieval query, history clearing, remembered calculation, planner, prompt history, request relation) | `…linked_to_its_own_scenario_only` (30 cases: 10 originals + 20 paraphrases); scenario-only recognition (9); figure provenance; topic change; new self-contained question; conjunction false positive; end-to-end prompt capture (3) | Fixed offline |
| RC2 | Naming a framework (or "tax" with a supplied rate) forced sentence-level citation; ASC/AICPA hold 0 passages | `requires_authoritative_evidence(question, context)` exempts applying a framework to a supplied scenario; one `authority_required` decision drives prompt, claim check and release. "Current vs deferred" / "current tax expense" no longer read as a rate lookup | 10 follow-ups not strict; 6 controls stay strict (current threshold, PF/ESI, GSTR due date, s.179 limit, unsupplied tax rate, deferred tax without a rate); end-to-end deferred-tax prompt has no citation rule | Fixed offline |
| RC3 | 8,000-token combined request budget truncates long answers | Not changed (shared setting; needs approval) | — | **Open** |
| RC4 | Calculator blocked on a figure the user supplied ("straight-line depreciation is $70,000") | Dispatch-level guard in `calculate_from_query` for every formula; depreciation also reads "cost/costing/purchased for $X" | supplied figure not blocked; real request still asks; two phrasings now compute 9,000; end-to-end deferred tax not a clarification | Fixed offline |
| RC5 | "Journal entries to record…" read as a reference to existing entries; oldest message quoted | `supplied_context.py`: production requests excluded; newest message named | 3 wordings not blocked; real reference still checked and names latest message | Fixed offline |
| RC6 | `conversation_turns` migration missing in shared DB | Not applied (shared DB; needs approval) | — | **Open** |
| — | Figure verifier removes correct derived figures (42,123.64; 75 %/90 %) and withholds the explanation | Not changed this round (Phase 3/6) | — | **Open** |
| — | Wrong standard / method passes (IAS 12/ASC 740 for options; Z-formula for MUS) | Not changed (Phase 3/6 accounting-concept validation) | Expected answers recorded in fixture for later evaluation | **Open** |

## Conversation resolver contract (Phase 1)

`resolve_conversation(query, history, legacy_follow_up, standalone) -> ConversationResolution`

- `kind`: `first_turn | standalone | scenario_only | follow_up`
- `relevant_turns`: history indices of the linked scenario chain (its own follow-ups and the replies to them), never an older unrelated scenario
- `facts`: every figure the request may rely on, with the turn it came from; `summary()` carries positions and figures only, no message text
- Signals: previous message was a scenario with no question (default link unless the new message is a lookup sharing nothing with it); recurring party name (company suffixes excluded); demonstrative reference (`this/these/those/the above`) to a described object, only when the message brings no money figures of its own; task request with no figures after a message that has them; short reply to the assistant's question; the existing high-confidence phrases (behaviour unchanged for those, whole history kept)
- Deterministic only. The bounded model-assisted rewriter is not built (live calls not approved); paraphrases beyond these signals may still be missed.

## Source coverage (read-only query of the shared DB)

100 registered sources: **23 have passages, 77 have none.** FASB ASC: 0 passages. AICPA practice aid: 0. No IFRS/IAS, ISA or COSO source. With web search paused, standards-based questions have no citable evidence; RC2's fix lets them be answered as labelled professional explanation instead of refused, but authority-dependent claims about those standards still cannot be sourced until licensed content is loaded.

## Test report

| Suite | Result |
|---|---|
| New reliability suite | 73 passed |
| Full offline backend (`-m "not integration and not live"`) | **3,435 passed, 1 failed, 13 skipped, 2 xfailed** |
| The 1 failure | Pre-existing at baseline, unchanged at 8,545 characters; not caused by this round |
| Regression found and fixed during the round | `test_independent_audit_question_does_not_send_old_statement_to_model` ("conclude that revenue…" misread as a reference); fixed and covered |
| Live model / HTTP / integration | **Not run** (no approval for live calls) |
| Frontend | No frontend change this round; not rerun |

## Not done

- **Phase 3:** calculation provenance and accounting-concept validation (wrong-standard and wrong-method detection; repair instead of deletion)
- **Phase 5:** task-derived budgets, truncation handling, report schema. RC3 stays open; a budget change touches shared configuration.
- **Phase 6:** independent validators and a semantic reviewer
- **Phase 7:** CI wiring and the provider-failure, long-context and chart/report families (only the conversation, routing and evidence cases are added)
- **Phase 8:** observability beyond the resolution log line and trace summary; staging and rollout
- **Model-assisted rewriting, source loading, the shared migration and a live evaluation:** each needs approval

## Release checklist and rollback

Before any live check:
1. Restart the local backend so `/health/version` reports the current tree's hash.
2. Restore the Tavily plan or accept that web evidence is unavailable.
3. Get approval and a token estimate for running the 30 fixture wordings live.

Rollback: revert these files:
- `app/orchestration/conversation_resolver.py` (new)
- `app/orchestration/service.py` (resolver wiring and `authority_required`)
- `app/orchestration/verification_service.py`
- `app/orchestration/calculation_service.py`
- `app/orchestration/supplied_context.py`
- `app/orchestration/calculations/engine.py`
- `tests/test_reliability_conversation_resolution.py` and `tests/fixtures/reliability_20261022.json` (new)

No data or configuration changes need reversing.
