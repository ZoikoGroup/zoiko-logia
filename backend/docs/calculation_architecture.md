# Governed calculation architecture

Implemented 2026-07-23. Extends the calculation architecture that already
existed in `app/domains/calculation/` (PolicyEngine-US) so that **no
material financial, tax, accounting, or audit number can reach the user
without machine-verifiable provenance.** The LLM explains numbers; it never
authors them.

## 1. System architecture

Four governed engines, in strict priority order — the application decides
which engine runs, never the LLM:

```
1. PolicyEngine-US            statutory US tax/benefit figures
2. Named formula registry     accounting/finance/tax/audit methodologies
3. Expression evaluator       plain arithmetic
4. Unsupported                honest "cannot verify" response
```

A calculation_type naming a known statutory tax figure or a registered
formula can **never** be downgraded to generic arithmetic, even if a raw
expression is also supplied — see `router.py`'s downgrade-prevention tests.

```
app/domains/calculation/
  household_extraction.py    existing — NL -> HouseholdParams (PolicyEngine input)
  policyengine_engine.py      existing — the actual PolicyEngine simulation
  service.py                  existing + extended — RAG-chunk formatting, audit logging,
                               now also to_expression_rag_chunk()
  expression_evaluator.py     NEW — Phase 1, sandboxed AST arithmetic
  units.py                    NEW — canonical unit normalization (15 vs 15% vs 0.15)
  rounding.py                 NEW — named rounding policies
  formula_registry.py         NEW — Phase 3, 15 named formulas
  provenance.py                NEW — Phase 2, shared provenance record model
  router.py                   NEW — Phase 4, engine selection
  arithmetic_extraction.py    NEW — fail-closed NL -> expression (household_extraction.py precedent)

app/domains/massarius/answer_validator.py   extended — provenance-aware check 8
app/orchestration/service.py                extended — wiring, LLM restriction prompt text
scripts/seed_dev_user.py                    extended — governed Source row for the evaluator
```

## 2. Engine priority (the router)

`app/domains/calculation/router.py::route(CalculationRequest) -> RouterDecision`

```python
route(CalculationRequest(calculation_type="federal_income_tax"))
# -> RouterDecision(engine="policyengine_us", status="routed")
# Execution stays in the EXISTING async, DB-aware, audit-logged
# household_extraction.py + policyengine_engine.py + service.py pipeline —
# the router only confirms this should not be downgraded to arithmetic.

route(CalculationRequest(
    calculation_type="gross_margin",
    inputs={"revenue": {"value": "250000", "unit": "USD"},
            "cost_of_goods_sold": {"value": "180000", "unit": "USD"}},
))
# -> RouterDecision(engine="formula_registry", status="executed", result=FormulaResult(...))

route(CalculationRequest(calculation_type="arithmetic", expression="250000 - 180000"))
# -> RouterDecision(engine="expression_evaluator", status="executed", result=CalculationRecord(...))

route(CalculationRequest(calculation_type="uk_vat"))
# -> RouterDecision(engine="unsupported", status="unsupported")
```

`calculation_type` accepts either a bare formula name (`"gross_margin"`) or
a fully-qualified ID (`"accounting.gross_margin.v1"`) — resolved via an
alias table built once from the registry at import time.

## 3. Expression evaluator security model

`app/domains/calculation/expression_evaluator.py`

**Never calls `eval()`, `exec()`, or any dynamic-execution primitive.**
`ast.parse()` builds a syntax tree; a recursive walker
(`_eval_node`) only knows how to handle five node types:
`Expression`, `Constant` (int/float only), `BinOp` (Add/Sub/Mult/Div only),
`UnaryOp` (UAdd/USub only). Every other AST node type — `Name`, `Call`,
`Attribute`, `Subscript`, `List`/`Dict`/`Set`/`Tuple`, comprehensions,
`Lambda`, `BoolOp`, `Compare`, `Import`, `Pow` — raises `ExpressionRejected`
before any evaluation happens. There is no code path from a hostile string
to Python execution, because the primitives that would allow it are never
invoked on untrusted text at all.

All arithmetic runs on `decimal.Decimal`, never binary float — `0.1 + 0.2`
returns exactly `0.3`, not `0.30000000000000004`.

Resource-exhaustion guards (all independently tested):
- Max expression length (200 chars)
- Max AST node count (64)
- Max AST depth (24) — note: pure grouping parentheses don't add AST depth
  in Python's `ast` module, only nested *operations* do
- Max numeric magnitude (1e15, both for literals and intermediate results)
- Division by zero -> a clean rejection, not an exception escaping to the caller

`evaluate_expression()` **never raises** — it always returns a
`CalculationRecord` with `status="verified"` or `status="error"` plus a
human-readable reason in `errors`, so callers never need a bare
`try/except` just to get a structured answer.

## 4. Formula registration process

`app/domains/calculation/formula_registry.py`

To add a formula:

1. Write a pure function `dict[str, Decimal] -> ComputeOutcome`. Raise
   `InvalidInputError(reason)` for a bad value (division by zero, negative
   where positive is required, etc.) — never silently clamp or default.
2. Register a `FormulaDefinition`: id (`"<domain>.<name>.v<major>"`),
   version, `inputs` tuple, `input_units` dict, `output_unit`,
   `methodology_reference` (cite the standard/textbook formula),
   `rounding_policy`, `default_assumptions`.
3. `execute_formula(formula_id, raw_inputs)` handles everything else:
   missing-input detection, unit normalization, rounding, error wrapping.
   Never called with `eval()` or any dynamic dispatch — `compute` is a
   plain Python callable stored on the (frozen) definition.

Currently registered (15): gross profit, gross margin, operating profit,
operating margin, current ratio, quick ratio, debt-to-equity, effective tax
rate, break-even point, straight-line depreciation, declining-balance
depreciation, simple interest, compound interest, loan payment (amortizing),
audit attribute-sampling sample size.

Every formula's numeric correctness is checked in
`tests/test_formula_registry.py` — two (loan payment, compound interest)
against independently-known reference values, not just internal
self-consistency.

## 5. Numeric provenance model

`app/domains/calculation/provenance.py`

```python
PROVENANCE_TYPES = {
    "retrieved_fact",        # existing behavior — literal match in grounding_context
    "user_provided_input",   # the user stated this figure in their own query
    "policy_engine_result",  # PolicyEngine-US
    "named_formula_result",  # formula_registry
    "expression_derived",    # expression_evaluator
    "presentation_only",     # not a factual claim needing verification (reserved for future structured output)
}
```

A `ProvenanceRecord` is built from whichever engine produced a number
(`from_expression_record`, `from_formula_result`, `from_policyengine_value`)
and added to a per-request `ProvenanceStore`. `ProvenanceStore.find_by_value`
does **Decimal-value equality**, not string equality — `"70000"` and
`"70000.00"` match.

**Design choice, documented as a limitation**: since the LLM has no
structured way to cite a specific `calculation_id` inline today (no
tool-calling infrastructure exists in this codebase — see §11), a claim is
matched against provenance **by numeric value**, not by an explicit
reference. This is sound as long as engines don't produce colliding values
for unrelated quantities within the same answer; see §11 for the upgrade
path once/if structured LLM output exists.

## 6. Checkpoint C behavior (provenance-aware check 8)

`app/domains/massarius/answer_validator.py`

Check 8 (numeric fidelity) is **extended, not replaced** — the existing
`retrieved_fact` literal-text-against-`grounding_context` check is
untouched (PolicyEngine's existing RAG-chunk-injection integration still
relies on it and keeps working unmodified). A claimed figure that fails
that check now gets two more chances before failing:

1. Does it appear literally in `query_text` (the user's own words)? -> `user_provided_input`, supported.
2. Does it match a `status="verified"` record in the optional `provenance` `ProvenanceStore`? -> supported.

```python
validate_answer(answer_text, source_bundle,
                 grounding_context=context_text,
                 query_text=request.query,
                 provenance=provenance_store)   # NEW, optional, defaults to None
```

**Backward compatible**: omitting `provenance=` (every existing call site
except the one in `orchestration/service.py`) leaves check 8's behavior
byte-for-byte identical to before this parameter existed —
`test_provenance_defaults_to_none_and_does_not_change_existing_behavior`
verifies this directly.

Checkpoint C escalates a numeric claim when, and only when, none of the
three support paths above match it. This directly fixes the false-positive
this task was raised to prevent: `"250000 - 180000 = 70000"` — a genuinely
correct derived number that would never appear verbatim in any retrieved
document.

## 7. Unit handling

`app/domains/calculation/units.py`

Every input to a formula is supplied as `{"value": ..., "unit": ...}`.
`normalize_value()` is the single place `15`, `"15%"`, and `0.15` get
resolved to one canonical internal representation:

- `unit="percent"`: `15` or `"15%"` both -> `Decimal("0.15")`
- `unit="decimal_rate"`: `0.15` -> `Decimal("0.15")` as-is; a `"15%"`
  *literal* under a declared `decimal_rate` unit is rejected as an
  unresolvable ambiguity, not silently guessed either way
- Currency values strip `$` and `,` before parsing

Formula `compute()` functions receive already-normalized `Decimal` inputs —
none of them re-implements unit parsing.

## 8. Rounding

`app/domains/calculation/rounding.py` — named policies, applied only to a
formula's **final** output, never to intermediate values:

| Policy | Behavior |
|---|---|
| `none` | no rounding |
| `two_decimal_places` | round-half-up to $X.XX |
| `whole_currency_unit` | round-half-up to a whole dollar |
| `percentage_two_decimal_places` | round-half-up to X.XX% |
| `bankers_rounding` | round-half-even to X.XX |
| `round_half_up` | round-half-up to a whole number (used for counts, e.g. sample size) |

Every `FormulaResult` and `CalculationRecord` stores which policy was
applied — a number without a recorded policy is not fully auditable.

## 9. Assumptions

Every `FormulaDefinition` carries `default_assumptions`; `compute()`
functions may add context-specific ones (e.g. quick ratio: "prepaid
expenses are not separately deducted unless supplied as a reduced
current_assets figure"). A required input with no honest default (e.g.
declining-balance's `declining_balance_factor`) is a **required input**,
never a silently-picked default — a caller who omits it gets
`status="missing_input"`, not a guessed `1.5` or `2`.

## 10. Error handling

Every engine returns a structured result object on every path — no
exception escapes to a caller who just wants to know "did this work and
why not":

| Status | Meaning |
|---|---|
| `verified` | executed successfully |
| `missing_input` | a required input was not supplied |
| `invalid_input` | a supplied input was the wrong type/unit/out-of-range |
| `error` | unknown formula id / expression syntax error / rounding failure |

## 11. Known limitations

- **No structured LLM tool-calling exists in this codebase.** The router
  (`CalculationRequest`/`RouterDecision`) is fully generic and ready for a
  future structured caller, but today's real, wired integration
  (`orchestration/service.py`) uses a **deterministic, fail-closed regex
  extractor** (`arithmetic_extraction.py`, mirroring the existing
  `household_extraction.py` precedent) to recognize a small set of
  query shapes ("revenue is $X and expenses are $Y, what is net profit?",
  "sales tax on a $X purchase at Y% rate", "$X minus/plus $Y"). Extend this
  extractor's pattern list incrementally, the same way
  `prescreen.py`/`risk_classifier.py`'s pattern banks already grow, or
  build a real structured tool-calling layer if broader natural-language
  coverage across all 15 formulas is needed — that is a separate,
  substantial project (a new LLM-interaction primitive this codebase does
  not have today), not a small addition.
- **Provenance matching is by numeric value, not by an explicit
  `calculation_id` reference** (see §5) — sound today, but a value
  collision between two unrelated genuine figures in the same answer could
  theoretically cross-validate. Not observed in testing; worth revisiting
  if/when structured LLM output exists to carry an explicit reference.
- **The audit sample-size formula requires `reliability_factor` as an
  explicit input** rather than embedding the full AICPA statistical lookup
  table (a 2-dimensional table keyed by confidence level and expected
  deviation count) — deliberate, per "do not silently choose assumptions."
- **PolicyEngine routing decisions are not executed by the router itself**
  — only classified. Actual execution stays in the pre-existing async/DB
  pipeline. This avoids a parallel architecture but means `router.py`'s
  PolicyEngine branch is a routing decision, not a runnable call, unlike
  its formula/expression branches.
- Only the expression evaluator (not yet the formula registry) is wired
  into the live `orchestration/service.py` pipeline end-to-end. The formula
  registry and provenance-aware Checkpoint C extension are fully built and
  tested standalone; wiring a natural-language path to each of the 15
  formulas is exactly the tool-calling/extractor limitation above.

## 12. Security considerations

- Expression evaluator: see §3. No `eval`/`exec`, explicit AST allow-list,
  four independent resource-exhaustion guards, all with dedicated tests
  including function-call/attribute-access/import/comprehension/lambda
  rejection.
- Formula registry: every `compute()` function is pure Python, reviewed and
  versioned at deploy time — never constructed from user/model input at
  runtime, so it carries none of the expression evaluator's threat model.
- No new external network calls, no new dependencies, no new database
  writes beyond the existing audit-event pattern
  (`record_event_async`, `emitting_service="calculation"`).
- The governed Source rows added in `scripts/seed_dev_user.py` follow the
  exact existing PolicyEngine precedent (dev-seed only, `licence_state="permitted"`,
  `authority_level="primary"`).

## 13. Example end-to-end request/response

```python
from app.domains.calculation.router import route, CalculationRequest

decision = route(CalculationRequest(
    calculation_type="straight_line_depreciation",
    inputs={
        "asset_cost": {"value": "50000", "unit": "USD"},
        "salvage_value": {"value": "0", "unit": "USD"},
        "useful_life_years": {"value": "10", "unit": "years"},
    },
))
# decision.engine == "formula_registry"
# decision.status == "executed"
# decision.result.to_dict() == {
#   "calculation_id": "calc-...",
#   "formula_id": "accounting.straight_line_depreciation.v1",
#   "formula_version": "1.0.0",
#   "engine": "formula_registry",
#   "engine_version": "1.0.0",
#   "output_value": "5000.00",
#   "output_unit": "annual_amount",
#   "steps": [
#     "Depreciable base = Asset cost - Salvage value = 50000 - 0 = 50000",
#     "Annual depreciation = Depreciable base / Useful life = 50000 / 10 = 5000 per year",
#   ],
#   "assumptions": ["Depreciation is allocated evenly across every year ..."],
#   "rounding_policy": "two_decimal_places",
#   "methodology_reference": "(Asset cost - Salvage value) / Useful life (US GAAP ASC 360 / IFRS IAS 16 ...)",
#   "status": "verified",
#   "errors": [],
# }
```

Feeding that into Checkpoint C:

```python
from app.domains.calculation.provenance import ProvenanceStore, from_formula_result
from app.domains.massarius.answer_validator import validate_answer

store = ProvenanceStore()
store.add(from_formula_result(decision.result))

validate_answer(
    "Annual straight-line depreciation on the asset is $5,000.00 per year. [REF-1]",
    source_bundle, grounding_context=context_text, provenance=store,
)
# .passed == True — the figure is verified via named_formula_result provenance,
# even though it never appears literally in grounding_context.
```

## 14. Migration requirements

- Run `scripts/seed_dev_user.py` (or the equivalent seed step in a
  non-dev environment) to create the
  `src-expression-evaluator-calculation-engine` governed Source row —
  without it, the expression evaluator's `allowed_source_ids` gate in
  `orchestration/service.py` never passes and the feature stays inert
  (fails closed, not open).
- Set `ENABLE_EXPRESSION_CALCULATION_ENGINE=true` to turn on the live
  orchestration wiring (same opt-in pattern as
  `ENABLE_TAX_CALCULATION_ENGINE`). No behavior changes for any existing
  request path when unset.
- No database schema migration — reuses the existing `Source`/`SourceVersion`
  tables and the existing `record_event_async` audit path.
