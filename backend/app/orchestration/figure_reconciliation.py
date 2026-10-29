"""Every material figure Kriton shows must come from verified data
(ZL-ENG-AGT-01 §07.5, gate G4).

A figure in an answer is accepted, at the precision it is written to, when it
is (unreconciled_figures):

1. stated by the evidence — the question, the conversation, retrieved sources,
   tool data — or by the application calculator;
2. a running total within one line or bulleted list of the user's facts;
3. the result of an equation the same statement shows, that holds, on
   verified operands; or one step (±, ×, ÷, % change) from a verified figure
   the same statement shows and a verified figure (the user's, the
   calculator's, or the answer's own already accepted); or one step between
   two figures the user stated together on one line;
4. a difference or percentage change between two figures of the answer that
   are already supported.

The prompt's own instructions and examples are never operands. Until
2026-10-17 any pair or run of numbers anywhere in the evidence, rescaled by
10ⁿ and matched within 0.2%, counted; 70–84% of fabricated figures passed.
Which period or scenario a verified figure belongs to is checked separately
(figure_attribution).

"Material" means a figure a reader would act on: an amount with a currency
sign or code, a percentage or percentage-point change, an amount with a scale
word (million, bn, lakh, crore …) or a comma-grouped number. Years, section
and form numbers ("Section 44AB", "VAT Notice 700"), list markers, dates and
[REF-n] markers are not checked.
"""
from __future__ import annotations

import re

_NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
_SCALES = (1.0, 1e2, 1e3, 1e5, 1e6, 1e7, 1e9, 1e12)
_RUNNING_TOTAL_SPAN = 24
_RUNNING_TOTAL_MAX_NUMBERS = 400
_PAIRWISE_MAX_NUMBERS = 60

_CODE_FENCE = re.compile(r"```[\s\S]*?```")
_REF = re.compile(r"\[REF-\d+\]")
_FIGURE = re.compile(
    r"(?<![\w.\-/])"
    r"(?P<currency>[£$€₹¥]\s?|(?:USD|GBP|EUR|INR|AUD|CAD|Rs\.?)\s)?"
    r"(?P<number>-?\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|-?\d+(?:\.\d+)?)"
    r"(?![\w/\-]\d)"
    r"(?:\s?(?P<unit>%|pp\b|percentage points?\b|per ?cent\b|bn\b|billion\b|million\b|mn\b|trillion\b|"
    r"lakhs?\b|crores?\b|k\b|m\b))?",
    re.IGNORECASE,
)


_JSON_ESCAPE = re.compile(r"\\u([0-9a-fA-F]{4})")


# Thousands grouped with a space: "£24 000", or a narrow/thin/no-break space
# ("£2 000"). A plain space counts only straight after a currency.
# Every Unicode space but the plain one (figure, thin, hair, en/em ...), the
# zero-width space, the Arabic thousands separator and apostrophe grouping
# ("93'736.12"): "£93 736.12" written with a figure space was read as £93.
_GROUP_SEPARATORS = "\u00a0\u1680\u2000-\u200b\u202f\u205f\u3000\u066c'\u2019"
_SPACE_GROUPED = re.compile(rf"(?<![\d.,])\d{{1,3}}(?:[{_GROUP_SEPARATORS}]\d{{3}})+(?![\d'\u2019])")
_CURRENCY_SPACE_GROUPED = re.compile(r"((?:[£$€₹¥]|\b(?:USD|GBP|EUR|INR))\s?)(\d{1,3}(?: \d{3})+)(?!\d)")


def _comma_grouped(text: str) -> str:
    """"£2 000" as "£2,000". Read as £2, the IFRS 15 schedule rows ("Oct 2025
    | £2 000 | … | £2 000") matched none of the calculator's results and every
    row was removed as an uncited claim, leaving an empty table."""
    text = _SPACE_GROUPED.sub(lambda match: re.sub(r"\D", ",", match.group(0)), text)
    return _CURRENCY_SPACE_GROUPED.sub(lambda match: match.group(1) + match.group(2).replace(" ", ","), text)


# An illustrative example inside a source: its figures describe the example's
# entity, not the user's. Applied to a user's case they are an assumed input:
# "the SME expects to recover only 20%" in a source example became "if the
# same expectation applies here … £15,000 × 20% = £3,000, impairment £12,000"
# for a customer in administration whose recovery the user never gave
# (28 Oct 2026). From the marker to the end of its paragraph; the rule text
# before it keeps its figures.
_EXAMPLE_MARKER = re.compile(
    r"(?im)^\s*(?:example|illustration|illustrative\s+example|case\s+study)\b"
    r"|\b(?:illustrative\s+example|worked\s+example|example\s+\d+|illustration\s+\d+"
    r"|in\s+(?:this|the|that|our)\s+example|suppose\s+(?:that\s+)?(?:an?|the)\b|assume\s+that|hypothetical)\b"
)


def without_example_figures(source_text: str) -> str:
    """A source passage with the figures of its illustrative examples masked,
    so they are never evidence for, or operands in, a figure about the user's
    own case. Only for retrieved source text, never the user's own words."""
    def masked(paragraph: str) -> str:
        marker = _EXAMPLE_MARKER.search(paragraph)
        if not marker:
            return paragraph
        return paragraph[:marker.start()] + re.sub(r"\d", "#", paragraph[marker.start():])
    return "".join(masked(part) for part in re.split(r"(\n\s*\n)", source_text or ""))


def _readable(evidence: str) -> str:
    """The conversation reaches the prompt as ASCII-escaped JSON, so an
    earlier answer's "£540,000" read as "\\u00a3540,000": the number 3,540,000
    and no money figure at all, and "£98,400 more than the original" could not
    be checked against it."""
    return _comma_grouped(_JSON_ESCAPE.sub(lambda match: chr(int(match.group(1), 16)), evidence or ""))


def known_values(evidence: str) -> list[float]:
    """Every value the evidence states or directly implies: stated numbers at
    every unit scale (a change of unit: 1,200,000 as "1.2 million"), running
    totals of consecutive numbers on one line (a list or a waterfall: "Jan 100,
    Feb 150, …"), and pairwise differences and percentage changes.

    Only stated numbers are rescaled, and running totals stay within a line:
    summed across the whole prompt and rescaled, fourteen unrelated numbers
    "made" £77,777 and 70% of fabricated figures passed (2026-10-17)."""
    evidence = _readable(evidence).replace("−", "-")
    stated = [float(token.replace(",", "")) for token in _NUMBER.findall(evidence)]
    running: list[float] = []
    if len(stated) <= _RUNNING_TOTAL_MAX_NUMBERS:
        for line in evidence.splitlines():
            numbers = [float(token.replace(",", "")) for token in _NUMBER.findall(line)]
            for start in range(len(numbers)):
                total = 0.0
                for value in numbers[start:start + _RUNNING_TOTAL_SPAN]:
                    total += value
                    running.append(total)
    derived: list[float] = []
    if len(stated) <= _PAIRWISE_MAX_NUMBERS:
        for a in stated:
            for b in stated:
                if a != b:
                    derived.append(b - a)
                    if a:
                        derived.append((b - a) / a * 100)
    scaled = [value * scale for value in stated for scale in _SCALES] + [value / scale for value in stated for scale in _SCALES]
    return scaled + running + derived


def tolerance_for(shown: str | None, value: float) -> float:
    """How far a figure may sit from a verified value: the existing 0.2%
    bound, never more than half a unit of the precision it is written to.
    "£48,213.57" is exact to the penny; within 0.2% it matched £48,000 + 122."""
    relative = max(abs(value) * 0.002, 0.006)
    if not shown:
        return relative
    number = re.search(r"\d[\d,]*(?:\.(\d+))?", shown)
    if not number:
        return relative
    decimals = number.group(1)
    if decimals:
        display = 0.5 * 10 ** -len(decimals)
    else:
        digits = number.group(0).replace(",", "")
        zeros = len(digits) - len(digits.rstrip("0")) if digits.strip("0") else 0
        display = 0.5 * 10 ** zeros                  # "£1,418,000" is rounded to the thousand
    return min(relative, display + 1e-9)


_UNIT_SCALE = {"k": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6, "bn": 1e9, "billion": 1e9, "trillion": 1e12,
               "lakh": 1e5, "lakhs": 1e5, "crore": 1e7, "crores": 1e7}


def _absolute(shown: str, value: float) -> float | None:
    """"£0.24m" as 240,000, to compare with a difference of two full amounts."""
    unit = re.search(r"(?:\d)\s?([A-Za-z]+)\s*$", shown or "")
    scale = _UNIT_SCALE.get(unit.group(1).lower()) if unit else None
    return value * scale if scale else None


def is_known(value: float, known: list[float], tolerance: float | None = None) -> bool:
    if value == 0:
        return True
    tolerance = max(abs(value) * 0.002, 0.006) if tolerance is None else tolerance
    # Sign-insensitive: a loss stated as "−5" may be written as a 5 loss.
    return any(abs(abs(value) - abs(k)) <= tolerance for k in known)


def material_figures(text: str) -> list[tuple[str, float]]:
    """(as written, numeric value) for each material figure in prose."""
    prose = _REF.sub(" ", _CODE_FENCE.sub(" ", _comma_grouped((text or "").replace("−", "-"))))
    figures = []
    for match in _FIGURE.finditer(prose):
        currency, number, unit = match.group("currency"), match.group("number"), match.group("unit")
        unit_word = (unit or "").lower()
        if unit_word == "m" and not currency:
            continue  # "5 m" is metres or minutes unless it is money
        if not (currency or unit or "," in number):
            continue
        figures.append((match.group(0).strip(), float(number.replace(",", ""))))
    return figures


_YEAR = re.compile(r"(?:19|20)\d{2}")
_LIST_ITEM = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
_BASE_MAX = 60


def _direct_values(evidence: str, calculations: str) -> list[float]:
    """Stated and calculated values: every number the evidence (the question,
    the conversation, retrieved sources, tool data) or the calculator states,
    and the evidence's
    own scale words as amounts ("$1.2 million" as 1,200,000). Not rescaled
    otherwise: ×/÷ 10ⁿ of every number accepted £1.3m, £5.5m … by chance.
    A percentage figure may also restate a fraction (see unreconciled_figures)."""
    text = _readable(evidence + "\n" + calculations).replace("−", "-")
    values = [float(token.replace(",", "")) for token in _NUMBER.findall(text)]
    values += [amount for shown, value in material_figures(text) if (amount := _absolute(shown, value)) is not None]
    return values


def _percent_values(evidence: str, calculations: str) -> list[float]:
    """What a percentage figure may restate: a percentage the evidence states,
    a measured (non-integer) value from the evidence or tool data ("growth
    2.1"), or a calculator result, also as a fraction ×100 (0.4156 → 41.56%).
    Not a bare whole number: "31%" matched the 31 of "31 March", and "25%"
    some count, so a quarter of fabricated whole-number percentages passed."""
    text = _readable(evidence).replace("−", "-")
    values = [value for shown, value in material_figures(text) if _is_percentage(shown)]
    plain = [float(token.replace(",", "")) for token in _NUMBER.findall(text)]
    values += [value for value in plain if value != int(value)]
    values += [value * 100 for value in plain if 0 < abs(value) < 1]
    calculated = [float(token.replace(",", "")) for token in _NUMBER.findall(_readable(calculations))]
    return values + calculated + [value * 100 for value in calculated]


def _is_percentage(shown: str) -> bool:
    return bool(re.search(r"%|\bpp\b|percentage points?|per ?cent", shown or "", re.I))


def _line_totals(facts: str) -> list[float]:
    """Running totals within one line of the user's facts: a list or a
    waterfall ("Opening 50,000; sales +80,000; salaries −45,000 …")."""
    totals: list[float] = []
    lines = _readable(facts).replace("−", "-").splitlines()
    groups = [[float(token.replace(",", "")) for token in _NUMBER.findall(line)] for line in lines]
    # A bulleted list is one list too: "- Salaries: £165,000 / - Rent: £48,000 …"
    # (operating expenses £314,000), one amount to an item.
    block: list[float] = []
    for line in lines + [""]:
        amounts = [_amount(shown, value) for shown, value in material_figures(line)]
        if _LIST_ITEM.match(line) and len(amounts) == 1:
            block += amounts
            continue
        if len(block) >= 2:
            groups.append(block)
        block = []
    for numbers in groups:
        if len(numbers) > _RUNNING_TOTAL_SPAN * 4:
            continue
        for start in range(len(numbers)):
            total = 0.0
            for value in numbers[start:start + _RUNNING_TOTAL_SPAN]:
                total += value
                totals.append(total)
    return totals


def _derivation_base(facts: str, calculations: str) -> list[float]:
    """The verified numbers a derived figure may be computed from: the user's
    figures (not years) and the calculator's operands and results. Never the
    prompt's instructions or examples: their numbers made £48,213.57 (rent
    £48,000 + an example's 122, within 0.2%). Too many to search safely:
    only the user's material figures and the calculator's, else none."""
    text = _readable(facts).replace("−", "-")
    calculated = [float(token.replace(",", "")) for token in _NUMBER.findall(_readable(calculations))]
    amounts = [amount for shown, value in material_figures(text) if (amount := _absolute(shown, value)) is not None]
    for candidate in (
        [float(token.replace(",", "")) for token in _NUMBER.findall(text) if not _YEAR.fullmatch(token.rstrip(","))],
        [value for _, value in material_figures(text)],
    ):
        base = list(dict.fromkeys(candidate + amounts + calculated))
        if len(base) <= _BASE_MAX:
            return base
    return []


def _statements(text: str) -> list[str]:
    """Each sentence or table row, outside code blocks."""
    pieces: list[str] = []
    in_fence = False
    for line in (text or "").splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not line.strip():
            continue
        pieces += [line.strip()] if line.lstrip().startswith("|") else _SENTENCE_END.split(line.strip())
    return pieces


def _fact_groups(facts: str) -> list[list[float]]:
    """The user's amounts stated together: line by line ("Original price
    £20,000. Revised price £22,260."), at most eight to a line."""
    groups = []
    for line in _readable(facts).splitlines():
        amounts = list(dict.fromkeys(_amount(shown, value) for shown, value in material_figures(line)))
        amounts += [value for value in _plain_numbers(line) if value not in amounts]
        if 2 <= len(amounts) <= 8:
            groups.append(amounts)
    return groups


def _plain_numbers(text: str) -> list[float]:
    """Numbers that are not material figures but are operands: an exchange
    rate written "US$1.30", a multiplier, a count. Years are not."""
    # A token keeps a trailing comma ("January 1, 2026, Nexus"): stripped
    # before the year test, or 2026 became an operand.
    return [float(token.replace(",", "")) for token in _NUMBER.findall(_readable(text).replace("−", "-"))
            if not _YEAR.fullmatch(token.lstrip("-").rstrip(","))]


# A chain of rounded factors misses its exact result by a little: "9.00% ×
# 1.68 × 1.77 = 26.74%" (26.76). Within this, an equation is not evidence
# either way.
_ROUNDING_SLACK = 0.005


def _equations(piece: str) -> list[tuple[float, list[float], str]]:
    """(result, operands, verdict) of each equation the statement shows:
    "holds", "rounding" (off by no more than rounded factors explain) or
    "fails". "Profit = 6,000 × £18 − £72,000 = £36,000" → (36,000, [6,000, 18,
    72,000], "holds"). Read and evaluated as validate_answer_calculations
    reads them."""
    from app.orchestration.calculation_service import _EQUATION, _evaluate, _normalise_arithmetic, plain_arithmetic
    # As the arithmetic check reads it: "= **26.74 %**" was not read as a
    # result, and a correct ROE was removed (22 Oct 2026).
    plain = plain_arithmetic(piece)
    normalized = _normalise_arithmetic(plain.replace("\\times", "*").replace("\\div", "/"))
    found = []
    for match in _EQUATION.finditer(normalized):
        expression = match.group("expression")
        if not any(operator in expression for operator in "+-*/×÷"):
            continue
        try:
            computed = float(_evaluate(expression.strip()))
            stated = float(match.group("result").replace(",", ""))
        except (SyntaxError, ValueError, ArithmeticError, TypeError):
            continue
        percent = bool(match.group("percent"))
        candidates = [computed, computed * 100] if percent else [computed]
        miss = min(abs(candidate - stated) for candidate in candidates)
        if miss <= max(abs(stated) * 0.0005, 0.006):
            verdict = "holds"
        elif miss <= max(abs(stated) * _ROUNDING_SLACK, 0.006):
            verdict = "rounding"
        else:
            verdict = "fails"
        # "6.0%" was normalised to "(6.0/100)": that 100 is notation, not an
        # operand to verify (a correct CAPM cost of equity was removed).
        operands = [float(token.replace(",", "")) for token in _NUMBER.findall(re.sub(r"/100\)", ")", expression))]
        found.append((stated, [abs(operand) for operand in operands], verdict))
    return found


def _equation_results(piece: str) -> list[tuple[float, list[float]]]:
    """(result, operands) of each equation the statement shows and that holds."""
    return [(stated, operands) for stated, operands, verdict in _equations(piece) if verdict == "holds"]


def _amount(shown: str, value: float) -> float:
    absolute = _absolute(shown, value)
    return value if absolute is None else absolute


_PAIR_SEARCH_MIN_DIGITS = 6


def reference_percentages(statement: str) -> list[float]:
    from app.orchestration.accounting_concepts import reference_percentages as published
    return published(statement)


def _significant_digits(shown: str) -> int:
    """Digits a figure states: "42,123.64" has 7, "£1,560,000" has 3, "83%" 2."""
    digits = re.sub(r"[^\d.]", "", shown or "")
    if "." in digits:
        return len(digits.replace(".", "").lstrip("0"))
    return len(digits.lstrip("0").rstrip("0"))


_TWO_STEP_MIN_DIGITS = 7
_TWO_STEP_MAX_OPERANDS = 16


# Adding or subtracting a count to an amount is not a financial step:
# "$210,608" passed as 210,618 − 5 − 5 (the 5 of "5-year"), a near-miss of the
# real present value — the error a typo or slip produces. In the derivation
# rules below, a sum or difference needs operands of comparable size.
_ADDITIVE_MIN_RATIO = 0.01


def _comparable(a: float, b: float) -> bool:
    big, small = max(abs(a), abs(b)), min(abs(a), abs(b))
    return big == 0 or small / big >= _ADDITIVE_MIN_RATIO


def _derived_values(a: float, b: float) -> list[float]:
    values = [a * b]
    if _comparable(a, b):
        values += [a + b, a - b, b - a]
    if b:
        values.append(a / b)
    if a:
        values.append(b / a)
    return values


def _one_step_values(numbers: list[float]) -> list[float]:
    """Every a ± b (of comparable size), a × b and a ÷ b over the numbers:
    the intermediates of a two-step figure."""
    values = []
    for a in numbers:
        for b in numbers:
            values += _derived_values(a, b)
    return list(dict.fromkeys(values))


def _derived_in_one_step(value: float, tolerance: float, numbers: list[float]) -> bool:
    target = abs(value)
    return any(abs(target - abs(x)) <= tolerance for a in numbers for b in numbers for x in _derived_values(a, b))


def _two_step_from(value: float, tolerance: float, steps: list[float], operands: list[float]) -> bool:
    """One more operation on an intermediate: (a op b) op c, c a verified
    number. Intermediates × operands only — about 16k pairs at the operand
    limit, not intermediates × intermediates."""
    target = abs(value)
    return any(abs(target - abs(x)) <= tolerance for p in steps for c in operands for x in _derived_values(p, c))


# "5-year", "6 years", "36 months", "10,000 options": a count with its unit.
_LIKE_QUANTITY = re.compile(
    r"\b(\d[\d,]*(?:\.\d+)?)[- ]?(years?|months?|weeks?|days?|units?|employees?|shares?|options?|accounts?|items?)\b",
    re.I,
)


def _share_of_like_quantities(value: float, tolerance: float, statement: str, facts: str) -> bool:
    """The percentage states one user-given quantity as a share of another of
    the same unit, and the statement says what it is a share of."""
    if not re.search(r"%\s*(?:of|is)\b|\bof (?:the|its)\b", statement or "", re.I):
        return False
    by_unit: dict[str, list[float]] = {}
    for number, unit in _LIKE_QUANTITY.findall(_readable(facts)):
        by_unit.setdefault(unit.lower().rstrip("s"), []).append(float(number.replace(",", "")))
    for quantities in by_unit.values():
        for a in quantities:
            for b in quantities:
                if a != b and b and abs(value - a / b * 100) <= max(tolerance, 0.5):
                    return True
    return False


def _one_step_from(value: float, tolerance: float, local: list[float], base: list[float]) -> bool:
    """One operation on a figure the statement itself shows and a verified
    figure: the formula's operand is on the page. "Gross margin 41.56%" beside
    £505,000 (505,000 ÷ 1,215,000); a "+1.56 pp" table cell beside 41.56% and
    40.00%. Searching every pair of ~60 numbers instead accepted 70–84% of
    fabricated figures (2026-10-17)."""
    for a in local:
        for b in list(dict.fromkeys(base + local)):
            # "| Senior debt | $7,000,000 | 7% | $490,000 |": an amount at a rate.
            candidates = [a + b, a - b, b - a, a * b, a * b / 100]
            if b:
                candidates += [a / b, a / b * 100, (a - b) / b * 100]
            if a:
                candidates += [b / a, b / a * 100, (b - a) / a * 100]
            if any(abs(abs(value) - abs(c)) <= tolerance for c in candidates):
                return True
    return False


_MONEY = re.compile(r"[£$€₹¥]|\b(?:USD|GBP|EUR|INR|AUD|CAD|JPY|SGD|AED)\b")
# An opening and a closing balance are of similar size; within 2× keeps a
# line's prices, units and costs from being averaged with one another.
_AVERAGE_MIN_RATIO = 0.5


def _money_groups(facts: str) -> list[list[float]]:
    """The user's money amounts, line by line ("Total Equity $1,600,000
    $1,900,000")."""
    groups = []
    for line in _readable(facts).splitlines():
        amounts = list(dict.fromkeys(_amount(shown, value) for shown, value in material_figures(line)
                                     if _MONEY.search(shown)))
        if 2 <= len(amounts) <= 8:
            groups.append(amounts)
    return groups


def _average_of_pair(value: float, tolerance: float, group: list[float]) -> bool:
    """The average of two money amounts the user gave on one line: opening
    and closing balances of a comparative table row ("Total Equity
    $1,600,000 $1,900,000" → average equity $1,750,000). The DuPont answer's
    average equity and assets, and every ratio built on them, were removed as
    unverified (22 Oct 2026)."""
    target = abs(value)
    return any(abs(target - abs(a + b) / 2) <= tolerance
               for i, a in enumerate(group) for b in group[i + 1:]
               if a != b and min(abs(a), abs(b)) >= _AVERAGE_MIN_RATIO * max(abs(a), abs(b)))


_ROW_MAX_OPERANDS = 8


def _column_runs(text: str) -> dict[str, list[list[float]]]:
    """For each table cell's figure, the runs of figures directly above it in
    its column: "| Total pre-tax interest | | | $790,000 |" under $490,000 and
    $300,000."""
    runs: dict[str, list[list[float]]] = {}
    table: list[list[str]] = []
    for line in (text or "").splitlines() + [""]:
        stripped = line.strip()
        if stripped.startswith("|"):
            if not re.fullmatch(r"\|?[\s:|-]+\|?", stripped):
                table.append([cell.strip() for cell in stripped.strip("|").split("|")])
            continue
        for row_index, row in enumerate(table):
            for column, cell in enumerate(row):
                figures = material_figures(cell)
                if len(figures) != 1:
                    continue
                above = []
                for earlier in reversed(table[:row_index]):
                    cell_above = material_figures(earlier[column]) if column < len(earlier) else []
                    if len(cell_above) != 1:
                        break
                    above.append(_amount(*cell_above[0]))
                    if len(above) >= 2:
                        runs.setdefault(figures[0][0], []).append(list(above))
        table = []
    return runs


def _row_combination(value: float, tolerance: float, operands: list[float]) -> bool:
    """A table cell that adds or subtracts verified cells of its own row:
    "| 1 | 500,000 | 200,000 | 160,000 | 140,000 | 29,400 | 270,600 |" (EBIT
    500,000 − 200,000 − 160,000; cash flow 140,000 − 29,400 + 160,000). The
    NPV answer's Years 1, 3 and 4 were removed for lack of this (22 Oct 2026).
    Operands of comparable size only (a year number is not one)."""
    from itertools import product
    usable = [operand for operand in dict.fromkeys(operands) if operand and _comparable(operand, value)]
    if not 2 <= len(usable) <= _ROW_MAX_OPERANDS:
        return False
    target = abs(value)
    for signs in product((-1, 0, 1), repeat=len(usable)):
        if sum(1 for sign in signs if sign) >= 2 and abs(target - abs(sum(
                sign * operand for sign, operand in zip(signs, usable)))) <= tolerance:
            return True
    return False


def _stated_rates(facts: str) -> tuple[list[float], list[float]]:
    """The question's money amounts and its percentages."""
    amounts, rates = [], []
    for shown, value in material_figures(_readable(facts)):
        if _is_percentage(shown):
            rates.append(value)
        elif _MONEY.search(shown):
            amounts.append(_amount(shown, value))
    return list(dict.fromkeys(amounts)), list(dict.fromkeys(rates))


def _rate_of_stated_amount(value: float, tolerance: float, amounts: list[float], rates: list[float]) -> bool:
    """An amount the question states at a percentage it states: MACRS
    depreciation $800,000 × 19.2% = 153,600 (the rates and the cost share a
    line too long for the same-line rule; 22 Oct 2026)."""
    return any(abs(abs(value) - abs(amount * rate / 100)) <= tolerance for amount in amounts for rate in rates)


def _restates_own_decimal(amount: float, tolerance: float, accepted: list[float]) -> bool:
    """A percentage restating a decimal this answer verified: WACC 0.103218
    shown as 10.32%, a weight 0.285714 as 29% (removed, 22 Oct 2026)."""
    return any(0 < abs(value) < 1 and abs(abs(amount) / 100 - abs(value)) <= tolerance / 100 for value in accepted)


def _change_between(value: float, tolerance: float, verified: list[float]) -> bool:
    for a in verified:
        for b in verified:
            if a == b:
                continue
            if abs(abs(value) - abs(a - b)) <= tolerance or (b and abs(abs(value) - abs((a - b) / b * 100)) <= tolerance):
                return True
    return False


def unreconciled_figures(text: str, evidence: str, calculations: str = "", stated: str | None = None) -> list[str]:
    """Material figures in `text` that no verified value supports. The made-up
    amounts of a labelled illustrative example are not claims (derived_output.py).

    A figure is supported when it is
    1. stated in the evidence or by the calculator (`calculations`), allowing
       rounding to the precision written and a percentage/fraction form;
    2. a running total within one line of the user's facts; or
    3. the result of an equation the same statement shows, that holds, and
       whose every operand is itself verified; or one step (±, ×, ÷, % change)
       from a figure shown in the same sentence
       or table row and a verified figure — the user's figures (`stated`, else
       the evidence), the calculator's, or figures of the answer already
       accepted this way (a prior-year profit, then its change); or
    4. a difference or percentage change between two figures of the answer
       already supported.
    """
    from app.orchestration.derived_output import scenario_text, without_scenarios
    body = without_scenarios(text)
    if not material_figures(body):
        return []
    # An example's own givens are the facts its checked lines work from.
    facts = "\n".join([stated if stated is not None else evidence, scenario_text(text)])
    direct = _direct_values(evidence, calculations) + _line_totals(facts)
    direct_percent = _percent_values(evidence, calculations)
    base = _derivation_base(facts, calculations)
    pending: list[tuple[str, float, list[float], float]] = []
    coarse: list[tuple[str, float]] = []
    approximates: list[tuple[str, float, float]] = []
    accepted: list[float] = []
    equations: list[tuple[float, list[float]]] = []
    # Figures whose own statement shows the equation for them: that equation
    # decides (it holds and its every operand is verified), never a pair rule.
    # "WACC = 28.57% × 5.98% + 3.76% × 8.00% + 67.67% × 12.3% = 11.33%" (the
    # sum is 10.33%) passed as one step from two other figures of the line;
    # "7.57% × (1 − 0.25) = 5.68%" with a 21% tax rate likewise.
    bound: set[int] = set()
    # Results of an equation that does not hold are the arithmetic check's
    # (validate_answer_calculations): it names the correct result, where
    # this check could only call the figure unverified.
    miscalculated: set[int] = set()
    row_items: set[int] = set()
    column_runs = _column_runs(body)
    for piece in _statements(body):
        figures = material_figures(piece)
        amounts = [_amount(shown, value) for shown, value in figures]
        shown_equations = _equations(piece)
        equations += [(stated_result, operands) for stated_result, operands, verdict in shown_equations
                      if verdict == "holds"]
        for index, (shown, value) in enumerate(figures):
            amount, tolerance = amounts[index], _scaled_tolerance(shown, value)
            approximate = _approximate_tolerance(piece, shown, value, amount)
            if approximate is not None and approximate > tolerance:
                # Judged last, against the figures it can be a rounding of.
                approximates.append((shown, amount, approximate))
                continue
            # A percentage may restate a fraction (0.4156 as 41.56%); an amount
            # never restates a hundred times another (£48,000 is not £4.8m).
            # A published reference value in its own statement's context: ASC
            # 842's 75%/90% bright lines, sampling confidence levels.
            if (is_known(amount, direct_percent if _is_percentage(shown) else direct, tolerance)
                    or (_is_percentage(shown) and is_known(amount, reference_percentages(piece), tolerance))):
                accepted.append(amount)
            elif _absolute(shown, value) is not None:
                # "£4.8m" is a rounded display: accepted as a rounding of a
                # stated or calculated amount, never derived — at that
                # precision a fifth of fabricated amounts matched some sum.
                coarse.append((shown, amount))
            else:
                # The other numbers of the statement (an "US$1.30" rate too): a
                # figure is never its own operand.
                others = amounts[:index] + amounts[index + 1:]
                others += [number for number in _plain_numbers(piece) if number not in amounts and number not in others]
                item = (shown, amount, others, tolerance)
                pending.append(item)
                if piece.lstrip().startswith("|"):
                    row_items.add(id(item))
                # A rounding-only miss ("9.00% × 1.68 × 1.77 = 26.74%") is not
                # evidence either way; the other rules still apply to it.
                verdicts = {verdict for result, _operands, verdict in shown_equations
                            if abs(abs(amount) - abs(result)) <= tolerance}
                if verdicts - {"rounding"}:
                    bound.add(id(item))
                if verdicts == {"fails"}:
                    miscalculated.add(id(item))
    # One step between two figures the user stated together, in one sentence
    # or line: "rose from £20,000 to £22,260" (£2,260 more), "net sales were
    # £1,100,000, cost of goods sold was £660,000" (£440,000), "sales
    # £1,000,000 and profit £120,000" (a 12.0% margin). Any two of a dozen
    # amounts on different lines matched 26% of fabricated figures.
    for group in _fact_groups(facts):
        still = []
        for item in pending:
            if id(item) not in bound and _one_step_from(item[1], item[3], group, group):
                accepted.append(item[1])
            else:
                still.append(item)
        pending = still
    for group in _money_groups(facts):
        still = []
        for item in pending:
            if id(item) not in bound and _average_of_pair(item[1], item[3], group):
                accepted.append(item[1])
            else:
                still.append(item)
        pending = still
    stated_amounts, stated_rates = _stated_rates(facts)
    still = []
    for item in pending:
        if id(item) not in bound and _rate_of_stated_amount(item[1], item[3], stated_amounts, stated_rates):
            accepted.append(item[1])
        else:
            still.append(item)
    pending = still
    for _ in range(6):
        progressed = False
        # A worked equation that holds and whose every operand is verified.
        verified_operands = list(dict.fromkeys(accepted + base))
        for item in list(pending):
            if any(abs(abs(item[1]) - abs(result)) <= item[3] and operands
                   and all(_operand_verified(operand, verified_operands + direct)
                           for operand in operands) for result, operands in equations):
                pending.remove(item)
                accepted.append(item[1])
                progressed = True
            # The same verified result as a percentage: "ROE = 0.08 × 1.6667 ×
            # 2.00 = 0.2667 (or 26.67%)", then "ROE (DuPont): 26.67%". A
            # correct DuPont ROE was removed as unverified (23 Oct 2026).
            elif _is_percentage(item[0]) and any(
                    abs(result) < 10 and abs(abs(item[1]) - abs(result) * 100) <= max(item[3], 0.005)
                    and operands and all(_operand_verified(operand, verified_operands + direct)
                                         for operand in operands) for result, operands in equations):
                pending.remove(item)
                accepted.append(item[1])
                progressed = True
        for item in list(pending):
            shown, amount, others, tolerance = item
            # Only operands already verified: "from £540,000 to £638,400, by
            # £98,400" with £540,000 unverified must not let the two
            # unverified figures vouch for each other.
            verified_here = [value for value in others
                             if is_known(value, accepted + direct + base, _operand_tolerance(value))]
            if id(item) not in bound and base and verified_here and _one_step_from(amount, tolerance, verified_here,
                                                         list(dict.fromkeys(base + accepted))):
                pending.remove(item)
                accepted.append(amount)
                progressed = True
            elif id(item) not in bound and id(item) in row_items and _row_combination(amount, tolerance, verified_here):
                pending.remove(item)
                accepted.append(amount)
                progressed = True
            elif id(item) not in bound and any(
                    abs(abs(amount) - abs(sum(run))) <= tolerance
                    and all(is_known(value, accepted + direct + base, _operand_tolerance(value)) for value in run)
                    for run in column_runs.get(shown, [])):
                pending.remove(item)
                accepted.append(amount)
                progressed = True
        # A change between two figures this answer already verified: "gross
        # profit rose £65,000" (505,000 − 440,000), "+1.56 pp". Differences
        # and percentage changes only, over the answer's own figures.
        verified = list(dict.fromkeys(accepted))
        if len(verified) <= _BASE_MAX:
            for item in list(pending):
                if id(item) not in bound and _change_between(item[1], item[3], verified):
                    pending.remove(item)
                    accepted.append(item[1])
                    progressed = True
        if not progressed or not pending:
            break
    # A high-precision figure one step from two verified figures, whether or
    # not the operand is on the same line: "annual amortisation $42,123.64"
    # (210,618.19 ÷ 5) was removed from a lease answer because the sentence
    # did not repeat $210,618 (2026-10-22). At six or more significant digits
    # a fabricated figure essentially never lands on a pair result
    # (test_figure_reconciliation measures it); shorter figures — "83%",
    # "£42,124" — keep the same-line rule above, where pair search accepted
    # most fabricated values.
    # Built on figures verified this way too ("Year 1 expense $54,760.73" =
    # interest + that amortisation), for a few rounds.
    for _ in range(3):
        progressed = False
        operands = list(dict.fromkeys(base + accepted)) if base else []
        for item in list(pending):
            shown, amount, _others, tolerance = item
            if (id(item) not in bound and operands and _significant_digits(shown) >= _PAIR_SEARCH_MIN_DIGITS
                    and _derived_in_one_step(amount, tolerance, operands)):
                pending.remove(item)
                accepted.append(amount)
                progressed = True
        if not progressed:
            break
    # Two steps when the answer does not show the intermediate: the closing
    # lease liability $173,255.28 (210,618.19 + 12,637.09 − 50,000). Only at
    # seven or more significant digits and over a short list of verified
    # numbers, where the candidates stay few (measured in
    # test_accounting_validation).
    operands = list(dict.fromkeys(base + accepted)) if base else []
    if operands and len(operands) <= _TWO_STEP_MAX_OPERANDS:
        steps = _one_step_values(operands)
        for item in list(pending):
            shown, amount, _others, tolerance = item
            if (id(item) not in bound and _significant_digits(shown) >= _TWO_STEP_MIN_DIGITS
                    and _two_step_from(amount, tolerance, steps, operands)):
                pending.remove(item)
                accepted.append(amount)
    # Decimals are not material figures: those of the answer's equations that
    # hold on verified inputs ("= 0.103218"), and the calculator's.
    known_here = accepted + direct + base
    decimals = accepted + [float(token.replace(",", "")) for token in _NUMBER.findall(_readable(calculations))] + [
        result for result, operands in equations if all(_operand_verified(operand, known_here) for operand in operands)]
    for item in list(pending):
        shown, amount, _others, tolerance = item
        if id(item) not in bound and _is_percentage(shown) and _restates_own_decimal(amount, tolerance, decimals):
            pending.remove(item)
            accepted.append(amount)
    # A share of a like quantity the user gave: "83% of the economic life"
    # with a 5-year lease and a 6-year life. Only between two figures of the
    # same unit, so few pairs exist to match by chance.
    for item in list(pending):
        shown, amount, _others, tolerance = item
        statement = next((piece for piece in _statements(body) if shown in piece), "")
        if id(item) not in bound and _is_percentage(shown) and _share_of_like_quantities(amount, tolerance, statement, facts):
            pending.remove(item)
            accepted.append(amount)
    # An approximate figure may round only a figure that matters here — one of
    # the user's amounts, a calculator result, or a figure this answer already
    # verified — not any number in the evidence: "about £1.3m" matched a
    # rounding of some unrelated number one time in five.
    calculated = [float(token.replace(",", "")) for token in _NUMBER.findall(_readable(calculations))]
    rounding_of = [_amount(shown, value) for shown, value in material_figures(_readable(facts))] + calculated + accepted
    rough = [shown for shown, amount, tolerance in approximates if not is_known(amount, rounding_of, tolerance)
             and not (_is_percentage(shown) and _restates_own_decimal(amount, tolerance, decimals))]
    # An unmarked rounding — "operating profit rose 23%" after "operating
    # profit rose £36,000 (23.23%)" — is the correct rounding, at the precision
    # written, of a figure this answer already verified *for the same thing*:
    # its statement shares the subject's words. Any nearby verified figure
    # would do otherwise ("rose 25%" matched an unrelated 24.9).
    contexts = {}
    for piece in _statements(body):
        words = _subject_words(piece)
        for shown, value in material_figures(piece):
            amount = _amount(shown, value)
            if amount in accepted:
                contexts.setdefault(amount, set()).add(words)

    def rounds_same_thing(shown: str, amount: float) -> bool:
        statement = next((p for p in _statements(body) if shown in p), "")
        words = _subject_words(statement)
        tolerance = _rounding_tolerance(shown, amount)
        return any(abs(abs(amount) - abs(value)) <= tolerance and any(len(words & other) >= 2 for other in sets)
                   for value, sets in contexts.items())

    pending = [item for item in pending if id(item) not in miscalculated
               and (id(item) in bound or not rounds_same_thing(item[0], item[1]))]
    coarse = [shown for shown, amount in coarse if not rounds_same_thing(shown, amount)]
    return list(dict.fromkeys(coarse + rough + [item[0] for item in pending]))


_STOP = frozenset("the and was were is are for from with this that than over into its their our your by of to in on at "
                  "an a as be been has have had per year years total about roughly around approximately".split())


def _subject_words(statement: str) -> frozenset[str]:
    return frozenset(word for word in re.findall(r"[a-z]{3,}", (statement or "").lower()) if word not in _STOP)


def _rounding_tolerance(shown: str, amount: float) -> float:
    number = _NUMBER.search(shown or "")
    if not number:
        return 0.0
    written = number.group(0).replace(",", "")
    decimals = written.split(".")[1] if "." in written else ""
    zeros = 0 if decimals else len(written) - len(written.rstrip("0"))
    half_unit = 0.5 * 10 ** (-len(decimals) if decimals else zeros)
    scale = abs(amount / float(written)) if float(written) else 1.0
    return min(half_unit * scale, abs(amount) * _APPROXIMATE_CAP)


_APPROXIMATE = re.compile(r"(?:\b(?:about|approximately|approx\.?|around|roughly|circa|nearly|almost|some|"
                          r"just\s+(?:over|under|below|above)|close\s+to|in\s+the\s+region\s+of)|~|≈|\bc\.)\s*[+\-]?\s*$",
                          re.I)
_APPROXIMATE_CAP = 0.05


def _approximate_tolerance(piece: str, shown: str, value: float, amount: float) -> float | None:
    """For a figure the text marks as approximate ("about 10%", "roughly
    £1.4m"): it may be any correct rounding at the precision written — within
    half a unit of its last digit — but never more than 5% from the verified
    value. "About 10%" for 10.45% is a rounding; "about £1m" for £1,418,182 is
    materially wrong and still fails. None when the figure is not so marked."""
    at = piece.find(shown)
    if at < 0 or not _APPROXIMATE.search(piece[max(0, at - 24):at]):
        return None
    number = _NUMBER.search(shown)
    if not number:
        return None
    written = number.group(0).replace(",", "")
    decimals = written.split(".")[1] if "." in written else ""
    zeros = 0 if decimals else len(written) - len(written.rstrip("0"))
    half_unit = 0.5 * 10 ** (-len(decimals) if decimals else zeros)
    scale = abs(amount / float(written)) if float(written) else 1.0
    return min(half_unit * scale, abs(amount) * _APPROXIMATE_CAP)


# Constants of a formula's form, not inputs: the 1 of "(1 − t)", the 2 of an
# average, the 100 of a percentage.
_FORMULA_CONSTANTS = (1.0, 2.0, 100.0)


def _operand_verified(operand: float, known: list[float]) -> bool:
    """A verified number, a formula constant, or a verified percentage written
    as a fraction: 0.21 for a stated 21% tax rate ("7.57% × (1 − 0.21)")."""
    return (operand in _FORMULA_CONSTANTS or is_known(operand, known, _operand_tolerance(operand))
            or (0 < abs(operand) < 1 and is_known(operand * 100, known, _operand_tolerance(operand * 100))))


def _operand_tolerance(value: float) -> float:
    return max(abs(value) * 0.0005, 0.006)


def _scaled_tolerance(shown: str, value: float) -> float:
    """tolerance_for, in the units of the figure's absolute amount."""
    absolute = _absolute(shown, value)
    raw = _NUMBER.search(shown or "")
    written = float(raw.group(0).replace(",", "")) if raw else value
    tolerance = tolerance_for(shown, written)
    return tolerance * (absolute / written) if absolute is not None and written else tolerance


_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def statements_with_figures(text: str, figures: list[str]) -> list[str]:
    """Each sentence or table row of `text` that states one of `figures` (as
    unreconciled_figures names them), verbatim, for claim_verification.
    remove_claims. One unverified figure removes the statement that carries
    it, not the whole answer. A scenario line of an illustrative example is
    never one: it was not checked, and "Turnover: £950,000" went with the row
    that failed on £950,000 (24 Oct 2026)."""
    from app.orchestration.derived_output import without_scenarios
    targets = {value for shown, value in material_figures(text) if shown in set(figures)}
    found: list[str] = []
    in_fence = False
    for line in without_scenarios(text).splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not line.strip():
            continue
        pieces = [line.strip()] if line.lstrip().startswith("|") else _SENTENCE_END.split(line.strip())
        for piece in pieces:
            if any(value in targets for _, value in material_figures(piece)):
                found.append(piece.strip())
    return list(dict.fromkeys(found))


def figure_provenance(text: str, receipts: list[dict]) -> list[dict]:
    """For each material figure of `text`: the statement it is in, the figure
    as shown, and the calculation ids whose result (or rounded result) it is,
    at the precision shown. Figures no calculation produced are listed with no
    ids: they were stated or sourced, not calculated."""
    results = []
    for receipt in receipts or []:
        for key in ("result", "rounded"):
            try:
                results.append((float(str(receipt.get(key, "")).replace(",", "")), receipt.get("calculation_id")))
            except ValueError:
                continue
    found = []
    for piece in _statements(text):
        for shown, value in material_figures(piece):
            amount, tolerance = _amount(shown, value), _scaled_tolerance(shown, value)
            ids = list(dict.fromkeys(cid for result, cid in results if cid and abs(abs(result) - abs(amount)) <= tolerance))
            found.append({"statement": piece, "figure": shown, "calculation_ids": ids})
    return found


_CHART_BLOCK = re.compile(r"```chart[ \t]*\n(.*?)\n[ \t]*```", re.DOTALL)
CHART_OMITTED_PREFIX = "Not charted:"


def reconcile_charts(text: str, verified: list[float]) -> tuple[str, list[str]]:
    """Charts that agree with the verified answer. A charted value must be a
    verified figure — a calculator result, a figure the user or a tool or a
    source stated (`verified`), or a figure the answer's own text still shows
    after verification. A category with any other value is dropped from the
    chart and named beneath it, so the chart never shows a hand-computed
    scenario the text withheld (FX benchmark, 2026-10-17). Returns the text and
    the categories dropped."""
    import json
    prose = _CHART_BLOCK.sub(" ", text or "")
    shown = [_amount(s, v) for s, v in material_figures(prose)] + _plain_numbers(prose)
    known = list(verified) + shown
    dropped_all: list[str] = []

    def ok(value) -> bool:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return True                                  # a gap in a series is not a claim
        return is_known(number, known, max(abs(number) * 0.0005, 0.006))

    def fix(match: re.Match) -> str:
        try:
            spec = json.loads(match.group(1))
        except ValueError:
            return match.group(0)
        categories = spec.get("categories") or []
        series = spec.get("series") or []
        bad = {index for item in series for index, value in enumerate(item.get("data") or []) if not ok(value)}
        if not bad:
            return match.group(0)
        names = [str(categories[i]) if i < len(categories) else f"point {i + 1}" for i in sorted(bad)]
        dropped_all.extend(names)
        keep = [i for i in range(len(categories)) if i not in bad]
        note = f"{CHART_OMITTED_PREFIX} {', '.join(names)} — the figure{'s were' if len(names) > 1 else ' was'} not verified."
        if not keep:
            return note
        spec["categories"] = [categories[i] for i in keep]
        for item in series:
            item["data"] = [item["data"][i] for i in keep if i < len(item.get("data") or [])]
        return "```chart\n" + json.dumps(spec, ensure_ascii=False) + "\n```\n" + note

    return _CHART_BLOCK.sub(fix, text or ""), dropped_all


def verified_values(evidence: str, calculations: str) -> list[float]:
    """Stated and calculated values (tier 1 of unreconciled_figures)."""
    return _direct_values(evidence, calculations)


def hand_derived_figures(text: str, evidence: str, calculations: str = "", stated: str | None = None) -> list[str]:
    """Figures of `text` that are neither stated (by the user, a source or a
    tool) nor a calculator result: worked out by hand. The gate may accept
    them as one step from verified figures, yet a release check that requires
    the calculator removes them — the FX scenarios at 1.20 and 1.30 were lost
    that way (2026-10-17). Scale-word roundings ("£1.2m") are not listed."""
    from app.orchestration.derived_output import scenario_text, without_scenarios
    body = without_scenarios(text)
    facts = "\n".join([stated if stated is not None else evidence, scenario_text(text)])
    direct = _direct_values(evidence, calculations) + _line_totals(facts)
    direct_percent = _percent_values(evidence, calculations)
    found = []
    for piece in _statements(body):
        for shown, value in material_figures(piece):
            if _absolute(shown, value) is not None:
                continue
            amount, tolerance = _amount(shown, value), _scaled_tolerance(shown, value)
            if not (is_known(amount, direct_percent if _is_percentage(shown) else direct, tolerance)
                    or (_is_percentage(shown) and is_known(amount, reference_percentages(piece), tolerance))):
                found.append(shown)
    return list(dict.fromkeys(found))
