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
_FX = re.compile(r"\b(convert|exchange rate|fx|forex|in (?:usd|eur|gbp|inr|aud|cad|jpy)|to (?:usd|eur|gbp|inr|aud|cad|jpy))\b", re.I)
_DECLARED_UNITS = re.compile(
    r"\ball\s+(?:amounts|figures|values)(?:\s+(?:below|above|shown|provided|quoted))?\s+"
    r"(?:are\s+)?(?:stated\s+|expressed\s+)?in\s+(?:USD|EUR|GBP|INR|AUD|CAD|JPY)\b", re.I,
)
_ECONOMY = re.compile(r"\b(gdp|inflation|cpi|unemployment|interest rate|repo rate|base rate|debt[- ]to[- ]gdp|economic growth|fiscal)\b", re.I)
_MARKET = re.compile(r"\b(stock|share price|shares|market cap|ticker|nasdaq|nyse|10-k|annual report|revenue of [A-Z]|earnings|dividend)\b", re.I)
_COMPUTE = re.compile(r"\b(calculate|compute|how much|total|margin|ratio|percentage|growth rate|difference|variance|"
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
    rule_text = _EXCLUDED_SPAN.sub(" ", q)
    # Figures to work with — not periods ("5 years") or calendar years ("2024").
    numbers = len(_NUMBER.findall(_PERIOD.sub(" ", q)))
    tools: list[str] = []
    reasons: list[str] = []

    if _RULE.search(rule_text):
        tools.append("search_knowledge_base")
        reasons.append("professional rule or authority named")
    if _FX.search(_DECLARED_UNITS.sub(" ", q)):
        tools.append("get_exchange_rate")
        reasons.append("currency conversion")
    if _ECONOMY.search(q):
        tools.append("get_economic_indicator")
        reasons.append("economic indicator")
    if _MARKET.search(q):
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
