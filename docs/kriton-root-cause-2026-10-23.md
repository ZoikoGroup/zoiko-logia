# Kriton — root-cause report and reliability fixes (23 October 2026)

Isolated worktree (base `3e4792e`). Evidence: the 8011 test-server logs, the
audit records of the failing questions (read-only, `SET TRANSACTION READ
ONLY`), and offline reproduction. No model calls were made for this report.

## 1. Root causes

| # | Failure seen | Root cause (evidence) | Class | Why earlier fixes did not prevent it |
|---|---|---|---|---|
| R1 | Dividend: "not answered"; hedge #1: working only | **Run budget too small for the test server's request size.** `agent_completed.stop_reason = token_budget`; tokens_used 58,802 / 64,000 with `estimated_tokens` 28,000 / 31,689 never released. `GenerationBudget.create` reserves prompt + full completion per call; failed calls keep their reservation (`agent_budget.py`). 8011 ran 16,000-token requests and 8,192-token answers under the default 64,000 run budget. | Configuration (+ missing diagnostics) | The caps were raised for the test server without raising the run budget; nothing checked the ratio or logged retained reservations. |
| R2 | Dividend strict, "sources do not establish" | **Live-data detection by keyword.** `needs_lookup` matched "currently pays … $1.20" and "value … today (Year 0)"; `release_check.requires_authority = true`. Three detectors (`needs_lookup`, planner `_LIVE`, `latest_fx_requested`) each had their own exception lists. | Orchestration (classification) | Every fix added one more exception to one detector; the next phrasing broke another. |
| R3 | Hedge #2, TDR, CCC: step limit | **One calculation per step + searches that cannot help.** `stop_reason = max_steps` (8). Tools: knowledge base `no_data`, web `no_data`, then one `calculate` per step. The batched calculator exists but is off (`build_default_registry(batch_calculations=False)`); the plan said "Follow this plan" including searches; the governed library had already been searched before the agent ran. | Orchestration (planning/tools) | Step allowance only grew for > 800-character questions with ≥ 4 deliverables; searches were never dropped when the pre-search was empty. |
| R4 | TDR: economic-data lookup planned | "calculate the new **effective interest rate**" matched the economic-indicator pattern. | Orchestration (planning) | The supplied-rate fix covered rates the user gives, not rates to compute. |
| R5 | Hedge #2: explanation replaced by working | **Unexplained fallback.** `final_text` falls back to bare working when the arithmetic check still fails after removal or nothing is left; neither the failed lines nor the reason were logged or audited, so the exact trigger cannot be confirmed from the records. | Validation (+ missing diagnostics) | The previous fix added targeted removal but no record of why the fallback was chosen. |
| R6 | `【calculate Misstatement to materiality ratio】`, `{"expression": …}`, `\DeltaDays` | **Sanitiser limits.** `_INVENTED_MARKER` accepted 【…】 up to 30 characters (this tag has 39); no rule for calculator arguments written as JSON; `_GREEK` required a non-letter after the name. | Presentation | Each sanitiser covered the forms seen so far. |
| R7 | Level 3: "known misstatement", AS 3105; inventory: bill-and-hold reversed, lot Y excluded; hedge gain called a loss; pension PBO; segment bases; TDR loss | **Model accounting reasoning.** The arithmetic is internally consistent, so every numeric check passes. | Model reasoning / accounting knowledge | No check validates accounting method; none can, by arithmetic. |

Missing diagnostic evidence (now added, see §2): the reservation each failed
model call keeps; the agent's failed calculation lines and fallback reason.
Still missing: the exact provider error behind each failed call in the forced
final turn (logged at INFO only from now on).

## 2. Fixes (worktree only)

| Fix | Files / functions | Addresses |
|---|---|---|
| **One live-data rule.** `live_data_requested`: a time word asks for live data only when it qualifies a fact whose value the question does not give (a linking verb or the clause's own figure counts as given; periods such as "52-week" and comparisons such as "above $100" do not), is not the computed target ("value today (Year 0)"), and is not negated ("without checking …"). Used by `needs_lookup`, the planner and `latest_fx_requested`; the time words were removed from `_NEEDS_LOOKUP`. | `calculation_service.py`, `agent_plan.py`, `fx_profit.py` | R2 (class, not phrasing) |
| Computed rates ("effective/implicit/internal interest rate") are not indicator lookups. | `agent_plan.py` | R4 |
| The governed library is not searched again by the agent when the pre-search for the same question found nothing (professional-knowledge questions); the professional instruction asks for at most one search, never repeated, and few calculator calls. | `service.py` | R3 |
| `AGENT_BATCH_CALCULATIONS` setting (default **off**; the design is still under review) selects the batched calculator. | `config.py`, `model_gateway/service.py`, `.env.example` | R3 |
| Run-budget consistency warning (< 6 requests per question) and an INFO log for every reservation a failed call keeps. | `execution.py`, `agent_budget.py` | R1 diagnostics |
| Validation record: failed lines, lines still failing after removal, fallback chosen and why; audited in `agent_completed.validation`. | `agent.py`, `audit_events.py`, `service.py` | R5 |
| Sanitisers: 【…】 up to 160 characters; calculator-argument JSON (fenced or bare) removed; Greek letters before a capitalised word. | `verification_service.py`, `answer_formatting.py` | R6 |
| Isolated test server only: run budget 128,000 and the batched calculator on (`scratchpad/run_worktree_server.py`). **Not active until 8011 is restarted (needs approval).** | test-server script | R1, R3 |

Not changed: production settings, the evidence policy for genuine lookups,
citations, tenant isolation, audit history, data.

## 3. Accounting answer keys (awaiting accountant review)

Added with references in `tests/fixtures/review_questions_20261022.json`
(`review_status`); the saved wrong answers are recorded as contradictions:

| Scenario | Key points | References (to confirm) |
|---|---|---|
| Dividend | D5 2.4386; TV 60.96; value ≈ $49.21 | Gordon growth model |
| Cash-flow hedge | Dec 31: Dr derivative / Cr OCI 400,000; Feb 1: OCI 100,000 loss, cash 300,000, inventory 7,800,000; sale 9,500,000; reclassify to cost of sales | ASC 815-30-35-3, -38 (ASU 2017-12) |
| Level 3 estimate | Three approaches incl. events after the measurement date; $900,000 > $750,000; **judgmental** misstatement (not known or projected); audit committee under **AS 1301** | AS 2501.15–.27, AS 2810.13, AS 1301 |
| Inventory count | X excluded if bill-and-hold criteria met; Y included (delivered Dec 31, FOB destination); Z excluded; adjustment $130,000 | ASC 606-10-55-83 |
| Pension, segments, TDR | PBO 4,837,500; profit threshold 137,000 and external revenue 94%; TDR gain 480,000 at 0% | ASC 715, ASC 280, ASC 470-60 |
| Brazil | PPP rates; NPV ≈ +$49,839; accept (capital budgeting, not tax) | Relative PPP |

Not implemented: an accounting-method review step or a human-review route
for high-risk conclusions (hedge, TDR, pension, consolidation, audit
opinions). This needs a product decision.

## 4. Tests (executed, offline)

- New: `tests/test_pipeline_reliability_oct23.py` (live-data rule both ways;
  routing of the six retest scenarios; computed rates; budget diagnostics;
  batched-calculator setting; fallback record and its audit; leaks and
  ordinary text kept; grader catches the saved Level 3, inventory and hedge
  errors). Not covered by a test: the knowledge-base skip after an empty
  pre-search (the test pipeline has no governed library).
- Benchmarks: none of the 301 eval and fixture questions changed source
  decision; planner tools unchanged against the previous build;
  `backend/evals` byte-identical to the base.
- Full backend suite: **4,043 passed, 0 failed, 30 skipped, 22 xfailed**, under
  `TZ=Asia/Kolkata` and `TZ=UTC`. Frontend not changed in this round.

## 5. Before and after

| Scenario | Live before (3001, 23 Oct) | After, offline | Live after |
|---|---|---|---|
| Dividend | not answered (strict + token budget) | not strict; plan `calculate` only | not run |
| Hedge | working only (token budget / step limit) | not strict; no repeat KB search; fallback recorded | not run |
| TDR | working only (step limit) | no indicator lookup | not run |
| Cash conversion cycle | ✅ full answer | unchanged | ✅ (23 Oct, before these fixes) |
| Level 3 | answered; reasoning errors; tag leak | tag removed; key catches errors | not run |
| Inventory | answered; reasoning errors; JSON leak | JSON removed; key catches errors | not run |
| Brazil | refused (earlier) | not strict, no FX gate | not run |
| EUR 1.10, simple interest | ✅ | unchanged | ✅ |

## 6. Remaining risks

- Model accounting reasoning (R7) is unchanged by any of this.
- `live_data_requested` is still rule-based; it was tested on 22 phrasings and
  301 benchmark questions.
- The batched calculator is off by default pending its design review.
- G1 figure-check gap, mixed-sources label granularity, and the earlier
  release-checklist items still apply.

## 7. Recommendation

**BLOCK** for release. The pipeline fixes are ready for review and an approved
retest on the isolated server (restart of 8011 needed), but accounting
correctness (R7) is not addressed and no live result after these fixes exists.
