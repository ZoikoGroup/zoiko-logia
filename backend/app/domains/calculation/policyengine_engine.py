"""
Runs a real PolicyEngine-US household simulation — the only file in this
domain that imports policyengine_us, so the heavy one-time import cost
(numpy/pandas + a ~5,800-variable parameter tree, ~15s measured on this
setup) is isolated to first real use rather than paid by every process that
merely imports app.domains.calculation. `import policyengine_us` inside a
function is cheap on every call after the first (Python's own sys.modules
cache), so no extra singleton/caching is needed beyond that — measured
per-simulation cost after the first import is well under 100ms.

Output scoped to what's already ingested elsewhere in this codebase
(scripts/ingest_policyengine_topics.py: Deductions, Credits, CA/NY income
tax) — federal EITC, CTC, standard deduction, federal income tax, and
CA/NY state income tax when named. Social Security is deliberately NOT
computed here: household_extraction.py has no extractor for a Social
Security benefit amount, and taxable_social_security is 0 for any household
with no such input — surfacing an always-zero figure would be misleading,
not merely incomplete. Add a benefit-amount extractor first if that
coverage is wanted later.

Every variable name and enum value below was verified against the
installed policyengine_us v1.775.8 package's variable registry
(policyengine_us.system.system.variables) before being hardcoded here —
per the project's own numeric-fidelity doctrine (massarius/answer_validator.py
check #8), a wrong variable name would silently produce a wrong number,
exactly the failure this feature exists to eliminate.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from app.domains.calculation.household_extraction import HouseholdParams

# States with no state income tax at all — used as a technical placeholder
# household state when the query names no US state, so the simulation has
# a valid household.state_code input to run against. Chosen specifically
# because it contributes nothing to any state_income_tax output, so it
# cannot leak a fabricated state-tax fact into a federal-only calculation
# (verified empirically: state_income_tax computes to 0 for this state,
# and no other output variable in _OUTPUT_VARIABLES reads household state).
_NO_STATE_INCOME_TAX_PLACEHOLDER = "TX"

# The two states this codebase has actually ingested PolicyEngine parameter
# content for (see backend/data/sources/us/US_PolicyEngine_CA_IncomeTax.md /
# _NY_IncomeTax.md) — only these get their state_income_tax figure surfaced
# in the chunk text; naming any other state still runs a valid simulation
# (state_income_tax is computed for all 50 states+DC) but the chunk text
# intentionally omits it rather than presenting un-ingested state tax
# figures as equally authoritative.
_SUPPORTED_STATE_TAX_JURISDICTIONS = frozenset({"CA", "NY"})

_OUTPUT_VARIABLES = ("eitc", "ctc", "standard_deduction", "income_tax", "state_income_tax")


@dataclass(frozen=True)
class CalculationResult:
    household: HouseholdParams
    # One float per _OUTPUT_VARIABLES entry.
    values: dict = field(default_factory=dict)
    # Whether household.state_code was one of _SUPPORTED_STATE_TAX_JURISDICTIONS
    # — governs whether to_calculation_rag_chunk() surfaces the state figure.
    state_tax_supported: bool = False


def _build_situation(household: HouseholdParams) -> dict:
    year = household.tax_year
    state_code = household.state_code if household.state_code else _NO_STATE_INCOME_TAX_PLACEHOLDER

    people = {"parent": {"age": {year: 35}, "employment_income": {year: household.annual_income}}}
    members = ["parent"]
    for i in range(household.num_dependents):
        child_id = f"dependent_{i}"
        people[child_id] = {"age": {year: 10}}  # a school-age placeholder; exact age doesn't affect EITC/CTC eligibility count
        members.append(child_id)

    return {
        "people": people,
        "tax_units": {
            "tax_unit": {"members": members, "filing_status": {year: household.filing_status}}
        },
        "households": {
            "household": {"members": members, "state_code": {year: state_code}}
        },
    }


def _run_simulation_sync(household: HouseholdParams) -> CalculationResult:
    from policyengine_us import Simulation  # lazy — see module docstring

    situation = _build_situation(household)
    simulation = Simulation(situation=situation)

    values = {}
    for variable in _OUTPUT_VARIABLES:
        result = simulation.calculate(variable, household.tax_year)
        # PolicyEngine returns a per-tax-unit array; this situation always
        # builds exactly one tax unit, so index 0 is the household's value.
        values[variable] = float(result[0])

    return CalculationResult(
        household=household,
        values=values,
        state_tax_supported=household.state_code in _SUPPORTED_STATE_TAX_JURISDICTIONS,
    )


async def run_calculation(household: HouseholdParams) -> CalculationResult:
    """CPU-bound (PolicyEngine's Simulation.calculate is synchronous) — run
    off the event loop the same way app/domains/rag/reranker.py's
    sentence-transformers inference is, so one household calculation never
    blocks every other concurrent request."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _run_simulation_sync, household)
