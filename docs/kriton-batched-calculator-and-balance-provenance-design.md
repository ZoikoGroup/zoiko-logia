# Kriton — Batched calculations and accounting-balance provenance (design)

Status: design for review, 2026-10-17. Nothing here is implemented in the
production path. Section 1 was written before the prototype; its measured
results are in section 1.7.

## 1. Batched calculations (Priority 2)

### 1.1 Problem (measured)

- The agent makes one `calculate` call per step. Across 33 measured runs on the
  stored benchmark questions, no step contained more than one calculation, even
  with an explicit instruction to batch (removed again on 2026-10-17 because it
  had no effect).
- Every step re-sends the whole prompt (instructions, evidence, history, tool
  results): about 10–12k tokens a step.
- The financial-performance question needs 6–12 calculations. It used a median
  of 95k tokens (maximum 149k against the 150,000 cap), took 23–62 s, and on
  2026-10-16 ran out of steps or tokens before computing its last comparison
  figures.

### 1.2 Proposed interface (backward compatible)

`calculate` keeps its current form and gains an optional batch form. Exactly
one form per call:

```json
{"expression": "1215000 - 710000", "label": "Gross profit"}
```

```json
{"expressions": [
  {"label": "Gross profit (current)", "expression": "1250000 - 35000 - 710000"},
  {"label": "Gross profit (prior)",   "expression": "1100000 - 660000"},
  {"label": "Gross margin (current)", "expression": "505000 / 1215000 * 100"}
]}
```

- `expressions`: 1–12 items, each `{label, expression}` with the existing
  limits (expression ≤ 240 characters, label ≤ 120). Items must be
  **independent**: an item may not refer to another item's result. A dependent
  calculation needs a later call or one combined expression, as today.
- Every item is evaluated by the same AST-whitelisted evaluator
  (`calculation_service.evaluate_expression`, formula version
  `expression-evaluator-1.0`). There is no new arithmetic engine.
- **Result:** one line per item, in order, in today's single-result format:
  `Label: expression = result (computed by the application; use this exact
  value). Rounded to 2 decimal places: …`. A failed item reads
  `Label: expression — error: <code> <message>`. The other items still succeed.
- **Receipts:** one receipt per successful item, with exactly today's fields
  (`calculation_id`, `formula_version`, `expression`, `input_hash`, `result`,
  `rounded`, `rounding_rule`, `warnings`). Each is saved as its own
  `CalculationRun` and audited as its own `calculation_receipt` event.
  Persistence and audit stay one row and one event per figure.
- `ToolResult` gains `receipts: tuple[dict, ...]`. The existing `receipt`
  field stays and holds the first receipt, so current readers keep working.
- `ok` is true when at least one item succeeded. An all-failed batch is a
  failure with the first item's error code.

### 1.3 Compatibility risks and mitigations

| # | Risk | Where | Mitigation |
|---|------|-------|------------|
| R1 | Readers take only the first result. `final_text`'s "verified working" fallback and `_verified_work_outcome` call `content.split(" (computed by the application", 1)[0]`, so a batch would show its first line only. | `agent.py` | Parse per line (or from `receipts`) in both places, with a test for each. |
| R2 | Only `result.receipt` is appended to `calculation_receipts`, so items 2..n would be missing from release verification, the figure gate and persistence. | `agent.py` | Append every item of `receipts`; keep `receipt` for single calls. |
| R3 | `ToolCallRecord.calculation_id` is a single value, so the tool-call audit would link to one receipt. | `agent.py`, audit | Add `calculation_ids`, keep the first id in the existing field. The receipts are the source of truth either way. |
| R4 | The tool-call cap counts calls, so 12 figures cost one call and the cap stops bounding work. | `AgentLimits` | Bound the batch at 12 items, and count items toward a separate `max_calculations` (e.g. 36). The time and token budgets are unchanged. |
| R5 | Idempotent resume is keyed by (tool, argument hash), so a reordered batch is a new key. | `agent.py` resume | Acceptable: a reorder re-evaluates pure arithmetic, with no side effects. |
| R6 | The model may put dependent items in one batch (`a = …`, then `b = a × 2`). | model | The schema and description say items are independent; an item naming another item fails as `invalid_expression` (names are not allowed by the evaluator). |
| R7 | The model may produce malformed arrays (an empty list, both forms, more than 12 items). | args validation | Pydantic validation with a clear error. One correction round already exists for invalid tool arguments. |
| R8 | Policy and authorisation: `_tool_authorizer` decides per call (`no_user_figures`). | service | Unchanged: a batch is one call and is authorised once; its items are arithmetic on the same supplied figures. |
| R9 | Audit volume: up to 12 receipt events from one call. | audit batch | Same per-figure volume as 12 single calls today. |
| R10 | Eval and planner code that counts `calculate` calls as "calculations". | `run_baseline_eval.py`, `planner_shadow` | Count receipts, not calls, in metrics. The planner stays in shadow and is not affected. |
| R11 | Provider support: whether gpt-oss-120b on Groq reliably emits nested arrays in tool arguments. | model | Measured by the prototype (1.7) before any decision. |

### 1.4 What does not change

- The evaluator, the formula version and the rounding rule.
- Per-figure receipts, `CalculationRun` rows and audit events.
- Permissions, tool policy, RLS and tenant scope (`tenant_scope="none"`; pure
  arithmetic).
- The figure gate, which reads calculator results per line.
- The 150,000-token cap, the time budget and step limits.

### 1.5 Rollout (if approved)

1. Fix R1–R3 behind the single-call path first (no behaviour change), with
   tests.
2. Add the optional `expressions` field and `max_calculations`, with tests for
   partial failure, all failure, more than 12 items, both forms, receipts and
   persistence.
3. Shadow comparison on the benchmark questions (correctness, tool calls,
   tokens, latency) before enabling it for users.

### 1.6 Prototype method

The prototype lives outside the repository (a scratch harness). It replaces
the calculator spec in the agent's registry with a batch-capable one and
carries every item's receipt into the outcome. It runs the real pipeline with
the real model and search, and with the database faked. Nothing is written to
any tenant table. It is not a substitute for authenticated API verification.

### 1.7 Prototype results

Measured 2026-10-17, 3 runs per arm, real model (gpt-oss-120b), database
faked. Both arms include the tightened figure gate. Correctness is scored
against independently computed figures (FX: £100,000 / £104,166.67 /
£96,153.85; financial: 12 key figures).

| Question | Arm | Correct | `calculate` calls / calculations (median) | Tokens median / max | Latency median | Token-cap stops |
|---|---|---|---|---|---|---|
| FX scenarios | current | 6/9 | 3 / 3 | 65,017 / 87,746 | 18.1 s | 0 |
| FX scenarios | batch | 9/9 | 2 / 4 | 43,655 / 54,376 | 16.6 s | 0 |
| Financial performance | current | 36/36 | 8 / 8 | 150,471 / 177,602 | 37.5 s | 2 of 3 |
| Financial performance | batch | 34/36 | 4 / 14 | 70,612 / 130,927 | 23.9 s | 0 |

Findings:

- The model used the batch form unprompted in every run, so R11 is
  answered: gpt-oss-120b emits the nested array reliably. There were no
  malformed-argument rejections.
- Tokens fell 33% (FX) and 53% (financial) at the median, and the financial
  question no longer hit the token cap. The "current" arm overshot the
  150,000 cap to 177,602, because the cap is checked before tool calls and
  the final answer turn is added after it.
- Correctness: on FX, batch computed every scenario (9/9), while the current
  arm left scenarios to hand arithmetic, which verification then removed.
  One financial batch run did not state two change figures at all (£65,000,
  £36,000); nothing was removed or wrong.
- Not covered by the prototype: R1 (the fallback text shows only the first
  item) and R3 (the audit tool-call record carries one calculation id).
  Both need the code changes in 1.5 step 1.
- Three runs per arm is a small sample: the direction is clear, the sizes
  are indicative.

### 1.8 Implementation (2026-10-17) — built, not enabled in production

**Interface as implemented** (`app/domains/model_gateway/tools/calc_tool.py`):

- `CALCULATE_TOOL` (version 1.1, single `expression`) is unchanged and stays
  in the production registry.
- `CALCULATE_BATCH_TOOL` (version 1.2) has the same name, policy, roles,
  tenant scope, risk level and 2 s timeout. Its arguments are
  `CalculateBatchArgs`: exactly one of `expression` (+ `label`) or
  `expressions` (1–12 × `{expression ≤ 240, label ≤ 120}`). Extra fields are
  rejected.
- The single form returns exactly the single-expression output.
- Each batch item is evaluated by the unchanged single-expression handler,
  with the same AST-whitelisted evaluator and the same division-by-zero and
  invalid-expression handling. One failed item never affects another.
- Result: one numbered line per item. A failed item is marked `NOT COMPUTED
  (<code>)` and "Do not state a result for this item". `receipts` holds one
  receipt per successful item, adding `batch_index` and `batch_size`, with
  `tool_version` 1.2. `receipt` is the first receipt. `items_total` and
  `items_failed` are counts. `ok` is false only when every item failed.
- Output stays within `MAX_RESULT_CHARS`: a batch that would exceed it uses a
  compact one-line-per-item form that keeps every result.
- `build_default_registry(batch_calculations=False)` is the default, and
  production calls it with no arguments.

**Step 1 (R1–R3), in the production path, with no change for single calls:**

- **R1.** `agent.verified_working` builds the working from receipts (every
  item, failed items excluded). It is used by the timeout and provider-failure
  fallback and by both withheld-answer fallbacks. A result without receipts
  falls back to reading its text line by line.
- **R2.** Every receipt is appended to `calculation_receipts`. Charts are
  reconciled with the verified answer (`figure_reconciliation.reconcile_charts`):
  a charted value must be a calculator result, a figure from the user, a
  source or tool data, or a figure the verified text still shows. Otherwise
  the category is dropped and named under the chart ("Not charted: …"), and a
  limitation is added.
- **R3.** `ToolCallRecord` and the `agent_tool_called` event carry
  `calculation_ids`, `items_total` and `items_failed`. `calculation_receipt_recorded`
  carries `batch_index` and `batch_size`. A new `answer_figure_provenance`
  event links each figure of the released answer (statement hash, figure,
  calculation ids) to the calculations that produced it.
- `ToolRegistry.execute` truncation now keeps every field of the result. It
  used to rebuild the result and drop the new ones.
- `AgentLimits.max_calculations` (36) counts batch items. A call that would
  exceed it is refused with `budget_exhausted`, as the tool-call cap is.

**Migration plan (each step needs separate approval):**

1. Review this change set (no production behaviour change except R1–R3 and
   chart reconciliation, which also apply to single calls).
2. Add a setting (proposed `KRITON_CALCULATE_BATCH`, default false) that
   passes `batch_calculations=True` in `model_gateway.service._tool_registry`.
   This touches configuration and `.env.example`, so it needs approval.
3. Enable it in a non-production environment. Re-run the stored benchmark
   questions through the authenticated API (not the in-process harness), and
   compare correctness, tool calls, tokens and latency with the single form.
4. Enable it in production. Rollback is turning the setting off: the single
   form is unchanged, and receipts, audit events and persistence are
   identical per figure.

## 2. Accounting-balance provenance (Priority 3)

### 2.1 What exists (2026-10-17)

`verification_service.unsupported_balances` checks one balance family:
contract liability, deferred revenue or income, unearned revenue, and revenue
received in advance. A figure is supported when it is consideration the user
says was paid, received, billed or due (or their total), that amount less
revenue the calculation recognised, or a straight-line share of it over a term
the question states. It is never more than was received. Table cells are
qualified ("Not established"), sentences removed, and the removal audited as
`unsupported_premise`.

### 2.2 Why it cannot simply be widened

- It keys on wording ("paid", "upfront", "due"). Other balances have different
  source-of-funds language: receivables (invoiced, billed, owed), payables
  (received goods, invoice received), prepayments (paid in advance for future
  service), accruals (incurred, not yet invoiced), provisions (obligation,
  estimate), and inventory (purchased, written down).
- Some balances have no single cash premise. A provision rests on a
  measurement judgement, and its amount is an estimate, not a sum of receipts.
  A "supported" rule here would wrongly certify an estimate.
- Period matters: a balance is at a date. The current check knows the term,
  but not the reporting date the question asks about.

### 2.3 Staged design

**Stage A — shared balance model (no new behaviour).** Represent a balance
claim as (balance type, amount, as-at date, period, source-of-funds facts).
Move the contract-liability rule onto it unchanged, with tests proving
identical results.

**Stage B — cash-premise balances, one type at a time, each behind its own
tests:**

| Balance | Premise required (stated by the user) | Supported amount |
|---|---|---|
| Contract liability / deferred revenue | consideration received or due | received/due − recognised (as today) |
| Trade receivable | amount invoiced/billed, or revenue recognised and unpaid | billed/recognised − cash received |
| Prepayment (asset) | amount paid in advance for a future period | paid − expense recognised (straight-line over the stated term) |
| Accrued expense | cost incurred and not invoiced | the stated incurred amount only |

**Stage C — the reporting period.** Use `figure_attribution`'s period tags.
An as-at balance must use only movements up to its date: the 31 December
liability uses three months of recognition, not four.

**Stage D — estimate balances** (provisions, impairment, ECL, depreciation
judgements). These are never "supported" by arithmetic alone. The amount must
be user-stated or sourced. Otherwise it is shown as an assumption, with the
judgement named, and the answer is partial.

Each stage is a separate change with its own adversarial tests (an assumed
payment, a wrong period, an overstated balance), and the existing
contract-liability tests are kept unchanged.

### 2.4 Out of scope until approved

Broad rewrites; balances inferred from documents (they need the document
provenance work first); multi-currency balances (they need the FX rate and its
date as a premise).
