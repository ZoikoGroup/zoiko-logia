"""Deterministic arithmetic extraction and answer validation.

Only explicitly structured arithmetic is handled here. Ambiguous word problems
are deliberately left to the normal answer path instead of guessing a formula.
"""
from __future__ import annotations

import ast
import re
import uuid
from dataclasses import dataclass
from decimal import Decimal, DivisionByZero, InvalidOperation

from app.orchestration.schemas import CalculationWidget, ChartPoint, WidgetInput
from app.domains.calculations.schemas import (
    CalculationResult, LiveObservation, NumericInput, VerifiedChartSeries, VerifiedChartSpec,
)

_NUMBER = r"(?:[$£€₹]\s*)?([0-9][0-9,]*(?:\.[0-9]+)?)"
_EXPLICIT = re.compile(
    r"(?:calculate|compute|evaluate|what\s+is)\s+([0-9$£€,\.\s()+\-*/x×÷]+)", re.IGNORECASE
)
_EQUATION = re.compile(
    # The repeated alternation is wrapped in an atomic group `(?>...)`: its two
    # branches both match plain digit/operator characters, so on any answer
    # text that never reaches a trailing `= result` (e.g. a chart's raw data
    # array of many numbers, some negative), an unbounded backtracking engine
    # explores every way of re-partitioning that run between the branches —
    # catastrophic (exponential-time) backtracking, confirmed hanging
    # multi-minute+ on a real 20-point GDP series with no `=` in it. Atomic
    # grouping commits to the first (greedy) partition and never backtracks
    # into it, which is a no-op for genuine `expr = result` matches (greedy
    # matching already stops at the right boundary with nothing to backtrack)
    # but turns the no-match case into an immediate, linear-time failure.
    r"(?P<expression>\(*\s*-?[0-9][0-9,.]*(?>(?:\s*[+\-*/×÷]\s*-?[0-9][0-9,.]*|[0-9,.()\s+\-*/×÷])*)\)?)"
    r"\s*=\s*[$£€]?\s*(?P<result>-?[0-9][0-9,]*(?:\.[0-9]+)?)(?P<percent>\s*%)?"
    # The result must be complete: in chained working ("A - B - C = 5,50,000 -
    # 1,50,000 = 4,00,000") "5,50,000" is an intermediate expression, not the
    # value of A - B - C, and was flagged as a mismatch on a correct answer.
    r"(?![\d,]|\.\d|\s*[+\-*/×÷])"
)


@dataclass(frozen=True)
class DeterministicCalculation:
    expression: str
    result: Decimal
    widget: CalculationWidget
    record: CalculationResult
    chart: VerifiedChartSpec
    # Further verified figures derived from the result (an EMI's total
    # payment and interest), given to the model alongside it.
    derived: tuple[tuple[str, str], ...] = ()

    def prompt_context(self) -> str:
        derived = "".join(f"{label}: {value}\n" for label, value in self.derived)
        if derived:
            # The model recomputed an EMI's totals from the unrounded EMI and
            # disagreed with the verified box beside its answer. Told only to
            # "state them", it then dropped the explanation altogether.
            derived += (
                "Explain the calculation as you normally would (formula, inputs, steps), but use "
                "these figures for the results instead of recomputing them, written with the "
                "question's currency symbol.\n"
            )
        return (
            "\n\nDETERMINISTIC CALCULATION (computed by the application; do not alter):\n"
            f"Expression: {self.expression}\nVerified result: {_format_decimal(self.result)}\n"
            f"{derived}"
        )


_MONEY = r"(?:₹|rs\.?|inr|[$£€])?\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(lakhs?|lacs?|crores?|million|m\b)?"
_LOAN_PRINCIPAL = re.compile(rf"\b(?:loan|borrow(?:ed|ing)?|principal|mortgage)\b(?:\s+(?:amount|of|is))*\s*[:=]?\s*{_MONEY}", re.I)
_PRINCIPAL_THEN_LOAN = re.compile(rf"{_MONEY}\s+(?:home\s+|car\s+|personal\s+)?(?:loan|mortgage)\b", re.I)
_ANNUAL_RATE = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*%", re.I)
_TERM = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*(years?|yrs?|months?)\b", re.I)
# "18% GST on ₹50,000", "20% of 5,000": a percentage of a stated amount.
_PERCENT_OF = re.compile(
    rf"([0-9]+(?:\.[0-9]+)?)\s*%\s*(gst|vat|tds|tax|discount|commission|interest|tip)?\s*(?:on|of)\s+{_MONEY}",
    re.I,
)
_SCALE = {"lakh": Decimal(100_000), "lac": Decimal(100_000), "crore": Decimal(10_000_000),
          "million": Decimal(1_000_000), "m": Decimal(1_000_000)}


def _loan_terms(query: str) -> tuple[Decimal, Decimal, int] | None:
    """(principal, annual rate %, months) for a loan-repayment question."""
    if not re.search(r"\b(?:emi|monthly (?:payment|instal+ment|repayment)|instal+ment|amortis|amortiz)", query, re.I):
        return None
    principal_match = _LOAN_PRINCIPAL.search(query) or _PRINCIPAL_THEN_LOAN.search(query)
    rate_match = _ANNUAL_RATE.search(query)
    term_match = _TERM.search(query)
    if not (principal_match and rate_match and term_match):
        return None
    principal = Decimal(principal_match.group(1).replace(",", ""))
    scale = (principal_match.group(2) or "").lower().rstrip("s")
    principal *= _SCALE.get(scale, Decimal(1))
    months = Decimal(term_match.group(1)) * (1 if term_match.group(2).lower().startswith("m") else 12)
    if principal <= 0 or months <= 0 or months != months.to_integral_value() or months > 1200:
        return None
    return principal, Decimal(rate_match.group(1)), int(months)


# Powers make EMI, compound growth, annuity and discount factors computable
# in one exact step — without them the model approximated (1 + r)^180 as
# "≈ 3.70" and put a ₹17/month error into an EMI. Bounded so an expression
# can never become an expensive computation.
_MAX_EXPONENT = Decimal(1200)
_MAX_POWER_BASE = Decimal(10) ** 6


def _evaluate(expression: str) -> Decimal:
    cleaned = (expression.replace(",", "").replace("×", "*").replace("÷", "/").replace("^", "**"))
    cleaned = re.sub(r"(?<=\d)\s*[xX]\s*(?=\d)", "*", cleaned).strip()
    if len(cleaned) > 240 or not re.fullmatch(r"[0-9.()\s+\-*/]+", cleaned):
        raise ValueError("unsupported arithmetic expression")
    tree = ast.parse(cleaned, mode="eval")

    def visit(node: ast.AST) -> Decimal:
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            # AST constants containing decimals have already been converted to
            # binary numbers by Python. Read the whitelisted source literal so
            # dependent calculator results retain their Decimal precision.
            return Decimal(ast.get_source_segment(cleaned, node))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = visit(node.operand)
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            return left / right
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            base, exponent = visit(node.left), visit(node.right)
            if abs(exponent) > _MAX_EXPONENT or abs(base) > _MAX_POWER_BASE:
                raise ValueError("power out of range")
            if exponent != exponent.to_integral_value() and base <= 0:
                # A fractional power of a non-positive number has no real value.
                raise ValueError("invalid power")
            return base ** exponent
        raise ValueError("unsupported arithmetic expression")

    try:
        return visit(tree)
    except (DivisionByZero, InvalidOperation, ZeroDivisionError) as exc:
        raise ValueError("invalid arithmetic expression") from exc


def evaluate_expression(expression: str) -> Decimal:
    """Public entry point for the calculate tool — the same AST-whitelisted
    evaluator (numbers, + - * /, bounded powers, parentheses; no names or
    calls) the question-parsing path uses. Raises ValueError on anything else."""
    return _evaluate(expression)


def _format_decimal(value: Decimal) -> str:
    rendered = format(value.quantize(Decimal("0.01")), "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


# "sales" alone means revenue, but not inside "cost of sales" — otherwise
# "Cost of sales is 160,000 and revenue is 250,000" read 160,000 as revenue.
_REVENUE_LABEL = r"revenue|(?<!of )sales"


def _number_for_label(query: str, labels: str) -> Decimal | None:
    match = re.search(rf"(?:{labels})(?:\s+(?:is|are|of))?\s*[:=]?\s*{_NUMBER}", query, re.IGNORECASE)
    return Decimal(match.group(1).replace(",", "")) if match else None


_FINANCE_FORMULA = re.compile(
    r"\b(?:compound(?:ed|ing)?|future value|present value|emi|cagr|simple interest|annuity|npv|irr|"
    r"(?:net |gross |operating )?(?:profit )?margin|break[- ]?even|payback|depreciation|"
    r"monthly (?:payment|instal+ment)|markup|mark-up|percentage (?:change|increase|decrease)|"
    # Checking the user's own figures: "Subtotal ₹10,000, tax ₹1,800, total
    # ₹11,500 — check the arithmetic" was treated as a tax question, sent
    # to web search and answered "the sources provided do not state this".
    r"(?:check|verify|recheck|validate)\s+(?:the\s+|my\s+|this\s+)?(?:arithmetic|maths?|math|totals?|sums?|calculations?)|"
    r"reconcile|add(?:s)?\s+up)\b",
    re.I,
)
# Something the question expects to be LOOKED UP, not computed from its own
# figures: a current or statutory rate, a threshold, a provision.
_NEEDS_LOOKUP = re.compile(
    # "current" alone, not "current assets/liabilities/ratio": a ratio question
    # was taken for a rate lookup, so its calculations were refused as uncited.
    # Time words ("current", "today", "latest") are decided by
    # live_data_requested, not by this list.
    r"\b(?:repo|rbi|federal reserve|bank rate|"
    r"tax (?:rate|slab|bracket)s?|slabs?|thresholds?|limits?|gst rate|vat rate|according to|as per|"
    r"under section|act|rules?|standard|ifrs|ind as|gaap)\b",
    re.I,
)


_ACCOUNTING_CURRENT = re.compile(
    r"\bcurrent\s+(?:and\s+quick\s+)?(?:assets?|liabilit(?:y|ies)|ratios?|account|portion)\b"
    # The user's own model, not today's rate: "Our current annual revenue is
    # £2,400,000 … calculate current contribution" was taken for a lookup, so
    # the forecast's formulas needed citations and the answer was refused.
    r"|\bcurrent\s+(?:annual\s+|monthly\s+|quarterly\s+)?(?:contribution|(?:operating\s+|net\s+|gross\s+)?profit|"
    r"(?:contribution\s+)?margin|break[- ]?even|(?:fixed|variable|operating)\s+(?:operating\s+)?costs?|cost base)\b"
    # "the current year-end spot rate is $1.35" (22 Oct 2026).
    # "current TTM (Trailing Twelve Months) EBITDA is $2,000,000".
    r"|\bcurrent\b[^.\n]{0,80}?\b(?:is|are|was|were|of|at)\s+(?:[£$€₹]\s?|(?:rs\.?|inr|usd|gbp|eur)\s?)?\d"
    # The income-tax split, not today's rate: "provision for income taxes
    # (current vs. deferred expense)" was read as a current-rate lookup.
    r"|\bcurrent\s+(?:vs\.?|versus|and|or|/)\s+deferred\b"
    # A price the user gives: "currently trading at $950 per bond".
    r"|\bcurrently\s+(?:trading|priced|quoted|valued|selling|listed)\s+at\s+(?:[£$€₹]\s?|(?:rs\.?|inr|usd|gbp|eur)\s?)?\d"
    r"|\bcurrent\s+(?:income\s+)?tax\s+(?:expense|payable|liabilit(?:y|ies)|charge|provision)\b",
    re.I,
)


# A threshold or limit the user gives is a fact of the scenario, not a
# statutory limit to look up: "just below a $3,000 manager approval
# threshold" sent a Benford question to strict sourcing (22 Oct 2026).
_SUPPLIED_LIMIT = re.compile(
    r"(?:[£$€₹]|\b(?:rs\.?|inr|usd|gbp|eur)\s?)\s?\d[\d,]*(?:\.\d+)?\s+(?:[a-z-]+\s+){0,3}(?:thresholds?|limits?)\b"
    r"|\b(?:thresholds?|limits?)\s+(?:of|at|is)\s+(?:[£$€₹]|\b(?:rs\.?|inr|usd|gbp|eur)\s?)\s?\d"
    # "The total materiality threshold for the entire financial audit is set at
    # $750,000" sent an AS 2501 question to strict sourcing (23 Oct 2026).
    r"|\b(?:materiality|tolerable|performance|approval|authori[sz]ation|clearly\s+trivial)\s+(?:thresholds?|limits?)\b"
    r"[^.\n]{0,60}?\b(?:is|was|of|at|=)\s+(?:set\s+at\s+)?(?:[£$€₹]|\b(?:rs\.?|inr|usd|gbp|eur)\s?)\s?\d", re.I)
# "The corporate tax rate is 21%", "a 25% tax rate": a rate the question
# supplies, not one to look up. A diluted-EPS question planned a live search
# for it (23 Oct 2026).
_SUPPLIED_TAX_RATE = re.compile(
    r"\b(?:(?:corporate|income|effective|marginal|statutory|applicable)\s+)?tax\s+rates?\s+(?:is|was|of|at|=|:)\s*"
    r"\d+(?:\.\d+)?\s?%"
    r"|\b\d+(?:\.\d+)?\s?%\s+(?:(?:corporate|income|effective|marginal|statutory)\s+)?tax\s+rates?\b", re.I)
# A request not to check or retrieve something: "Use the supplied rate without
# checking the current repo rate", "Do not retrieve a live rate" (23 Oct 2026).
# The clause is an instruction about tools, not a request for the fact.
NEGATED_LOOKUP = re.compile(
    r"\b(?:without|do\s+not|don'?t|never|no\s+need\s+to|need\s+not)\s+(?:\w+\s+){0,2}?"
    r"(?:check\w*|verif\w*|confirm\w*|validat\w*|look\w*\s+up|retriev\w*|fetch\w*|search\w*|use)\b[^.?!\n]*", re.I)


# Asking whether a rate is right is a lookup, whatever figure the question
# quotes: "Is the current repo rate at 6.5%?" and "Is the current exchange
# rate of 83 INR per USD correct?" read as the user's own figures (review R1,
# 22 Oct 2026). Giving a rate to work with ("the current spot rate is $1.35")
# is not a question about it.
_VERIFY_OPENER = re.compile(
    r"^\W*(?:is|are|was|were|has|have|does|do|did|can\s+you\s+confirm|please\s+confirm|confirm|check|verify|validate)\b",
    re.I)
_VERIFY_ASK = re.compile(
    r"\b(?:correct|accurate|right|valid|true|up[- ]to[- ]date|in\s+force|still\s+appl(?:y|ies)|still\s+(?:the\s+)?(?:same|current))\b",
    re.I)
# A verifying verb anywhere, with the time word after it: "Could you verify
# whether the current repo rate is 6.5%?", "Kindly confirm the current GST
# rate …", "I need to know whether the current SOFR rate is still 5.3%". The
# order keeps "Using the current repo rate of 6.5%, compute … and check that
# the interest is correct" a calculation (final review, 22 Oct 2026).
_VERIFY_PHRASE = re.compile(
    # Not a bare "know" or "tell me": "I know the current rate is 7%" and
    # "tell me the interest using …" supply a rate (v4 review).
    r"\b(?:verify|confirm|check|validate|find\s+out|know\s+(?:whether|if)"
    r"|tell\s+me\s+(?:whether|if))\b"
    r"(?:\s+(?:whether|if|that))?[^.?!\n]{0,40}?"
    r"\b(?:current(?:ly)?|latest|today'?s?|prevailing|present|still|now)\b", re.I)
_TIME_WORD = re.compile(r"\b(?:current(?:ly)?|latest|today'?s?|now|still|prevailing|present|this\s+year'?s?)\b", re.I)
_FACT_WORD = re.compile(
    r"\b(?:rates?|prices?|thresholds?|limits?|wages?|yields?|slabs?|ceilings?|caps?|exemptions?|allowances?|"
    r"repo|sofr|libor|euribor|base\s+rate|fx|exchange|gst|vat|tds)\b", re.I)
# The sentence asks about a calculation on the rate, not whether the rate is
# right: "does the current exchange rate of $1.12 create a gain", "is the
# current price of $45 above book value", "was … 8% applied correctly",
# "compute interest" (v4 review). Such a sentence is never a verification.
_CALCULATION_ASK = re.compile(
    r"\b(?:comput\w*|calculat\w*|appl(?:y|ies|ied|ying)|creat\w*|translat\w*|above|below|compar\w*|"
    r"determin\w*|estimat\w*|us(?:e|ed|es|ing)|based\s+on|exceed\w*|record\w*|recogni[sz]\w*|measur\w*|"
    r"impact|effect|gain|loss|interest\s+(?:on|for|of)\b)\b", re.I)
# A yes/no question about a rate with its figure, no time word needed: "Is the
# repo rate 6.5%?", "Repo rate still 6.5%?", "The repo rate is 6.5% now,
# isn't it?". Not a wh-question ("What is the cost if the rate is 21%?").
_YES_NO = re.compile(r"^\W*(?:is|are|was|were|has|have|does|do|did)\b", re.I)
_WH_OR_TASK = re.compile(r"^\W*(?:what|how|which|why|when|where|who|calculate|compute|determine|find|prepare)\b",
                         re.I)
# "…, isn't it?", "…, right?", and a bare "Repo rate still 6.5%?".
_TAG_QUESTION = re.compile(r",\s*(?:isn'?t\s+it|is\s+it\s+not|right|correct|yes)\s*\?\s*$", re.I)
_ELLIPTICAL = re.compile(r"^\W*(?:the\s+)?[\w/ ]{0,30}?\b(?:rate|price|threshold|limit|wage|yield)s?\s+(?:still|now)\b",
                         re.I)
_STATED_FIGURE = re.compile(r"\d+(?:\.\d+)?\s?%|[£$€₹¥]\s?\d|\b\d+(?:\.\d+)?\b")


def verifies_current_fact(text: str) -> bool:
    """A sentence asks whether a current rate, price, threshold or limit is
    right, rather than supplying one to calculate with."""
    for sentence in re.split(r"(?<=[.?!])\s+|\n", NEGATED_LOOKUP.sub(" ", text or "")):
        if not _FACT_WORD.search(sentence) or _CALCULATION_ASK.search(sentence):
            continue
        asks = (_VERIFY_OPENER.match(sentence) or _VERIFY_PHRASE.search(sentence)
                or (sentence.rstrip().endswith("?") and _VERIFY_ASK.search(sentence)))
        if asks and _TIME_WORD.search(sentence):
            return True
        question = sentence.rstrip().endswith("?") and not _WH_OR_TASK.match(sentence)
        if question and (_YES_NO.match(sentence) or _TAG_QUESTION.search(sentence) or _ELLIPTICAL.match(sentence)) \
                and _STATED_FIGURE.search(sentence):
            return True
    return False


_PERIOD = r"(?:financial\s+|fiscal\s+|accounting\s+|reporting\s+)?(?:year|period|quarter|month)"
_OWN_PRIOR_PERIOD = re.compile(rf"\b(?:previous|prior|last|preceding|comparative)\s+{_PERIOD}\b", re.I)
# The question's own figures for those periods: "£1,250,000", "₹8,00,000", "$1.2m".
_STATED_AMOUNT = re.compile(r"(?:[£$€₹]|\b(?:rs\.?|inr|usd|gbp|eur)\s?)\s?\d[\d,]*(?:\.\d+)?", re.I)
_CURRENT_PERIOD = re.compile(
    rf"\bcurrent(?:\s+(?:and|or|vs\.?|versus|/)\s+(?:previous|prior|last|preceding))?[\s-]+{_PERIOD}'?s?\b", re.I)


# One decision for every "does this question need live data?" check
# (needs_lookup, the planner, the FX latest-rate gate). Three detectors each
# kept their own exception lists, so every new phrasing broke one of them:
# "currently pays an annual dividend of $1.20", "the value per share today
# (Year 0)", "the current spot rate is 5.00 BRL per $1" (22-23 Oct 2026).
_TIME_WORDS = re.compile(
    r"\b(?:current(?:ly)?|latest|today'?s?|prevailing|live|this\s+(?:week|month|year)'?s?|at\s+present|present[- ]day)\b"
    # "now" and "present" are also ordinary words ("the team must now
    # perform", "present the following details"): only beside a figure word.
    r"|\b(?:rates?|prices?|quotes?|yields?|values?|levels?)\s+(?:right\s+)?now\b|\bpresent\s+(?:rates?|prices?|market)\b",
    re.I)
_FIGURE = r"(?:[£$€₹¥]\s?|(?:rs\.?|inr|usd|gbp|eur)\s?)?\d"
_LINKING = r"\b(?:is|are|was|were|of|at|=|pays?|paying|trades?|trading|earns?|stands?|costs?|totals?|equals?)\s+"
_LOOKUP_NOUN = r"\b(?:rates?|prices?|quotes?|yields?|index|cpi|inflation|thresholds?|limits?|levels?)\b"
_CLAUSE = r"(?:(?!\b(?:and|if|but|while|whereas|then|or)\b)[^.;?!\n])"
# The time word's own clause gives the figure: "currently pays … $1.20",
# "the current spot rate is 5.00", "this year: rent £36,000", "this month I
# expect £6,000". A rate or price word before the figure needs a linking verb
# ("the current repo rate on ₹10 lakh" asks for the rate); a conjunction or
# condition starts another clause ("today and its P/E if EPS is 6.1").
# A period ("52-week high", "5 years") is not a value, and a comparison
# ("trading above $100") is a condition to check, not a supplied figure.
_VALUE = rf"{_FIGURE}(?![\d,.]*\s*-?\s*(?:weeks?|days?|months?|years?|quarters?|hours?)\b)"
_COMPARISON = r"\b(?:above|below|over|under|exceed\w*|more\s+than|less\s+than|higher|lower)\b"
_SUPPLIED_AFTER = re.compile(
    rf"^{_CLAUSE}{{0,80}}?{_LINKING}(?:about\s+|approximately\s+)?{_VALUE}"
    rf"|^(?:(?!{_LOOKUP_NOUN}|{_COMPARISON}){_CLAUSE}){{0,60}}?{_VALUE}", re.I)
# What the question asks to compute, not an input to fetch: "the intrinsic
# current value per share today (Year 0)", "present value".
_COMPUTED_TARGET = re.compile(
    r"^\s*(?:\(?year\s*0\)?|value\b|worth\b|(?:intrinsic|fair|present|net\s+present)\s+value\b)", re.I)
_VALUATION_TASK = re.compile(r"\b(?:discount\w*|valu(?:e|ation)|intrinsic|present\s+value|year\s*0)\b", re.I)


def supplied_fact_kinds(text: str) -> set[str]:
    """Kinds of figure ("price", "rate") the text gives a current value for:
    "the current spot rate is 5.00" supplies a rate."""
    supplied: set[str] = set()
    for sentence in re.split(r"(?<=[.?!])\s+|\n", NEGATED_LOOKUP.sub(" ", text or "")):
        for match in _TIME_WORDS.finditer(sentence):
            after = sentence[match.end():]
            if _SUPPLIED_AFTER.search(after):
                supplied.update(_fact_nouns(re.split(r"\d", after, maxsplit=1)[0]))
    return supplied


def live_data_requested(text: str, context: str | None = None) -> bool:
    """A time word asks for live data only when it qualifies something whose
    value the question does not give and that is not the result being
    computed; "without checking …" and "do not retrieve …" never do."""
    text = NEGATED_LOOKUP.sub(" ", text or "")
    # Facts the question itself gives a current value for: "The current
    # market price of the stock is $48" supplies a price, so a later "based
    # on the current underlying stock price" means that $48, not a live
    # quote (the convertible question planned a market lookup, 23 Oct 2026).
    # `context` is the full question when `text` has had phrases removed.
    supplied = supplied_fact_kinds(context if context is not None else text)
    for sentence in re.split(r"(?<=[.?!])\s+|\n", text):
        for match in _TIME_WORDS.finditer(sentence):
            after = sentence[match.end():]
            if _SUPPLIED_AFTER.search(after):
                continue
            if _VALUATION_TASK.search(sentence) and (
                    _COMPUTED_TARGET.search(after) or re.search(r"\(\s*year\s*0\s*\)", after[:30], re.I)):
                continue
            # The phrase the time word qualifies, up to the clause's end.
            named = _fact_nouns(re.split(r"[,;:()]|\b(?:and|or|if|but|then)\b", after, maxsplit=1)[0][:60])
            if named and named <= supplied:
                continue
            return True
    return False


def _fact_nouns(phrase: str) -> set[str]:
    """The kinds of figure a phrase names, singular: {"price"}, {"rate"}."""
    return {re.sub(r"s$", "", word.lower()) for word in re.findall(
        r"\b(?:rates?|prices?|quotes?|yields?|thresholds?|limits?|levels?|index)\b", phrase or "", re.I)}


def needs_lookup(query: str) -> bool:
    """The question asks for something that must be looked up — a current or
    statutory rate, slab, threshold or provision — rather than computed."""
    query = NEGATED_LOOKUP.sub(" ", query or "")
    if verifies_current_fact(query):
        return True
    # Accounting uses of "current" are labels on the user's own figures, not
    # a request for today's rate ("Current and quick ratio?").
    text = _SUPPLIED_TAX_RATE.sub(" ", _SUPPLIED_LIMIT.sub(" ", _ACCOUNTING_CURRENT.sub(" ", query or "")))
    if _OWN_PRIOR_PERIOD.search(text) and len(_STATED_AMOUNT.findall(text)) >= 2:
        # "Calculate … for the current year … and for the previous financial
        # year using the figures provided" compares the user's own periods
        # (qry-f7c7ad8f72ff): read as a lookup, every line of the analysis
        # needed a citation and the answer was "no factual answer verified".
        text = _CURRENT_PERIOD.sub(" ", text)
    requested_fx = re.search(
        r'\b(?:find|fetch|get|look\s+up|retrieve)\b[^.?]*\b(?:exchange|fx|conversion|currency)\s+rates?\b',
        text, re.I,
    )
    return bool(_NEEDS_LOOKUP.search(text) or requested_fx or live_data_requested(text, context=query))


def is_self_contained_calculation(query: str, history=()) -> bool:
    """Every input is in the question and nothing needs looking up — "invest
    $10,000 at 8% compounded annually for 10 years". Web search adds nothing
    to such a question: it returned unrelated World Bank reports that were
    then cited as the answer's sources."""
    if needs_lookup(query):
        return False
    # history: a follow-up ("if cost of sales rose 10%…") whose other inputs
    # are earlier in the conversation is just as self-contained.
    if build_calculation(query, history) is not None:
        return True
    # "Revenue is zero and expenses are ₹15,000" states two figures; with
    # "zero" uncounted it went to web search and cited unrelated reports.
    numbers = re.findall(r"\d[\d,]*(?:\.\d+)?|\b(?:zero|nil)\b", query, re.I)
    if len(numbers) >= 2 and _FINANCE_FORMULA.search(query):
        return True
    # A chart of figures the message supplies ("Waterfall chart: revenue 500,
    # cost of sales −300, … tax −20") is built from them. Read as a tax
    # question, it ran a web search, required citations for the user's own
    # numbers and answered "the sources provided do not state this".
    from app.orchestration.response_planner import detect_explicit_visual_request
    return len(numbers) >= 3 and detect_explicit_visual_request(query)


def build_calculation(query: str, history=()) -> DeterministicCalculation | None:
    from app.orchestration.calculations.engine import asks_several_questions
    if asks_several_questions(query):
        return None
    # The single-value widget cannot represent multiple periods or net sales
    # adjustments. Matching the first "sales" and "COGS" here produced a
    # misleading 43.20% alongside an otherwise unrelated financial report.
    if re.search(r'\b(?:gross sales|sales returns)\b', query, re.I) or (
        re.search(r'\b(?:current|this)[ -]year\b', query, re.I)
        and re.search(r'\b(?:previous|prior|last)[ -]year\b', query, re.I)
    ):
        return None
    expression: str | None = None
    formula_name = "Arithmetic calculation"
    inputs: list[WidgetInput] = []
    operation = "arithmetic"
    output_unit = "number"

    revenue = _number_for_label(query, _REVENUE_LABEL)
    sales_cost = _number_for_label(query, r"cost of sales|cost of goods sold|cogs")
    increase = re.search(r"cost of sales\s+increased?\s+by\s+(\d+(?:\.\d+)?)\s*%", query, re.I)
    if increase and re.search(r"revenue\s+(?:stayed|stays|remains?)\s+unchanged", query, re.I):
        for message in reversed(history):
            if message.role != "user":
                continue
            previous_revenue = _number_for_label(message.content, _REVENUE_LABEL)
            previous_cost = _number_for_label(message.content, r"cost of sales|cost of goods sold|cogs")
            if previous_revenue is not None and previous_cost is not None:
                revenue = revenue if revenue is not None else previous_revenue
                sales_cost = sales_cost if sales_cost is not None else previous_cost
                break
        if sales_cost is not None:
            sales_cost *= 1 + Decimal(increase.group(1)) / 100

    cost = _number_for_label(query, r"cost|purchase\s+price")
    residual = _number_for_label(query, r"residual(?:\s+value)?|salvage(?:\s+value)?")
    life = _number_for_label(query, r"useful\s+life|life")
    change = re.search(rf"\bfrom\s+{_NUMBER}\s+to\s+{_NUMBER}", query, re.I)
    actual = _number_for_label(query, r"actual")
    budget = _number_for_label(query, r"budget")
    loan = _loan_terms(query)
    derived: tuple[tuple[str, str], ...] = ()
    if loan is not None:
        principal, annual_rate, months = loan
        if annual_rate == 0:
            expression = f"{principal} / {months}"
        else:
            r = f"({annual_rate} / 12 / 100)"
            expression = f"{principal} * {r} * (1 + {r}) ** {months} / ((1 + {r}) ** {months} - 1)"
        formula_name = "Loan EMI"
        operation = "loan_emi"
        output_unit = "currency/month"
        inputs = [
            _widget_input("principal", "Loan amount", principal, "currency"),
            _widget_input("annual_rate", "Annual interest rate", annual_rate, "percent"),
            _widget_input("months", "Term", Decimal(months), "months"),
        ]
    elif (percent_of := _PERCENT_OF.search(query)) is not None:
        rate, label = Decimal(percent_of.group(1)), (percent_of.group(2) or "").upper()
        amount = Decimal(percent_of.group(3).replace(",", ""))
        amount *= _SCALE.get((percent_of.group(4) or "").lower().rstrip("s"), Decimal(1))
        expression = f"{amount} * {rate} / 100"
        formula_name = f"{label} amount" if label else "Percentage of amount"
        operation = "percentage"
        output_unit = "currency"
        inputs = [
            _widget_input("amount", "Amount", amount, "currency"),
            _widget_input("rate", f"{label} rate" if label else "Rate", rate, "percent"),
        ]
    elif revenue is not None and sales_cost is not None and re.search(r"\b(?:gross profit|margin)\b", query, re.I):
        if revenue == 0:
            return None
        margin = bool(re.search(r"\bmargin\b", query, re.I))
        expression = f"({revenue} - {sales_cost}) / {revenue} * 100" if margin else f"{revenue} - {sales_cost}"
        formula_name = "Gross profit margin" if margin else "Gross profit"
        operation = "percentage" if margin else "difference"
        output_unit = "percent" if margin else "currency"
        inputs = [_widget_input("revenue", "Revenue", revenue, "currency"),
                  _widget_input("cost_of_sales", "Cost of sales", sales_cost, "currency")]
    elif change and re.search(r"percent|percentage|change|growth", query, re.I):
        old = Decimal(change.group(1).replace(",", ""))
        new = Decimal(change.group(2).replace(",", ""))
        if old == 0:
            return None
        expression = f"({new} - {old}) / {old} * 100"
        formula_name = "Percentage change"
        operation = "percentage_change"
        inputs = [
            _widget_input("prior", "Prior value", old, "number"),
            _widget_input("current", "Current value", new, "number"),
        ]
    elif actual is not None and budget is not None and re.search(r"variance", query, re.I):
        expression = f"{actual} - {budget}"
        formula_name = "Variance"
        operation = "variance"
        inputs = [
            _widget_input("actual", "Actual", actual, "currency"),
            _widget_input("budget", "Budget", budget, "currency"),
        ]
    elif (cost is not None and residual is not None and life is not None and re.search(r"depreciat", query, re.I)
          and cost > residual and life > 0):
        expression = f"({cost} - {residual}) / {life}"
        formula_name = "Straight-line depreciation"
        operation = "straight_line_depreciation"
        inputs = [
            _widget_input("cost", "Cost", cost, "currency"),
            _widget_input("residual", "Residual value", residual, "currency"),
            _widget_input("life", "Useful life", life, "years"),
        ]
    else:
        match = _EXPLICIT.search(query)
        # An expression needs an operator between operands: "What is 18% GST
        # on ₹50,000?" otherwise became the "calculation" 18 = 18, shown in a
        # Verified calculation box beside the real answer (₹9,000).
        if match and re.search(r"[\d)]\s*[+\-*/x×÷]\s*[\d(]", match.group(1)):
            expression = match.group(1).strip().rstrip("?. ")
    if not expression:
        return None
    try:
        result = _evaluate(expression)
    except (SyntaxError, ValueError):
        return None

    rendered = _format_decimal(result)
    if loan is not None:
        # Totals from the EMI as shown (two decimals), so "EMI × months"
        # in the answer's working re-checks exactly.
        emi = result.quantize(Decimal("0.01"))
        total = emi * loan[2]
        # Money keeps both decimals: _format_decimal shows 44986.30 as
        # "44986.3", which the model then copied into the answer.
        def money(value: Decimal) -> str:
            return format(value.quantize(Decimal("0.01")), "f")

        derived = (
            ("EMI (rounded to 2 decimals)", money(emi)),
            (f"Total paid over {loan[2]} months ({money(emi)} * {loan[2]})", money(total)),
            (f"Total interest ({money(total)} - {money(loan[0])})", money(total - loan[0])),
        )
    calculation_id = f"calc_{uuid.uuid4().hex}"
    widget = CalculationWidget(
        formula_id="straight_line_depreciation" if formula_name.startswith("Straight") else "arithmetic",
        formula_name=formula_name,
        formula_display=f"{expression} = {rendered}",
        methodology_reference="Deterministic Decimal arithmetic",
        inputs=inputs,
        output_label="Annual depreciation" if formula_name.startswith("Straight") else "Result",
        output_value=rendered,
        output_unit="currency/year" if formula_name.startswith("Straight") else output_unit,
        chart_type="kpi",
        chart_label=formula_name,
        chart_x_label="",
        chart_y_label="",
        chart_points=[ChartPoint(x="result", y=rendered)],
        calculation_id=calculation_id,
    )
    numeric_inputs = [
        NumericInput(name=item.name, value=item.value, unit=item.unit)
        for item in inputs
    ] or [
        NumericInput(name=f"operand_{index}", value=value.replace(",", ""), unit="number")
        for index, value in enumerate(re.findall(r"(?<![A-Za-z])\d[\d,]*(?:\.\d+)?", expression), start=1)
    ]
    record = CalculationResult(
        calculation_id=calculation_id,
        operation=operation,
        rule_version=f"{operation}:v1",
        inputs=numeric_inputs,
        output_value=rendered,
        output_unit=widget.output_unit,
    )
    chart = VerifiedChartSpec(
        chart_id=f"chart_{uuid.uuid4().hex}",
        type="kpi",
        title=formula_name,
        categories=[widget.output_label],
        series=[VerifiedChartSeries(
            name=widget.output_label,
            values=[rendered],
            unit=widget.output_unit,
            source_ids=[calculation_id],
        )],
        calculation_id=calculation_id,
    )
    return DeterministicCalculation(
        expression=expression, result=result, widget=widget, record=record, chart=chart, derived=derived,
    )


def _widget_input(name: str, label: str, value: Decimal, unit: str) -> WidgetInput:
    magnitude = abs(value)
    return WidgetInput(
        name=name, label=label, value=_format_decimal(value), unit=unit,
        min="0", max=_format_decimal(max(magnitude * 2, Decimal("1"))),
        step="1" if value == value.to_integral() else "0.01",
    )


def _normalise_arithmetic(text: str) -> str:
    """Make money-formatted working checkable. "£74,000 ÷ £250,000 × 100 =
    29.6%" was read as "250,000 × 100" (the £ split the expression) and a
    correct answer was escalated as a calculation mismatch."""
    # LaTeX number/operator formatting the model uses inside formulas:
    # "50{,}000 \\times 0.06" was read as "000 * 0.06" and a correct
    # simple-interest answer was escalated.
    text = text.replace("{,}", ",").replace("\\%", "%").replace("\\cdot", "*")
    # "\\frac{18,00,000}{1,00,00,000}\\times 100 = 1.8\\%" was never read, so a
    # ROCE answer ten times too small went out unchecked.
    text = re.sub(r"\\(?:text|mathrm|mathbf|textbf|boldsymbol)\s*\{([^{}]*)\}", r"\1", text)
    previous = None
    while previous != text:
        previous = text
        text = re.sub(r"\\[dt]?frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}", r"(\1)/(\2)", text)
    text = re.sub(r"\\(?:left|right)\s*([()\[\]])", r"\1", text)
    text = re.sub(r"\\[,;:! ]", " ", text)                       # LaTeX spacing commands
    text = re.sub(r"(?:[£$€₹]|\bRs\.?|\bINR|\bUSD|\bGBP|\bEUR)\s*(?=\d)", "", text)
    text = re.sub(r"[\u2010-\u2015\u2212]", "-", text)          # unicode dashes / minus sign
    # "10% ×" -> (10/100); also inside brackets and sums, so "\\frac{63.75\\%}{3}
    # = 21.75\\%" (really 21.25%) is checked instead of skipped.
    text = re.sub(r"(\d(?:[\d,]*\d)?(?:\.\d+)?)\s*%(?=\s*[*×/÷)+\-])", r"(\1/100)", text)
    # "× 12% =" as well: "₹40,000 × 12% = ₹2,400" (really ₹4,800) was never
    # checked, because the % sat between the expression and its "=".
    return re.sub(r"([*×/÷]\s*)(\d(?:[\d,]*\d)?(?:\.\d+)?)\s*%", r"\1(\2/100)", text)


_DEBIT_HEADER = re.compile(r"\b(dr|debit)\b", re.I)
_CREDIT_HEADER = re.compile(r"\b(cr|credit)\b", re.I)
# Thousands grouped by commas or by spaces (ordinary, no-break, narrow, thin):
# "133 650.60" in a journal table was read as 133 (28 Oct 2026).
_AMOUNT = re.compile(r"-?\d{1,3}(?:[    ]\d{3})+(?:\.\d+)?(?!\d)|-?\d[\d,]*(?:\.\d+)?")


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _amount(cell: str) -> Decimal | None:
    match = _AMOUNT.search(cell.replace("₹", "").replace("Rs.", ""))
    try:
        return Decimal(re.sub(r"[,    ]", "", match.group())) if match else None
    except InvalidOperation:
        return None


_SAYS_UNBALANCED = re.compile(
    r"\b(?:does\s+not|doesn['’]t|do\s+not|don['’]t|did\s+not|fails?\s+to|will\s+not|won['’]t)\s+balance\b"
    r"|\b(?:un|not\s+|out\s+of\s+)balanced?\b|\bimbalance\b", re.I)


def _journal_balance_failures(answer_text: str) -> list[str]:
    """A journal table whose debit and credit columns do not total the same.
    "Share Capital Dr 10,000 / Calls in Arrears Dr 3,000 / Share Forfeiture
    Cr 7,000" (13,000 against 7,000) went out as an answer.

    Not when the answer says the entry does not balance: "Check if it
    balances" for the user's own unbalanced entry was answered correctly and
    then replaced by bare working as a calculation error (27 Oct 2026)."""
    if _SAYS_UNBALANCED.search(answer_text or ""):
        return []
    failures: list[str] = []
    lines = answer_text.splitlines()
    index = 0
    while index < len(lines):
        if not lines[index].lstrip().startswith("|"):
            index += 1
            continue
        block = []
        while index < len(lines) and lines[index].lstrip().startswith("|"):
            block.append(_cells(lines[index]))
            index += 1
        header, rows = block[0], [row for row in block[1:] if not all(set(c) <= set("-: ") for c in row)]
        debit = next((i for i, cell in enumerate(header) if _DEBIT_HEADER.search(cell)), None)
        credit = next((i for i, cell in enumerate(header) if _CREDIT_HEADER.search(cell)), None)
        if debit is None or credit is None or debit == credit or not rows:
            continue

        def numeric_column(column: int) -> int:
            # "Account (Debit) | Amount | Account (Credit) | Amount": the
            # figures sit in the column after the one that names the side.
            values = [_amount(row[column]) for row in rows if column < len(row) and row[column]]
            if values and sum(v is not None for v in values) * 2 < len(values) and column + 1 < len(header):
                return column + 1
            return column

        debit, credit = numeric_column(debit), numeric_column(credit)
        totals = [Decimal(0), Decimal(0)]
        stated: list[Decimal | None] = [None, None]
        for row in rows:
            # "| | **Total** | 133,650.60 | 126,370.91 |": the label may sit in
            # any column but the amounts; it was summed in, and a wrong stated
            # total was never compared.
            if any(re.search(r"\btotal\b", cell, re.I) for at, cell in enumerate(row) if at not in (debit, credit)):
                stated = [_amount(row[column]) if column < len(row) else None for column in (debit, credit)]
                continue
            for slot, column in enumerate((debit, credit)):
                value = _amount(row[column]) if column < len(row) else None
                if value is not None:
                    totals[slot] += value
        if totals[0] > 0 and totals[1] > 0 and abs(totals[0] - totals[1]) > Decimal("0.5"):
            failures.append(
                f"Journal entry does not balance: debits total {_format_decimal(totals[0])}, "
                f"credits total {_format_decimal(totals[1])}."
            )
        for side, shown, total in zip(("debit", "credit"), stated, totals):
            if shown is not None and total > 0 and abs(shown - total) > Decimal("0.5"):
                failures.append(
                    f"Journal total does not match its lines: the {side} total is shown as "
                    f"{_format_decimal(shown)}, but the {side} lines add up to {_format_decimal(total)}."
                )
    return failures + _text_journal_balance_failures(answer_text)


# "Dr Right-of-use asset £133,650.60" / "Credit Lease liability: $126,370.91".
_TEXT_JOURNAL_LINE = re.compile(
    r"^\s*(?:[-*•]\s*)?(?:\*\*)?(?P<side>Dr|Debit|Cr|Credit)\b\.?(?:\*\*)?\s*:?\s+(?P<rest>.+)$", re.I)
_TEXT_AMOUNT = re.compile(r"(?:[£$€₹]|\b(?:GBP|USD|EUR|INR|Rs\.?)\s*)?\d(?:[\d,]*\d)?(?:\.\d+)?")


def _text_journal_balance_failures(answer_text: str) -> list[str]:
    """A journal written as text lines ("Dr … / Cr …") whose sides differ.
    Only table journals were checked, so "Dr Right-of-use asset £133,650.60 /
    Cr Lease liability £126,370.91" went out unflagged. An entry is checked
    only when every line states exactly one amount; anything less certain
    (a working, a year in the account name, a "To …" line) is left alone."""
    failures: list[str] = []
    entry: list[tuple[str, Decimal | None]] = []

    def close() -> None:
        sides = {"dr": Decimal(0), "cr": Decimal(0)}
        if entry and all(value is not None for _, value in entry):
            for side, value in entry:
                sides[side] += value
            if sides["dr"] > 0 and sides["cr"] > 0 and abs(sides["dr"] - sides["cr"]) > Decimal("0.5"):
                failures.append(
                    f"Journal entry does not balance: debits total {_format_decimal(sides['dr'])}, "
                    f"credits total {_format_decimal(sides['cr'])}."
                )
        entry.clear()

    for line in answer_text.splitlines():
        segments = [segment for segment in re.split(r";\s*", line) if segment.strip()]
        lines = [_TEXT_JOURNAL_LINE.match(segment) for segment in segments]
        if not segments or not all(lines):
            close()
            continue
        for match in lines:
            side = "dr" if match.group("side").lower().startswith("d") else "cr"
            if side == "dr" and any(earlier == "cr" for earlier, _ in entry):
                close()        # a debit after credits starts the next entry
            amounts = _TEXT_AMOUNT.findall(match.group("rest"))
            entry.append((side, _amount(amounts[0]) if len(amounts) == 1 else None))
    close()
    return failures


def plain_arithmetic(answer_text: str) -> str:
    """Answer text as the equation checks read it. LaTeX becomes plain text;
    emphasis and a spaced percent sign are presentation: "= **27.74 %**" (a
    narrow no-break space before %) was not read as a result at all, so a
    wrong bold figure passed every check (22 Oct 2026)."""
    from app.orchestration.answer_formatting import latex_to_plain
    # Not the power operator: "1.728/(1.09**2) = 1.454423" became "1.092" and
    # four correct present values were reported as mismatches (23 Oct 2026),
    # and "1 / (1.1 ** 4)", written with spaces, lost its operator too.
    text = latex_to_plain(answer_text)
    return re.sub(r"(\d)[ \u00a0\u202f]+%", r"\1%", re.sub(r"\*\*", lambda match: _bold_or_power(text, match), text))


def _bold_or_power(text: str, match: re.Match) -> str:
    """"**" between an operand and a number or "(" is a power, kept; any
    other "**" is emphasis, removed."""
    before = text[:match.start()].rstrip(" ")
    after = text[match.end():].lstrip(" ")
    power = bool(before) and (before[-1].isdigit() or before[-1] == ")") and bool(after) and (
        after[0].isdigit() or after[0] in "(-")
    return match.group(0) if power else ""


def shows_arithmetic(answer_text: str) -> bool:
    """The answer shows a computed equation ("£24,000 ÷ 12 = £2,000"), read
    the way validate_answer_calculations reads one."""
    normalized = _normalise_arithmetic(plain_arithmetic(answer_text).replace("\\times", "*").replace("\\div", "/"))
    return any(any(operator in match.group("expression") for operator in "+-*/×÷")
               for match in _EQUATION.finditer(normalized))


def validate_answer_calculations(answer_text: str) -> list[str]:
    """Return failures only for simple equations we can verify with certainty."""
    # "10{,}000 \times 1.1025 = 10{,}025" was unreadable here, and a wrong
    # compound-interest result ($10,025 for $11,025) was released.
    answer_text = plain_arithmetic(answer_text)
    failures: list[str] = []
    normalized = _normalise_arithmetic(answer_text.replace("\\times", "*").replace("\\div", "/"))
    for match in _EQUATION.finditer(normalized):
        expression = match.group("expression").strip()
        line_start = normalized.rfind("\n", 0, match.start()) + 1
        step_start = max(line_start, normalized.rfind("=", line_start, match.start()) + 1)
        # A step with a power counts even when the match starts after the
        # "^" at a bare number ("10,000 × (1 + 0.05)^2 = 12,000").
        has_power = bool(re.search(r"\^|\*\*", normalized[step_start:match.end()]))
        if not any(operator in expression for operator in "+-*/×÷") and not has_power:
            continue
        # Powers are outside what this checker evaluates, and the match
        # starts after the exponent: "(150,000 ÷ 100,000)^(1/3) − 1 =
        # 0.144714" (a correct CAGR) was judged as "(1/3) − 1 = -0.67", and
        # that one false mismatch replaced a whole nine-part answer.
        # Only this step of a chain counts: in "FV = 10,000 × (1 + 0.05)^2 =
        # 10,000 × 1.1025 = 10,025" the power in the first step hid the wrong
        # final step ($10,025 for $11,025) from the check.
        if has_power:
            # The whole step is checked when it is plain arithmetic: skipping
            # every power let "1.728/(1.09**2) = 1.60" (1.454423) through
            # (23 Oct 2026). A step with words or units is still skipped.
            equals = normalized.rfind("=", match.start(), match.start("result"))
            whole = normalized[step_start:equals].strip()
            if not re.fullmatch(r"[0-9,.()\s+\-*/×÷^]+", whole) or not re.search(r"\^|\*\*", whole):
                continue
            expression = whole
        # An equation in an unknown is not arithmetic: "Revenue × (1 − 0.45) −
        # 840,000 = 900,000" (the target-profit condition) was read from its
        # first number as "(1 − 0.45) − 840,000 = 900,000", judged false, and
        # a correct forecast follow-up was replaced by its working.
        if re.search(r"[A-Za-z]\w*\)?\s*[*×/÷+\-]\s*\(?\s*$", normalized[step_start:match.start()]):
            continue
        try:
            expected = _evaluate(expression)
            stated = Decimal(match.group("result").replace(",", ""))
        except (SyntaxError, ValueError, InvalidOperation):
            continue
        # "200,000 / 500,000 = 40%" states the ratio as a percentage.
        if match.group("percent"):
            # An explicit ×100 already converted the ratio to percent units.
            candidates = [expected] if re.search(r"[×*]\s*100\s*\)*$", expression) else [expected * 100]
        else:
            candidates = [expected]
        # Judge the precision displayed, not the size of the amount. A
        # relative tolerance allowed a 53-rupee error on a million-rupee sum.
        tolerance = Decimal(5).scaleb(stated.as_tuple().exponent - 1)
        if all(abs(candidate - stated) > tolerance
               for candidate in candidates):
            failures.append(
                f"Calculation mismatch: {expression} equals {_format_decimal(expected)}, "
                f"not {_format_decimal(stated)}."
            )
    return failures + _journal_balance_failures(answer_text)


def build_observation_chart(observations: list[LiveObservation]) -> VerifiedChartSpec | None:
    if not observations:
        return None
    unit = observations[0].unit
    compatible = [item for item in observations if item.unit == unit]
    try:
        values = [_format_decimal(Decimal(item.value)) for item in compatible]
    except InvalidOperation:
        return None
    return VerifiedChartSpec(
        chart_id=f"chart_{uuid.uuid4().hex}", type="line",
        title=compatible[0].indicator,
        categories=[item.period for item in compatible],
        series=[VerifiedChartSeries(
            name=compatible[0].indicator, values=values, unit=unit,
            source_ids=[item.observation_id for item in compatible],
        )],
        calculation_id="live_observations",
    )
