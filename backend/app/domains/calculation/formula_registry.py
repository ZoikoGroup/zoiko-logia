"""
Named, versioned formula registry — Phase 3 of the governed calculation
architecture (see docs/calculation_architecture.md).

Every formula here is pure (no I/O, no randomness, no wall-clock dependence
in its math — only `executed_at` on the result records real time), fully
deterministic, and independently testable. A formula's compute function
never invents a missing input's value: a required input that isn't supplied
produces a `missing_input` FormulaResult, never a guess.

Percentage/rate inputs are normalized once, centrally, by units.py before any
compute() function runs — every compute() function below can assume
"expects a rate" means "expects a Decimal fraction like 0.15", never a bare
15 or a "15%" string.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, DivisionByZero, InvalidOperation, getcontext
from typing import Callable, Optional
from uuid import uuid4

from app.domains.calculation.rounding import round_value
from app.domains.calculation.units import UnitError, normalize_value

getcontext().prec = 50

ENGINE_NAME = "formula_registry"
ENGINE_VERSION = "1.0.0"


class MissingInputError(Exception):
    def __init__(self, missing: list[str]):
        self.missing = missing
        super().__init__(f"Missing required input(s): {missing}")


class InvalidInputError(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class ComputeOutcome:
    value: Decimal
    steps: list[str]
    assumptions: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class FormulaDefinition:
    id: str
    name: str
    version: str
    inputs: tuple[str, ...]
    input_units: dict           # {input_name: unit}
    output_unit: str
    jurisdiction: Optional[str]
    methodology_reference: str
    rounding_policy: str
    default_assumptions: tuple[str, ...]
    compute: Callable[[dict], ComputeOutcome]


@dataclass(frozen=True)
class FormulaResult:
    calculation_id: str
    formula_id: str
    formula_version: str
    engine: str
    engine_version: str
    inputs: dict = field(default_factory=dict)          # {name: {"value": raw, "unit": unit}}
    output_value: str = ""
    output_unit: str = ""
    steps: list = field(default_factory=list)
    assumptions: list = field(default_factory=list)
    rounding_policy: str = ""
    methodology_reference: str = ""
    executed_at: str = ""
    status: str = "verified"   # verified | missing_input | invalid_input | error
    errors: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "calculation_id": self.calculation_id,
            "formula_id": self.formula_id,
            "formula_version": self.formula_version,
            "engine": self.engine,
            "engine_version": self.engine_version,
            "inputs": self.inputs,
            "output_value": self.output_value,
            "output_unit": self.output_unit,
            "steps": self.steps,
            "assumptions": self.assumptions,
            "rounding_policy": self.rounding_policy,
            "methodology_reference": self.methodology_reference,
            "executed_at": self.executed_at,
            "status": self.status,
            "errors": self.errors,
        }


def _new_calculation_id() -> str:
    return f"calc-{uuid4().hex[:12]}"


def _req(inputs: dict, name: str) -> Decimal:
    return inputs[name]


# ─────────────────────────────────────────────────────────────────────────
# Formula implementations — each is pure: dict[str, Decimal] -> ComputeOutcome
# ─────────────────────────────────────────────────────────────────────────

def _gross_profit(i: dict) -> ComputeOutcome:
    revenue, cogs = _req(i, "revenue"), _req(i, "cost_of_goods_sold")
    value = revenue - cogs
    return ComputeOutcome(
        value=value,
        steps=[f"Gross profit = Revenue - COGS = {revenue} - {cogs} = {value}"],
    )


def _gross_margin(i: dict) -> ComputeOutcome:
    revenue, cogs = _req(i, "revenue"), _req(i, "cost_of_goods_sold")
    if revenue == 0:
        raise InvalidInputError("Revenue cannot be zero when computing gross margin.")
    gross_profit = revenue - cogs
    value = (gross_profit / revenue) * Decimal(100)
    return ComputeOutcome(
        value=value,
        steps=[
            f"Gross profit = Revenue - COGS = {revenue} - {cogs} = {gross_profit}",
            f"Gross margin = Gross profit / Revenue = {gross_profit} / {revenue} = {value}%",
        ],
    )


def _operating_profit(i: dict) -> ComputeOutcome:
    revenue = _req(i, "revenue")
    cogs = _req(i, "cost_of_goods_sold")
    opex = _req(i, "operating_expenses")
    gross_profit = revenue - cogs
    value = gross_profit - opex
    return ComputeOutcome(
        value=value,
        steps=[
            f"Gross profit = Revenue - COGS = {revenue} - {cogs} = {gross_profit}",
            f"Operating profit = Gross profit - Operating expenses = {gross_profit} - {opex} = {value}",
        ],
        assumptions=["Operating profit excludes interest and taxes (EBIT-style measure)."],
    )


def _operating_margin(i: dict) -> ComputeOutcome:
    revenue = _req(i, "revenue")
    cogs = _req(i, "cost_of_goods_sold")
    opex = _req(i, "operating_expenses")
    if revenue == 0:
        raise InvalidInputError("Revenue cannot be zero when computing operating margin.")
    operating_profit = revenue - cogs - opex
    value = (operating_profit / revenue) * Decimal(100)
    return ComputeOutcome(
        value=value,
        steps=[
            f"Operating profit = Revenue - COGS - Operating expenses = {revenue} - {cogs} - {opex} = {operating_profit}",
            f"Operating margin = Operating profit / Revenue = {operating_profit} / {revenue} = {value}%",
        ],
        assumptions=["Operating profit excludes interest and taxes (EBIT-style measure)."],
    )


def _current_ratio(i: dict) -> ComputeOutcome:
    assets, liabilities = _req(i, "current_assets"), _req(i, "current_liabilities")
    if liabilities == 0:
        raise InvalidInputError("Current liabilities cannot be zero when computing the current ratio.")
    value = assets / liabilities
    return ComputeOutcome(
        value=value,
        steps=[f"Current ratio = Current assets / Current liabilities = {assets} / {liabilities} = {value}"],
    )


def _quick_ratio(i: dict) -> ComputeOutcome:
    assets = _req(i, "current_assets")
    inventory = _req(i, "inventory")
    liabilities = _req(i, "current_liabilities")
    if liabilities == 0:
        raise InvalidInputError("Current liabilities cannot be zero when computing the quick ratio.")
    numerator = assets - inventory
    value = numerator / liabilities
    return ComputeOutcome(
        value=value,
        steps=[
            f"Quick assets = Current assets - Inventory = {assets} - {inventory} = {numerator}",
            f"Quick ratio = Quick assets / Current liabilities = {numerator} / {liabilities} = {value}",
        ],
        assumptions=["Quick assets exclude inventory only; prepaid expenses are not separately deducted unless supplied as a reduced current_assets figure."],
    )


def _debt_to_equity(i: dict) -> ComputeOutcome:
    liabilities, equity = _req(i, "total_liabilities"), _req(i, "total_equity")
    if equity == 0:
        raise InvalidInputError("Total equity cannot be zero when computing debt-to-equity ratio.")
    value = liabilities / equity
    return ComputeOutcome(
        value=value,
        steps=[f"Debt-to-equity = Total liabilities / Total equity = {liabilities} / {equity} = {value}"],
    )


def _effective_tax_rate(i: dict) -> ComputeOutcome:
    tax, pretax_income = _req(i, "total_tax_expense"), _req(i, "pretax_income")
    if pretax_income == 0:
        raise InvalidInputError("Pretax income cannot be zero when computing effective tax rate.")
    value = (tax / pretax_income) * Decimal(100)
    return ComputeOutcome(
        value=value,
        steps=[f"Effective tax rate = Total tax expense / Pretax income = {tax} / {pretax_income} = {value}%"],
    )


def _net_profit(i: dict) -> ComputeOutcome:
    revenue, expenses = _req(i, "revenue"), _req(i, "total_expenses")
    value = revenue - expenses
    return ComputeOutcome(value=value, steps=[f"Net profit = Revenue - Total expenses = {revenue} - {expenses} = {value}"])


def _inventory_turnover(i: dict) -> ComputeOutcome:
    cogs, inventory = _req(i, "cost_of_goods_sold"), _req(i, "average_inventory")
    if inventory == 0:
        raise InvalidInputError("Average inventory cannot be zero.")
    value = cogs / inventory
    return ComputeOutcome(value=value, steps=[f"Inventory turnover = COGS / Average inventory = {cogs} / {inventory} = {value}"])


def _receivables_days(i: dict) -> ComputeOutcome:
    receivables, revenue, days = _req(i, "average_receivables"), _req(i, "credit_revenue"), _req(i, "days_in_period")
    if revenue == 0 or days <= 0:
        raise InvalidInputError("Credit revenue and days in period must be positive.")
    value = receivables / revenue * days
    return ComputeOutcome(value=value, steps=[f"Receivables days = Average receivables / Credit revenue x Days = {receivables} / {revenue} x {days} = {value}"], assumptions=["Credit revenue and average receivables cover the same period."])


def _taxable_income_scenario(i: dict) -> ComputeOutcome:
    gross, adjustments, deductions = _req(i, "gross_income"), _req(i, "adjustments"), _req(i, "deductions")
    value = gross - adjustments - deductions
    return ComputeOutcome(value=value, steps=[f"Scenario taxable income = Gross income - Adjustments - Deductions = {gross} - {adjustments} - {deductions} = {value}"], assumptions=["Arithmetic on user-supplied amounts; this does not determine legal allowability."])


def _tax_from_supplied_rate(i: dict) -> ComputeOutcome:
    base, rate = _req(i, "taxable_base"), _req(i, "user_supplied_rate")
    value = base * rate
    return ComputeOutcome(value=value, steps=[f"Scenario tax = Taxable base x User-supplied rate = {base} x {rate} = {value}"], assumptions=["The user supplies the rate; Kriton does not determine whether it legally applies."])


def _audit_materiality(i: dict) -> ComputeOutcome:
    benchmark, percentage = _req(i, "benchmark_amount"), _req(i, "user_selected_percentage")
    value = benchmark * percentage
    return ComputeOutcome(value=value, steps=[f"Overall materiality = Benchmark x User-selected percentage = {benchmark} x {percentage} = {value}"], assumptions=["Benchmark and percentage selection remain professional judgment inputs."])


def _projected_misstatement(i: dict) -> ComputeOutcome:
    error, sample, population = _req(i, "sample_misstatement"), _req(i, "sample_book_value"), _req(i, "population_book_value")
    if sample == 0:
        raise InvalidInputError("Sample book value cannot be zero.")
    rate = error / sample
    value = rate * population
    return ComputeOutcome(value=value, steps=[f"Sample error rate = {error} / {sample} = {rate}", f"Projected misstatement = {rate} x {population} = {value}"], assumptions=["Simple ratio projection; sampling risk and anomalous-error evaluation require auditor judgment."])


def _sampling_interval(i: dict) -> ComputeOutcome:
    tolerable, size = _req(i, "tolerable_misstatement"), _req(i, "sample_size")
    if size <= 0:
        raise InvalidInputError("Sample size must be positive.")
    value = tolerable / size
    return ComputeOutcome(value=value, steps=[f"Sampling interval = Tolerable misstatement / Sample size = {tolerable} / {size} = {value}"])


def _break_even_point(i: dict) -> ComputeOutcome:
    fixed_costs = _req(i, "fixed_costs")
    price = _req(i, "price_per_unit")
    variable_cost = _req(i, "variable_cost_per_unit")
    contribution_margin = price - variable_cost
    if contribution_margin <= 0:
        raise InvalidInputError(
            "Price per unit must exceed variable cost per unit (positive contribution margin required)."
        )
    value = fixed_costs / contribution_margin
    return ComputeOutcome(
        value=value,
        steps=[
            f"Contribution margin per unit = Price - Variable cost = {price} - {variable_cost} = {contribution_margin}",
            f"Break-even point (units) = Fixed costs / Contribution margin = {fixed_costs} / {contribution_margin} = {value}",
        ],
        assumptions=["Assumes a single product with constant price and variable cost per unit."],
    )


def _straight_line_depreciation(i: dict) -> ComputeOutcome:
    cost = _req(i, "asset_cost")
    salvage = _req(i, "salvage_value")
    life = _req(i, "useful_life_years")
    if life <= 0:
        raise InvalidInputError("Useful life in years must be positive.")
    if salvage > cost:
        raise InvalidInputError("Salvage value cannot exceed asset cost.")
    depreciable_base = cost - salvage
    value = depreciable_base / life
    return ComputeOutcome(
        value=value,
        steps=[
            f"Depreciable base = Asset cost - Salvage value = {cost} - {salvage} = {depreciable_base}",
            f"Annual depreciation = Depreciable base / Useful life = {depreciable_base} / {life} = {value} per year",
        ],
        assumptions=["Depreciation is allocated evenly across every year of the useful life (no partial-year convention applied)."],
    )


def _declining_balance_depreciation(i: dict) -> ComputeOutcome:
    cost = _req(i, "asset_cost")
    salvage = _req(i, "salvage_value")
    life = _req(i, "useful_life_years")
    factor = _req(i, "declining_balance_factor")
    target_year = _req(i, "target_year")
    if life <= 0:
        raise InvalidInputError("Useful life in years must be positive.")
    if target_year < 1 or target_year != target_year.to_integral_value():
        raise InvalidInputError("Target year must be a positive whole number.")
    if factor <= 0:
        raise InvalidInputError("Declining balance factor must be positive (e.g. 2 for double-declining balance).")

    rate = factor / life
    book_value = cost
    steps = [f"Rate = Declining balance factor / Useful life = {factor} / {life} = {rate}"]
    year_depreciation = Decimal(0)
    for year in range(1, int(target_year) + 1):
        candidate = book_value * rate
        floor = book_value - salvage
        year_depreciation = candidate if candidate <= floor else floor
        if year_depreciation < 0:
            year_depreciation = Decimal(0)
        book_value -= year_depreciation
        steps.append(
            f"Year {year}: depreciation = min(Book value x Rate, Book value - Salvage) = "
            f"min({candidate}, {floor}) = {year_depreciation}; ending book value = {book_value}"
        )
    return ComputeOutcome(
        value=year_depreciation,
        steps=steps,
        assumptions=["Depreciation never reduces book value below the stated salvage value."],
    )


def _simple_interest(i: dict) -> ComputeOutcome:
    principal = _req(i, "principal")
    rate = _req(i, "annual_rate")
    time_years = _req(i, "time_years")
    value = principal * rate * time_years
    return ComputeOutcome(
        value=value,
        steps=[f"Simple interest = Principal x Rate x Time = {principal} x {rate} x {time_years} = {value}"],
    )


def _compound_interest(i: dict) -> ComputeOutcome:
    principal = _req(i, "principal")
    rate = _req(i, "annual_rate")
    time_years = _req(i, "time_years")
    n = _req(i, "compounding_periods_per_year")
    if n <= 0:
        raise InvalidInputError("Compounding periods per year must be positive.")
    growth_factor = (Decimal(1) + rate / n) ** (n * time_years)
    final_amount = principal * growth_factor
    value = final_amount - principal
    return ComputeOutcome(
        value=value,
        steps=[
            f"Growth factor = (1 + Rate/n)^(n x Time) = (1 + {rate}/{n})^({n} x {time_years}) = {growth_factor}",
            f"Final amount = Principal x Growth factor = {principal} x {growth_factor} = {final_amount}",
            f"Compound interest = Final amount - Principal = {final_amount} - {principal} = {value}",
        ],
    )


def _loan_payment(i: dict) -> ComputeOutcome:
    principal = _req(i, "principal")
    annual_rate = _req(i, "annual_rate")
    n_payments = _req(i, "number_of_payments")
    if n_payments <= 0 or n_payments != n_payments.to_integral_value():
        raise InvalidInputError("Number of payments must be a positive whole number.")
    periodic_rate = annual_rate / Decimal(12)
    if periodic_rate == 0:
        value = principal / n_payments
        return ComputeOutcome(
            value=value,
            steps=[f"Zero-interest loan: Payment = Principal / Number of payments = {principal} / {n_payments} = {value}"],
            assumptions=["Monthly compounding assumed (annual rate / 12)."],
        )
    growth = (Decimal(1) + periodic_rate) ** n_payments
    value = principal * (periodic_rate * growth) / (growth - Decimal(1))
    return ComputeOutcome(
        value=value,
        steps=[
            f"Periodic rate = Annual rate / 12 = {annual_rate} / 12 = {periodic_rate}",
            f"Payment = P x [r(1+r)^n] / [(1+r)^n - 1] = {principal} x [{periodic_rate}(1+{periodic_rate})^{n_payments}] / "
            f"[(1+{periodic_rate})^{n_payments} - 1] = {value}",
        ],
        assumptions=["Monthly compounding assumed (annual rate / 12); fully amortizing fixed-rate loan."],
    )


def _audit_sample_size(i: dict) -> ComputeOutcome:
    reliability_factor = _req(i, "reliability_factor")
    tolerable_deviation_rate = _req(i, "tolerable_deviation_rate")
    expected_deviation_rate = _req(i, "expected_deviation_rate")
    denominator = tolerable_deviation_rate - expected_deviation_rate
    if denominator <= 0:
        raise InvalidInputError(
            "Tolerable deviation rate must exceed expected population deviation rate."
        )
    value = reliability_factor / denominator
    return ComputeOutcome(
        value=value,
        steps=[
            f"Sample size = Reliability factor / (Tolerable deviation rate - Expected deviation rate) "
            f"= {reliability_factor} / ({tolerable_deviation_rate} - {expected_deviation_rate}) = {value}"
        ],
        assumptions=[
            "Poisson-based attribute sampling approximation (AICPA Audit Sampling guidance); "
            "reliability_factor must be looked up from the applicable statistical table for the "
            "desired confidence level (risk of overreliance) and expected number of deviations — "
            "this formula does not select that factor.",
            "No finite-population correction applied.",
        ],
    )


_REGISTRY: dict[str, FormulaDefinition] = {}


def _register(definition: FormulaDefinition) -> None:
    _REGISTRY[definition.id] = definition


_register(FormulaDefinition(
    id="accounting.gross_profit.v1", name="Gross profit", version="1.0.0",
    inputs=("revenue", "cost_of_goods_sold"),
    input_units={"revenue": "USD", "cost_of_goods_sold": "USD"},
    output_unit="USD", jurisdiction=None,
    methodology_reference="Revenue - Cost of Goods Sold (standard income statement presentation, US GAAP/IFRS).",
    rounding_policy="two_decimal_places",
    default_assumptions=(), compute=_gross_profit,
))

_register(FormulaDefinition(
    id="accounting.gross_margin.v1", name="Gross margin", version="1.0.0",
    inputs=("revenue", "cost_of_goods_sold"),
    input_units={"revenue": "USD", "cost_of_goods_sold": "USD"},
    output_unit="percent", jurisdiction=None,
    methodology_reference="Gross profit / Revenue (standard profitability ratio, US GAAP/IFRS).",
    rounding_policy="percentage_two_decimal_places",
    default_assumptions=(), compute=_gross_margin,
))

_register(FormulaDefinition(
    id="accounting.operating_profit.v1", name="Operating profit", version="1.0.0",
    inputs=("revenue", "cost_of_goods_sold", "operating_expenses"),
    input_units={"revenue": "USD", "cost_of_goods_sold": "USD", "operating_expenses": "USD"},
    output_unit="USD", jurisdiction=None,
    methodology_reference="Revenue - COGS - Operating expenses (EBIT-style operating profit, standard income statement presentation).",
    rounding_policy="two_decimal_places",
    default_assumptions=(), compute=_operating_profit,
))

_register(FormulaDefinition(
    id="accounting.operating_margin.v1", name="Operating margin", version="1.0.0",
    inputs=("revenue", "cost_of_goods_sold", "operating_expenses"),
    input_units={"revenue": "USD", "cost_of_goods_sold": "USD", "operating_expenses": "USD"},
    output_unit="percent", jurisdiction=None,
    methodology_reference="Operating profit / Revenue (standard profitability ratio).",
    rounding_policy="percentage_two_decimal_places",
    default_assumptions=(), compute=_operating_margin,
))

_register(FormulaDefinition(
    id="finance.current_ratio.v1", name="Current ratio", version="1.0.0",
    inputs=("current_assets", "current_liabilities"),
    input_units={"current_assets": "USD", "current_liabilities": "USD"},
    output_unit="ratio", jurisdiction=None,
    methodology_reference="Current assets / Current liabilities (standard liquidity ratio).",
    rounding_policy="two_decimal_places",
    default_assumptions=(), compute=_current_ratio,
))

_register(FormulaDefinition(
    id="finance.quick_ratio.v1", name="Quick ratio (acid-test)", version="1.0.0",
    inputs=("current_assets", "inventory", "current_liabilities"),
    input_units={"current_assets": "USD", "inventory": "USD", "current_liabilities": "USD"},
    output_unit="ratio", jurisdiction=None,
    methodology_reference="(Current assets - Inventory) / Current liabilities (standard acid-test liquidity ratio).",
    rounding_policy="two_decimal_places",
    default_assumptions=(), compute=_quick_ratio,
))

_register(FormulaDefinition(
    id="finance.debt_to_equity.v1", name="Debt-to-equity ratio", version="1.0.0",
    inputs=("total_liabilities", "total_equity"),
    input_units={"total_liabilities": "USD", "total_equity": "USD"},
    output_unit="ratio", jurisdiction=None,
    methodology_reference="Total liabilities / Total equity (standard leverage ratio).",
    rounding_policy="two_decimal_places",
    default_assumptions=(), compute=_debt_to_equity,
))

_register(FormulaDefinition(
    id="tax.effective_tax_rate.v1", name="Effective tax rate", version="1.0.0",
    inputs=("total_tax_expense", "pretax_income"),
    input_units={"total_tax_expense": "USD", "pretax_income": "USD"},
    output_unit="percent", jurisdiction=None,
    methodology_reference="Total tax expense / Pretax income (standard effective tax rate presentation).",
    rounding_policy="percentage_two_decimal_places",
    default_assumptions=(), compute=_effective_tax_rate,
))

_register(FormulaDefinition(
    id="accounting.break_even_point.v1", name="Break-even point (units)", version="1.0.0",
    inputs=("fixed_costs", "price_per_unit", "variable_cost_per_unit"),
    input_units={"fixed_costs": "USD", "price_per_unit": "USD", "variable_cost_per_unit": "USD"},
    output_unit="count", jurisdiction=None,
    methodology_reference="Fixed costs / (Price per unit - Variable cost per unit) (standard cost-volume-profit analysis).",
    rounding_policy="two_decimal_places",
    default_assumptions=(), compute=_break_even_point,
))

_register(FormulaDefinition(
    id="accounting.straight_line_depreciation.v1", name="Straight-line depreciation", version="1.0.0",
    inputs=("asset_cost", "salvage_value", "useful_life_years"),
    input_units={"asset_cost": "USD", "salvage_value": "USD", "useful_life_years": "years"},
    output_unit="annual_amount", jurisdiction=None,
    methodology_reference="(Asset cost - Salvage value) / Useful life (US GAAP ASC 360 / IFRS IAS 16 standard straight-line method).",
    rounding_policy="two_decimal_places",
    default_assumptions=(), compute=_straight_line_depreciation,
))

_register(FormulaDefinition(
    id="accounting.declining_balance_depreciation.v1", name="Declining-balance depreciation", version="1.0.0",
    inputs=("asset_cost", "salvage_value", "useful_life_years", "declining_balance_factor", "target_year"),
    input_units={
        "asset_cost": "USD", "salvage_value": "USD", "useful_life_years": "years",
        "declining_balance_factor": "ratio", "target_year": "count",
    },
    output_unit="annual_amount", jurisdiction=None,
    methodology_reference="Book value x (Factor / Useful life) each year, floored at salvage value "
                           "(US GAAP ASC 360 / IFRS IAS 16 accelerated depreciation method; factor=2 is double-declining balance).",
    rounding_policy="two_decimal_places",
    default_assumptions=(), compute=_declining_balance_depreciation,
))

_register(FormulaDefinition(
    id="finance.simple_interest.v1", name="Simple interest", version="1.0.0",
    inputs=("principal", "annual_rate", "time_years"),
    input_units={"principal": "USD", "annual_rate": "percent", "time_years": "years"},
    output_unit="USD", jurisdiction=None,
    methodology_reference="Principal x Rate x Time (standard simple-interest formula).",
    rounding_policy="two_decimal_places",
    default_assumptions=(), compute=_simple_interest,
))

_register(FormulaDefinition(
    id="finance.compound_interest.v1", name="Compound interest", version="1.0.0",
    inputs=("principal", "annual_rate", "time_years", "compounding_periods_per_year"),
    input_units={
        "principal": "USD", "annual_rate": "percent", "time_years": "years",
        "compounding_periods_per_year": "count",
    },
    output_unit="USD", jurisdiction=None,
    methodology_reference="Principal x [(1 + Rate/n)^(n x Time) - 1] (standard compound-interest formula).",
    rounding_policy="two_decimal_places",
    default_assumptions=(), compute=_compound_interest,
))

_register(FormulaDefinition(
    id="finance.loan_payment.v1", name="Loan payment (amortizing)", version="1.0.0",
    inputs=("principal", "annual_rate", "number_of_payments"),
    input_units={"principal": "USD", "annual_rate": "percent", "number_of_payments": "count"},
    output_unit="monthly_amount", jurisdiction=None,
    methodology_reference="P x [r(1+r)^n] / [(1+r)^n - 1] (standard fixed-rate amortizing loan payment formula, monthly compounding).",
    rounding_policy="two_decimal_places",
    default_assumptions=(), compute=_loan_payment,
))

_register(FormulaDefinition(
    id="audit.attribute_sample_size.v1", name="Audit sample size (attribute sampling)", version="1.0.0",
    inputs=("reliability_factor", "tolerable_deviation_rate", "expected_deviation_rate"),
    input_units={
        "reliability_factor": "ratio", "tolerable_deviation_rate": "percent",
        "expected_deviation_rate": "percent",
    },
    output_unit="count", jurisdiction=None,
    methodology_reference="Reliability factor / (Tolerable deviation rate - Expected deviation rate) "
                           "(Poisson-based attribute sampling approximation, AICPA Audit Sampling guidance).",
    rounding_policy="round_half_up",
    default_assumptions=(), compute=_audit_sample_size,
))


_register(FormulaDefinition(
    id="accounting.net_profit.v1", name="Net profit", version="1.0.0",
    inputs=("revenue", "total_expenses"), input_units={"revenue": "USD", "total_expenses": "USD"},
    output_unit="USD", jurisdiction=None, methodology_reference="Revenue - Total expenses (standard profit calculation).",
    rounding_policy="two_decimal_places", default_assumptions=(), compute=_net_profit,
))
_register(FormulaDefinition(
    id="accounting.inventory_turnover.v1", name="Inventory turnover", version="1.0.0",
    inputs=("cost_of_goods_sold", "average_inventory"), input_units={"cost_of_goods_sold": "USD", "average_inventory": "USD"},
    output_unit="ratio", jurisdiction=None, methodology_reference="Cost of goods sold / Average inventory (standard activity ratio).",
    rounding_policy="two_decimal_places", default_assumptions=(), compute=_inventory_turnover,
))
_register(FormulaDefinition(
    id="accounting.receivables_days.v1", name="Receivables days", version="1.0.0",
    inputs=("average_receivables", "credit_revenue", "days_in_period"), input_units={"average_receivables": "USD", "credit_revenue": "USD", "days_in_period": "count"},
    output_unit="days", jurisdiction=None, methodology_reference="Average receivables / Credit revenue x Days in period.",
    rounding_policy="two_decimal_places", default_assumptions=(), compute=_receivables_days,
))
_register(FormulaDefinition(
    id="tax.taxable_income_scenario.v1", name="Taxable income scenario", version="1.0.0",
    inputs=("gross_income", "adjustments", "deductions"), input_units={"gross_income": "USD", "adjustments": "USD", "deductions": "USD"},
    output_unit="USD", jurisdiction=None, methodology_reference="User-supplied gross income less user-supplied adjustments and deductions; arithmetic scenario only.",
    rounding_policy="two_decimal_places", default_assumptions=(), compute=_taxable_income_scenario,
))
_register(FormulaDefinition(
    id="tax.tax_from_supplied_rate.v1", name="Tax from user-supplied rate", version="1.0.0",
    inputs=("taxable_base", "user_supplied_rate"), input_units={"taxable_base": "USD", "user_supplied_rate": "percent"},
    output_unit="USD", jurisdiction=None, methodology_reference="Taxable base x explicitly user-supplied rate; legal applicability is not determined.",
    rounding_policy="two_decimal_places", default_assumptions=(), compute=_tax_from_supplied_rate,
))
_register(FormulaDefinition(
    id="audit.materiality.v1", name="Audit materiality", version="1.0.0",
    inputs=("benchmark_amount", "user_selected_percentage"), input_units={"benchmark_amount": "USD", "user_selected_percentage": "percent"},
    output_unit="USD", jurisdiction=None, methodology_reference="User-selected benchmark x user-selected percentage; selection remains professional judgment.",
    rounding_policy="two_decimal_places", default_assumptions=(), compute=_audit_materiality,
))
_register(FormulaDefinition(
    id="audit.projected_misstatement.v1", name="Projected misstatement", version="1.0.0",
    inputs=("sample_misstatement", "sample_book_value", "population_book_value"), input_units={"sample_misstatement": "USD", "sample_book_value": "USD", "population_book_value": "USD"},
    output_unit="USD", jurisdiction=None, methodology_reference="Ratio projection: sample misstatement / sample book value x population book value.",
    rounding_policy="two_decimal_places", default_assumptions=(), compute=_projected_misstatement,
))
_register(FormulaDefinition(
    id="audit.sampling_interval.v1", name="Audit sampling interval", version="1.0.0",
    inputs=("tolerable_misstatement", "sample_size"), input_units={"tolerable_misstatement": "USD", "sample_size": "count"},
    output_unit="USD", jurisdiction=None, methodology_reference="Tolerable misstatement / sample size (simple monetary-unit sampling interval).",
    rounding_policy="two_decimal_places", default_assumptions=(), compute=_sampling_interval,
))


def list_formulas() -> list[FormulaDefinition]:
    return list(_REGISTRY.values())


def get_formula(formula_id: str) -> Optional[FormulaDefinition]:
    return _REGISTRY.get(formula_id)


def execute_formula(formula_id: str, raw_inputs: dict) -> FormulaResult:
    """raw_inputs shape: {name: {"value": <raw>, "unit": <unit>}}. Always
    returns a FormulaResult — never raises — so a caller gets a structured
    'why this failed' answer instead of an exception to catch."""
    calculation_id = _new_calculation_id()
    executed_at = datetime.now(timezone.utc).isoformat()
    definition = get_formula(formula_id)

    if definition is None:
        return FormulaResult(
            calculation_id=calculation_id, formula_id=formula_id, formula_version="",
            engine=ENGINE_NAME, engine_version=ENGINE_VERSION,
            inputs=raw_inputs, executed_at=executed_at, status="error",
            errors=[f"Unknown formula id: {formula_id!r}."],
        )

    missing = [name for name in definition.inputs if name not in raw_inputs]
    if missing:
        return FormulaResult(
            calculation_id=calculation_id, formula_id=formula_id, formula_version=definition.version,
            engine=ENGINE_NAME, engine_version=ENGINE_VERSION,
            inputs=raw_inputs, executed_at=executed_at, status="missing_input",
            errors=[f"Missing required input(s): {missing}"],
            methodology_reference=definition.methodology_reference,
        )

    normalized: dict[str, Decimal] = {}
    for name in definition.inputs:
        raw = raw_inputs[name]
        unit = raw.get("unit") if isinstance(raw, dict) else definition.input_units.get(name)
        value = raw.get("value") if isinstance(raw, dict) else raw
        expected_unit = definition.input_units.get(name)
        if expected_unit and unit and unit != expected_unit and not (
            expected_unit == "percent" and unit == "decimal_rate"
        ) and not (expected_unit == "decimal_rate" and unit == "percent"):
            return FormulaResult(
                calculation_id=calculation_id, formula_id=formula_id, formula_version=definition.version,
                engine=ENGINE_NAME, engine_version=ENGINE_VERSION,
                inputs=raw_inputs, executed_at=executed_at, status="invalid_input",
                errors=[f"Input {name!r} expects unit {expected_unit!r}, got {unit!r}."],
                methodology_reference=definition.methodology_reference,
            )
        try:
            normalized[name] = normalize_value(value, unit or expected_unit or "count")
        except UnitError as exc:
            return FormulaResult(
                calculation_id=calculation_id, formula_id=formula_id, formula_version=definition.version,
                engine=ENGINE_NAME, engine_version=ENGINE_VERSION,
                inputs=raw_inputs, executed_at=executed_at, status="invalid_input",
                errors=[f"Input {name!r}: {exc.reason}"],
                methodology_reference=definition.methodology_reference,
            )

    try:
        outcome = definition.compute(normalized)
    except MissingInputError as exc:
        return FormulaResult(
            calculation_id=calculation_id, formula_id=formula_id, formula_version=definition.version,
            engine=ENGINE_NAME, engine_version=ENGINE_VERSION,
            inputs=raw_inputs, executed_at=executed_at, status="missing_input",
            errors=[str(exc)], methodology_reference=definition.methodology_reference,
        )
    except InvalidInputError as exc:
        return FormulaResult(
            calculation_id=calculation_id, formula_id=formula_id, formula_version=definition.version,
            engine=ENGINE_NAME, engine_version=ENGINE_VERSION,
            inputs=raw_inputs, executed_at=executed_at, status="invalid_input",
            errors=[exc.reason], methodology_reference=definition.methodology_reference,
        )
    except (InvalidOperation, DivisionByZero, ZeroDivisionError) as exc:
        return FormulaResult(
            calculation_id=calculation_id, formula_id=formula_id, formula_version=definition.version,
            engine=ENGINE_NAME, engine_version=ENGINE_VERSION,
            inputs=raw_inputs, executed_at=executed_at, status="error",
            errors=[f"Arithmetic error: {exc}"], methodology_reference=definition.methodology_reference,
        )

    try:
        rounded = round_value(outcome.value, definition.rounding_policy)
    except Exception as exc:  # rounding.RoundingError, or a bad policy string
        return FormulaResult(
            calculation_id=calculation_id, formula_id=formula_id, formula_version=definition.version,
            engine=ENGINE_NAME, engine_version=ENGINE_VERSION,
            inputs=raw_inputs, executed_at=executed_at, status="error",
            errors=[f"Rounding error: {exc}"], methodology_reference=definition.methodology_reference,
        )

    return FormulaResult(
        calculation_id=calculation_id,
        formula_id=formula_id,
        formula_version=definition.version,
        engine=ENGINE_NAME,
        engine_version=ENGINE_VERSION,
        inputs=raw_inputs,
        output_value=str(rounded),
        output_unit=definition.output_unit,
        steps=outcome.steps,
        assumptions=list(definition.default_assumptions) + outcome.assumptions,
        rounding_policy=definition.rounding_policy,
        methodology_reference=definition.methodology_reference,
        executed_at=executed_at,
        status="verified",
        errors=[],
    )
