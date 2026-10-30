"""The plan Kriton proposes before any evidence is fetched (ZL-ENG-AGT-01 §02,
§05.5, App. B4 `kriton.propose_plan`).

Deterministic and model-free: it reads only the question, so it is fast,
repeatable and testable, and the backend (not the model) decides how much
work a question needs.

  • "simple"  — a definition or concept question with nothing to fetch or
                compute. It skips the tool loop: one grounded answer from the
                governed knowledge base and a single search.
  • "agent"   — anything that needs live data, a calculation, a chart, a
                comparison or research. The agent receives the planned tool
                sequence and the allowed tool list; it fetches the evidence
                itself, so nothing (beyond the governed knowledge base) is
                pre-fetched.

The plan is a proposal. Policy still authorises every tool call, and a call
outside the plan is allowed but flagged as unplanned in the trace.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_PERIOD = re.compile(r"\b\d+\s*(?:years?|months?|days?|quarters?|weeks?)\b|\b(?:19|20)\d{2}\b|\bFY\s?\d{2,4}\b", re.I)
_CHART = re.compile(r"\b(chart|graph|plot|visuali[sz]e|trend line|bar|pie|histogram)\b", re.I)
# Not a convertible bond converted into shares: "purchase the bond and
# convert it immediately" planned an exchange-rate lookup (22 Oct 2026). "it"
# with a currency after it is a conversion: "Convert it to pounds at the
# latest rate" (the benchmark check, 23 Oct 2026).
_CURRENCY_TARGET = (r"(?:to|into|in)\s+(?:[A-Z]{3}\b|pounds?|sterling|euros?|dollars?|rupees?|yen|yuan|francs?|"
                    r"dirhams?|riyals?|reais|real)")
_FX = re.compile(r"\b(convert(?!ible)(?!\s+(?:it|them)\b(?![^.\n]{0,30}?\b" + _CURRENCY_TARGET + r"))"
                 r"(?![^.\n]{0,40}\b(?:shares?|stock|equity)\b)|exchange rate|fx|forex|in (?:usd|eur|gbp|inr|aud|cad|jpy)|to (?:usd|eur|gbp|inr|aud|cad|jpy))\b", re.I)
_DECLARED_UNITS = re.compile(
    r"\ball\s+(?:amounts|figures|values)(?:\s+(?:below|above|shown|provided|quoted))?\s+"
    r"(?:are\s+)?(?:stated\s+|expressed\s+)?in\s+(?:USD|EUR|GBP|INR|AUD|CAD|JPY)\b", re.I,
)
_ECONOMY = re.compile(r"\b(gdp|inflation|cpi|unemployment|interest rate|repo rate|base rate|debt[- ]to[- ]gdp|economic growth|fiscal(?![\s-]+(?:years?|year-end|periods?|quarters?|months?)))\b", re.I)
_MARKET = re.compile(r"\b(stock|share price|shares|market cap|ticker|nasdaq|nyse|10-k|annual report|revenue of [A-Z]|earnings|dividend)\b", re.I)
# Share-capital wording in a supplied scenario is accounting, not a market
# lookup: "2,000,000 outstanding shares", "20,000 shares of preferred stock",
# "stock options", "earnings per share". On 22 Oct 2026 WACC and diluted-EPS
# questions about invented companies were planned a market-data fetch, which
# found nothing, and the answer said the supplied prices were unavailable.
# Removed before _MARKET is tested; "Apple's share price", a ticker or a
# market cap still plans the fetch.
_SHARE_CAPITAL_TERMS = re.compile(
    r"\b(?:\d[\d,.]*\s*(?:million\s+|m\s+)?(?:outstanding\s+|common\s+|ordinary\s+|preferred\s+|preference\s+)?shares"
    r"|shares\s+(?:of|outstanding|issued|authori[sz]ed|in\s+issue)|(?:outstanding|treasury)\s+shares"
    r"|(?:common|preferred|preference|ordinary|treasury|capital|voting|non-voting)\s+(?:stock|shares?)"
    r"|stock[- ](?:options?|dividends?|splits?|based|compensation)|share[- ](?:based|capital|options?)"
    r"|(?:annual|cash|preferred|quarterly|interim|final)\s+dividends?|dividends?\s+(?:of|paid|declared|per|payable)"
    r"|retained\s+earnings|(?:basic\s+|diluted\s+)?earnings\s+per\s+share)\b", re.I)
# A rate the question gives is an input, not an indicator to fetch: "issue
# $3,000,000 in new debt at an 8% annual interest rate" planned an economic
# data lookup (22 Oct 2026).
_SUPPLIED_INTEREST_RATE = re.compile(
    r"\d+(?:\.\d+)?\s?%\s+(?:annual\s+|fixed\s+|nominal\s+|coupon\s+)?interest\s+rate"
    r"|\binterest\s+rate\s+(?:of|is|at)\s+\d+(?:\.\d+)?\s?%"
    # "interest rate from 8% down to 4%", "the inflation rate in Brazil is
    # expected to remain stable at 6.0%" (23 Oct 2026).
    r"|\b(?:nominal\s+|annual\s+)?(?:interest|inflation|repo|base)\s+rates?\b[^.\n%]{0,50}?\d+(?:\.\d+)?\s?%"
    # A rate the question asks to compute: "calculate the new effective
    # interest rate for subsequent periods" (TDR, 23 Oct 2026).
    r"|\b(?:effective|implicit|internal|imputed|new)\s+(?:annual\s+)?interest\s+rates?\b", re.I)
# A scenario with its own figures needs no market data unless it asks for a
# live price or names a listing: "Sell 20% of NewTech … for $500,000" and a
# dividend recapitalisation planned market lookups for invented companies.
_SCENARIO_MONEY = re.compile(r"[£$€₹]\s?\d[\d,]*(?:\.\d+)?")
_SCENARIO_PERCENT = re.compile(r"\b\d+(?:\.\d+)?\s?%")
_MARKET_LOOKUP = re.compile(r"\b(share price|stock price|market cap|ticker|nasdaq|nyse|10-k|annual report|listed)\b", re.I)
_COMPUTE = re.compile(r"\b(calculat\w*|compute|journal\s+entr(?:y|ies)|how much|total|margin|ratio|percentage|growth rate|difference|variance|"
                      r"compare|net|profit|loss|depreciation|interest|tax due|vat due|gst due|"
                      # Projections: "£1,000,000 growing 8% a year … after three
                      # years" was planned as web research, and the calculated
                      # £1,259,712 replaced by "the sources do not contain this".
                      r"grow(?:s|ing|th)?|increases?|decreases?|drops?|falls?|rises?|forecast|projected|compound(?:ed)?|"
                      r"after\s+\w+\s+years?)\b", re.I)
_LIVE = re.compile(r"\b(latest|current|today|now|this (?:week|month|year)|live)\b", re.I)
_RULE = re.compile(r"\b(vat|gst|tax|income[- ]tax|corporation tax|threshold|deadline|filing|return|ifrs|ias|gaap|"
                   r"section \d+|form \w+|hmrc|irs|regulation|rule|standard|audit|compliance)\b", re.I)
_SIMPLE_OPENER = re.compile(r"^\s*(what is|what are|what's|define|explain|meaning of|describe|why do|why does|"
                            r"what does|how does|difference between|when (?:is|must|do))\b", re.I)
# "File my VAT return", "submit our GSTR-3B", "pay HMRC", "post this journal".
_WRITE_REQUEST = re.compile(
    r"\b(?:file|submit|lodge|send|pay|post|book|transfer|e-?file)\b[^.?!]{0,40}?"
    r"\b(?:return|vat|gst|gstr|itr|tax|payroll|rti|p11d|payment|invoice|journal|filing|hmrc|irs|accounts|confirmation statement)\b",
    re.I,
)
# Practical process guidance — how to organise the work, not what a rule,
# tax or standard requires. Decision C (approved): ordinary explanatory
# questions may be answered as a labelled general explanation; accounting,
# tax and financial claims keep their evidence requirements, so anything
# matching _RULE or carrying figures never takes this path.
_PRACTICE_GUIDANCE = re.compile(
    r"\b(?:month[- ]end|year[- ]end|close|closing)\s+(?:steps|process|checklist|procedures?|routine)\b|"
    r"\b(?:steps|checklist|process|workflow|routine|controls|best practices?)\b[^.?]{0,60}\b(?:should|could|put in place|"
    r"set up|introduce|start|first|organi[sz]e)\b", re.I)
GENERAL_GUIDANCE_REASON = "practical guidance; general explanation allowed (Decision C)"
_MULTI_PART = re.compile(r"\?.+\?|\b(and also|as well as|then|also show|plus)\b", re.I)
# A comment on, or summary of, the earlier answer or the attached files needs
# nothing fetched or computed. "comment on the above" after three PDFs searched
# the knowledge base three times, tried the calculator twice and ran out of
# token budget before writing anything (30 Oct 2026).
_ABOUT_WHAT_IS_HERE = re.compile(
    r"^\s*(?:please\s+|can you\s+|could you\s+)?(?:comment on|summari[sz]e|review|critique|give (?:your |me )?"
    r"(?:comments?|feedback|views?|thoughts) on|what do you think (?:of|about))\s+"
    r"(?:above|it|them|(?:the|this|these|that|those)(?:\s+above)?(?:\s+(?:answer|response|statements?|summary|"
    r"report|files?|documents?|results?|table))?)\s*[.!?]?\s*$", re.I)


@dataclass(frozen=True)
class ExecutionPlan:
    mode: str                                  # "simple" | "agent"
    tools: tuple[str, ...] = ()                # planned order
    reasons: tuple[str, ...] = field(default_factory=tuple)
    # The user asked Kriton to file, submit or pay something. Kriton never
    # does (no write tools, §10.5); the answer says so before any steps.
    write_request: bool = False

    def as_prompt(self) -> str:
        if self.mode != "agent" or not self.tools:
            return ""
        steps = " → ".join(self.tools)
        return (f"\n\nPlanned steps (backend plan, policy-approved): {steps}. Follow this plan; call another "
                "tool only if a result shows the plan is not enough, and never call a tool you do not need.")

    def without(self, tool: str) -> "ExecutionPlan":
        return ExecutionPlan(mode=self.mode, tools=tuple(t for t in self.tools if t != tool),
                             reasons=self.reasons + (f"{tool} already done before the agent ran",),
                             write_request=self.write_request)

    def summary(self) -> dict:
        return {"mode": self.mode, "planned_tools": list(self.tools), "reasons": list(self.reasons),
                "write_request": self.write_request}


_ACTION_VERB = r"(?:file|submit|lodge|send|pay|post|book|transfer|e-?file)"
# The user is asking Kriton to act: the request starts with the action, or
# asks Kriton to do it ("can you file…", "please submit…", "…for me").
_ASKS_TO_ACT = re.compile(
    rf"^\s*(?:please\s+)?{_ACTION_VERB}\b|\b(?:can|could|will|would)\s+you\s+(?:please\s+)?{_ACTION_VERB}\b|"
    rf"\bplease\s+{_ACTION_VERB}\b|\b{_ACTION_VERB}\b[^.?!]*\bfor me\b",
    re.I,
)


def is_write_request(question: str) -> bool:
    """"File my VAT return" is a request to act; "How do I file a VAT
    return?" is a question about how to."""
    return bool(_WRITE_REQUEST.search(question or "") and _ASKS_TO_ACT.search(question or ""))


WRITE_REQUEST_NOTICE = ("Kriton can't file, submit or pay anything on your behalf. "
                        "Here is how to do it yourself:")


# What the user tells Kriton to leave out is not a topic: "Ignore interest,
# tax and depreciation for this simplified model" planned a tax-rule search
# for a pure operating forecast, and the answer opened with "the sources do
# not define contribution margin" (qry-58ce336ac0d7).
_EXCLUDED_SPAN = re.compile(r"\b(?:ignore|ignoring|disregard|disregarding|leave out|leaving out)\b[^.;\n]*", re.I)


def plan_request(question: str, *, has_documents: bool = False, history: bool = False) -> ExecutionPlan:
    q = question or ""
    if (has_documents or history) and _ABOUT_WHAT_IS_HERE.search(q):
        return ExecutionPlan(mode="simple", tools=(), reasons=(
            "comment on the earlier answer or attached files; no tools needed",), write_request=False)
    rule_text = _EXCLUDED_SPAN.sub(" ", q)
    # Figures to work with — not periods ("5 years") or calendar years ("2024").
    numbers = len(_NUMBER.findall(_PERIOD.sub(" ", q)))
    tools: list[str] = []
    reasons: list[str] = []

    if _RULE.search(rule_text):
        tools.append("search_knowledge_base")
        reasons.append("professional rule or authority named")
    from app.orchestration.calculation_service import NEGATED_LOOKUP
    from app.orchestration.fx_profit import SUPPLIED_FX_RATE
    # "Do not retrieve a live rate", "without checking the current repo rate":
    # instructions about tools, never a request for them (23 Oct 2026).
    q = NEGATED_LOOKUP.sub(" ", q)
    supplied_fx = bool(SUPPLIED_FX_RATE.search(q)) and not re.search(r"\b(?:latest|today|live)\b", q, re.I)
    if _FX.search(_DECLARED_UNITS.sub(" ", q)) and not supplied_fx:
        tools.append("get_exchange_rate")
        reasons.append("currency conversion")
    if _ECONOMY.search(_SUPPLIED_INTEREST_RATE.sub(" ", q)):
        tools.append("get_economic_indicator")
        reasons.append("economic indicator")
    # The shared live-data decision (calculation_service.live_data_requested).
    from app.orchestration.calculation_service import live_data_requested, supplied_fact_kinds
    live = live_data_requested(q)
    # "stock price" names a market lookup unless the question gives that price
    # itself ("the current market price of the stock is $48"); a ticker, a
    # listing or a market cap still does.
    market_terms = {term.lower() for term in _MARKET_LOOKUP.findall(q)}
    if market_terms <= {"share price", "stock price"} and "price" in supplied_fact_kinds(q):
        market_terms = set()
    own_scenario = (len(_SCENARIO_MONEY.findall(q)) + len(_SCENARIO_PERCENT.findall(q)) >= 3 and not live
                    and not market_terms)
    if _MARKET.search(_SHARE_CAPITAL_TERMS.sub(" ", q)) and not own_scenario:
        tools.append("get_market_data")
        reasons.append("market or company data")
    # Something to compute: figures the question gives, or one figure plus a
    # rate or value another tool looks up ("tax due on profits of 300,000").
    # In a conversation the other figures are in the earlier turns: "Using the
    # same figures, what profit would 6,000 units give?" has one number of its
    # own, so only search_web was planned; the agent calculated £36,000, was
    # then told to answer only from search results, and replaced the result
    # with "the sources do not establish this".
    if _COMPUTE.search(q) and (numbers >= 2 or (numbers >= 1 and (tools or history))
                               or "get_exchange_rate" in tools or "get_market_data" in tools):
        tools.append("calculate")
        reasons.append("figures to compute")
    if supplied_fx and "calculate" not in tools and re.search(r"\b(?:convert|translate)\w*", q, re.I):
        # A conversion at the rate the question gives is arithmetic on its own
        # figures: "convert EUR 50,000 at 1.10 USD per EUR" (23 Oct 2026).
        tools.append("calculate")
        reasons.append("figures to compute")
    if _CHART.search(q):
        tools.append("render_chart")
        reasons.append("chart requested")

    data_tools = {"get_exchange_rate", "get_economic_indicator", "get_market_data", "calculate", "render_chart"}
    simple = (
        not has_documents and not history and not (set(tools) & data_tools)
        and bool(_SIMPLE_OPENER.search(q)) and not _MULTI_PART.search(q) and not _LIVE.search(q) and numbers <= 1
    )
    write_request = is_write_request(q)
    if (not simple and not tools and not has_documents and not _RULE.search(rule_text) and not _LIVE.search(q)
            and numbers <= 1 and _PRACTICE_GUIDANCE.search(q)):
        # "What month-end close steps should we put in place first?" was sent
        # to web research, found nothing and answered "the sources do not
        # contain this" (int-planning-recommendation).
        return ExecutionPlan(mode="simple", tools=(), reasons=(GENERAL_GUIDANCE_REASON,), write_request=write_request)
    if simple:
        return ExecutionPlan(mode="simple", tools=(), reasons=("definition or concept question; no tools needed",),
                             write_request=write_request)
    # Web research when a rule or authority is involved, or when nothing else
    # in the plan can supply evidence; not for figures the question supplies
    # or a data tool fetches.
    needs_research = bool(_RULE.search(rule_text)) or not tools
    if needs_research and not (set(tools) & {"get_exchange_rate", "get_economic_indicator", "get_market_data"}):
        # Rules and research beyond the governed knowledge base.
        insert_at = 1 if tools[:1] == ["search_knowledge_base"] else 0
        tools.insert(insert_at, "search_web")
        reasons.append("may need sources beyond the knowledge base")
    return ExecutionPlan(mode="agent", tools=tuple(dict.fromkeys(tools)), reasons=tuple(reasons),
                         write_request=write_request)
