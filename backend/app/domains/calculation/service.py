"""
Audit-logging + RAG-chunk-formatting layer for the PolicyEngine-US
calculation engine — same job app/domains/reference_data/service.py does
for external API sources, but for an in-process computation instead of an
HTTP call (see policyengine_engine.py's docstring for why this lives in its
own domain rather than inside reference_data/).

No cache here, unlike every reference_data source: each calculation is
specific to one household (income/filing-status/dependents/year/state), so
a TTL cache keyed on that full tuple would almost never hit for real,
distinct user queries and isn't worth the complexity.
"""
from __future__ import annotations

from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.audit_ledger.event_envelope import record_event_async
from app.domains.calculation.household_extraction import HouseholdParams
from app.domains.calculation.policyengine_engine import CalculationResult, run_calculation

# The governed Source row Kriton's retrieval layer cites for this data (see
# scripts/seed_dev_user.py) — same fixed-id convention as every
# reference_data *_GOVERNED_SOURCE_ID constant.
POLICYENGINE_GOVERNED_SOURCE_ID = "src-policyengine-us-calculation-engine"

# Checked by orchestration/service.py's _LIVE_DATA_NODE_PREFIXES so this
# chunk survives cross-encoder reranking regardless of prose-similarity
# score — the same reason every reference_data live chunk has one.
POLICYENGINE_NODE_PREFIX = "policyengine-calc-live-"

_VARIABLE_LABELS: dict[str, str] = {
    "eitc": "Earned Income Tax Credit (EITC)",
    "ctc": "Child Tax Credit (CTC)",
    "standard_deduction": "Standard deduction",
    "income_tax": "Federal income tax (after credits)",
    "state_income_tax": "State income tax",
}

_FILING_STATUS_LABELS: dict[str, str] = {
    "SINGLE": "Single",
    "JOINT": "Married Filing Jointly",
    "SEPARATE": "Married Filing Separately",
    "HEAD_OF_HOUSEHOLD": "Head of Household",
    "SURVIVING_SPOUSE": "Qualifying Surviving Spouse",
}


async def get_calculation_bundle(
    db: AsyncSession,
    *,
    household: HouseholdParams,
    tenant_id: str,
    actor_id: str | None,
) -> CalculationResult:
    try:
        result = await run_calculation(household)
    except Exception as exc:
        await _log_calculation_call(
            db, tenant_id=tenant_id, actor_id=actor_id, household=household,
            status=f"error: {exc}", output_variables=[],
        )
        raise

    await _log_calculation_call(
        db, tenant_id=tenant_id, actor_id=actor_id, household=household,
        status="ok", output_variables=list(result.values.keys()),
    )
    return result


def _bucket_income(annual_income: float) -> str:
    """Buckets to the nearest $5,000 rather than logging the exact figure.
    reference_data/service.py's _log_payroll_call comment explicitly warns
    its audit payload is stored verbatim with no redaction layer, and
    orchestration/service.py never persists the raw query text for the same
    reason (query is hashed, not stored) — an exact income figure combined
    with filing status, dependent count, state, and the resulting exact
    credit amounts is a meaningfully re-identifying tuple about a real
    household. A $5,000 bucket preserves everything needed to diagnose a
    bracket-boundary bug (the documented incident this feature is reacting
    to, see reingest_policyengine_fixed.py) while reducing that risk."""
    bucket_floor = int(annual_income // 5000) * 5000
    return f"${bucket_floor:,}-{bucket_floor + 5000:,}"


async def _log_calculation_call(
    db: AsyncSession,
    *,
    tenant_id: str,
    actor_id: str | None,
    household: HouseholdParams,
    status: str,
    output_variables: list[str],
) -> None:
    # Never an "external_reference_data_call" event — this never leaves the
    # process, and labeling it "external" would mislead a future ledger
    # reader into thinking a third-party API was hit.
    await record_event_async(
        db,
        tenant_id=tenant_id,
        event_name="tax_calculation_computed",
        emitting_service="calculation",
        subject_type="calculation_engine",
        subject_id="policyengine_us.household_calculation",
        actor_id=actor_id,
        payload={
            "params": {
                "income_bucket": _bucket_income(household.annual_income),
                "filing_status": household.filing_status,
                "num_dependents": household.num_dependents,
                "tax_year": household.tax_year,
                "state_code": household.state_code,
            },
            "status": status,
            "output_variables_computed": output_variables,
        },
    )


def to_calculation_rag_chunk(result: CalculationResult, *, source_id: str) -> dict:
    """Formats a CalculationResult into a dict shaped exactly like a real
    RAG chunk (see reference_data/service.py's to_*_rag_chunk functions for
    the precedent this follows). Every computed dollar figure is written in
    a form massarius/answer_validator.py's numeric-fidelity check
    (_CLAIMED_FIGURE_PATTERN = r"\\$\\s?\\d[\\d,]*(?:\\.\\d+)?|...") can
    actually match, since this text is exactly what becomes part of
    grounding_context — the LLM's answer is checked against this literal
    text, so the figure format here is not cosmetic."""
    household = result.household
    filing_label = _FILING_STATUS_LABELS.get(household.filing_status, household.filing_status)
    dependents_label = (
        "no dependents" if household.num_dependents == 0
        else f"{household.num_dependents} dependent{'s' if household.num_dependents != 1 else ''}"
    )

    lines = [
        "PolicyEngine-US — real household tax calculation (not an LLM estimate), "
        f"computed for a {filing_label} filer, {dependents_label}, "
        f"${household.annual_income:,.0f} annual employment income, tax year {household.tax_year}:"
    ]
    for variable in ("eitc", "ctc", "standard_deduction", "income_tax"):
        value = result.values.get(variable)
        if value is not None:
            lines.append(f"- {_VARIABLE_LABELS[variable]}: ${value:,.2f}")

    if result.state_tax_supported and household.state_code:
        state_value = result.values.get("state_income_tax")
        if state_value is not None:
            lines.append(f"- {household.state_code} state income tax: ${state_value:,.2f}")
    else:
        lines.append(
            "- This is a federal-only calculation. State income tax was not computed "
            f"for {household.state_code or 'an unspecified state'} (only CA and NY state "
            "income tax are covered by this system's ingested state tax content)."
        )

    return {
        "text": "\n".join(lines),
        "metadata": {
            "source_id": source_id,
            "title": "PolicyEngine-US — Live Household Tax Calculation Engine",
            "version": f"tax_year_{household.tax_year}",
            "jurisdiction": household.state_code or "US",
            "file_path": "https://github.com/PolicyEngine/policyengine-us",
        },
        "score": 0.5,
        "node_id": f"{POLICYENGINE_NODE_PREFIX}{uuid4().hex[:8]}",
    }


# The governed Source row for the sandboxed arithmetic expression evaluator
# (Phase 1 of the governed calculation architecture — see
# docs/calculation_architecture.md). Same fixed-id convention as
# POLICYENGINE_GOVERNED_SOURCE_ID above; see scripts/seed_dev_user.py.
EXPRESSION_EVALUATOR_GOVERNED_SOURCE_ID = "src-expression-evaluator-calculation-engine"

# Same rerank-survival purpose as POLICYENGINE_NODE_PREFIX above.
EXPRESSION_EVALUATOR_NODE_PREFIX = "expr-calc-live-"


def to_expression_rag_chunk(record, *, source_id: str) -> dict:
    """Formats an expression_evaluator.CalculationRecord into the same
    real-RAG-chunk shape to_calculation_rag_chunk() produces above — the
    figure is written in the exact literal form
    massarius/answer_validator.py's numeric-fidelity check matches, for the
    same reason. Only called for a verified record; an error/rejected
    expression never reaches composition as a "fact" to cite."""
    lines = [
        "Deterministic arithmetic calculation (sandboxed expression "
        "evaluator, not an LLM estimate) — never binary floating-point, "
        f"exact decimal arithmetic: {record.expression} = {record.result}",
    ]
    return {
        "text": "\n".join(lines),
        "metadata": {
            "source_id": source_id,
            "title": "Sandboxed Expression Evaluator — Live Arithmetic Calculation Engine",
            "version": record.engine_version,
            "jurisdiction": "US",
            "file_path": "",
        },
        "score": 0.5,
        "node_id": f"{EXPRESSION_EVALUATOR_NODE_PREFIX}{uuid4().hex[:8]}",
    }


# The governed Source row for the named formula registry (Phase 3 of the
# governed calculation architecture). Same fixed-id convention as the two
# constants above; see scripts/seed_dev_user.py.
FORMULA_REGISTRY_GOVERNED_SOURCE_ID = "src-formula-registry-calculation-engine"

FORMULA_REGISTRY_NODE_PREFIX = "formula-calc-live-"


def to_formula_rag_chunk(result, *, source_id: str) -> dict:
    """Formats a formula_registry.FormulaResult into the same real-RAG-chunk
    shape as to_calculation_rag_chunk()/to_expression_rag_chunk() — the
    figure is written in the exact literal form
    massarius/answer_validator.py's numeric-fidelity check matches. Only
    called for a verified result."""
    lines = [
        f"{result.formula_id.split('.')[1].replace('_', ' ').title()} "
        f"(named formula registry, not an LLM estimate) — "
        f"{result.methodology_reference}",
        f"Result: {result.output_value} {result.output_unit}",
        f"Calculation ID: {result.calculation_id}",
        f"Rounding policy: {result.rounding_policy}",
    ]
    lines.extend(f"- {step}" for step in result.steps)
    lines.extend(f"- Assumption: {assumption}" for assumption in result.assumptions)
    return {
        "text": "\n".join(lines),
        "metadata": {
            "source_id": source_id,
            "title": "Named Formula Registry — Governed Accounting/Finance/Tax/Audit Calculation Engine",
            "version": result.formula_version,
            "jurisdiction": "US",
            "file_path": "",
            "calculation_id": result.calculation_id,
            "formula_id": result.formula_id,
        },
        "score": 0.5,
        "node_id": f"{FORMULA_REGISTRY_NODE_PREFIX}{uuid4().hex[:8]}",
    }
