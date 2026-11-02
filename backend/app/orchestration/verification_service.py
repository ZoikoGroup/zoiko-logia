"""Answer correction and the final evidence verification release gate."""
from __future__ import annotations
import asyncio
import re
from typing import Callable, Awaitable
from dataclasses import dataclass, field
from app.orchestration import claim_verification
from app.orchestration.telemetry import StageMetrics
from app.domains.model_gateway import service as model_gateway_service
from app.domains.model_gateway.errors import ProviderRequestTooLarge, ProviderResponseIncomplete, RequestBudgetExhausted
from app.orchestration.calculation_service import needs_lookup
from app.orchestration.derived_output import is_illustration_heading, is_scenario_sentence

_MODEL_PROVIDER_FAILURE = "Kriton is temporarily unable to reach the language model provider."
# Claim batches judged at once; bounded for the provider's tokens-per-minute cap.
_VERIFY_CONCURRENCY = 3

_CLAIM_REMOVED_NOTE = (
    "A statement was removed because it conflicted with the cited sources. "
    "Check the sources for the exact rule."
)
_UNSUPPORTED_REMOVED_NOTE = (
    "Statements the cited sources do not support were removed from this answer. "
    "Check the sources for anything not covered here."
)
_UNVERIFIED_REMOVED_NOTE = (
    "Statements Kriton could not verify against its sources were removed. "
    "Check the official source before relying on this answer."
)
_UNVERIFIED_ANSWER_NOTE = (
    "Kriton could not check this answer against its sources, so it is unverified. "
    "Check the official source before relying on it."
)
_CLAIM_UNCORRECTED_NOTE = (
    "A statement in this answer may conflict with the cited sources and could not be corrected. "
    "Check the sources before relying on it."
)
_CLAIMS_UNCONFIRMED_NOTE = (
    "Some figures in this answer could not be confirmed in the sources retrieved for it "
    "and may be out of date. Check them against the official source before relying on them."
)


async def _verify_answer_claims(
    answer: str,
    *,
    evidence: list[str],
    question: str,
    grounded_input: str,
    report: Callable[[str, str], Awaitable[None]],
    metrics: StageMetrics,
    removed: list[dict] | None = None,
) -> tuple[str, str | None]:
    """Judge every statement carrying a specific (amount, rate, threshold,
    form, deadline) against the evidence the answer was composed from, and
    return the answer to show plus a limitation note, if any.

    A contradicted statement gets one corrective rewrite; one that still
    contradicts the evidence is removed and the note says so. An answer to a
    current-rate question whose figures are mostly absent from the evidence
    is kept but flagged: India FY 2025-26 slabs came back as the FY 2024-25
    table, from memory, beside five unrelated citations."""
    if not claim_verification.enabled() or not evidence or not answer:
        return answer, None
    from app.orchestration.derived_output import without_scenarios
    claims = claim_verification.extract_claims(without_scenarios(answer))
    if not claims:
        return answer, None
    await report("verifying", "Checking facts against the sources")
    verdict = await metrics.run(
        "composition.claim_verification",
        claim_verification.verify_claims(claims, evidence, question),
    )
    if verdict.contradicted:
        await report("correcting", "Correcting a statement the sources contradict")
        try:
            corrected = await metrics.run(
                "composition.claim_correction",
                model_gateway_service.run_grounded_completion(
                    grounded_input + claim_verification.correction_request(answer, verdict.contradicted),
                ),
            )
        except (ProviderResponseIncomplete, RequestBudgetExhausted, ProviderRequestTooLarge):
            # The rewrite of a long, three-question answer was cut off at the
            # output limit, and the whole answer was lost as an internal error;
            # so was a ledger statement whose request had used its processing
            # budget by then. The rewrite is optional: keep the answer and say
            # it is unchecked.
            return answer, _CLAIM_UNCORRECTED_NOTE
        if not corrected or not corrected.strip() or _MODEL_PROVIDER_FAILURE in corrected:
            return answer, None
        recheck = await claim_verification.verify_claims(
            claim_verification.extract_claims(corrected), evidence, question,
        )
        if recheck.contradicted:
            # Deleting is final, and the verifier is not perfectly repeatable:
            # "goods 4 years, services 6 months" (correct, cited) was once
            # judged contradicted and removed, leaving empty bullets. Only a
            # sentence contradicted again on a confirming check is removed.
            suspects = [item.claim for item in recheck.contradicted]
            confirm = await claim_verification.verify_claims(suspects, evidence, question)
            confirmed = {item.claim for item in confirm.contradicted} if confirm.ran else set(suspects)
            removable = [claim for claim in suspects if claim in confirmed]
            if removable:
                if removed is not None:
                    # For the audit trail (service.record_removed): contradicted
                    # on the recheck and, when it ran, on a confirming check.
                    removed.extend({"statement": claim, "reason_code": "contradicted_by_cited_source",
                                    "confirmations": 2 if confirm.ran else 1} for claim in removable)
                return claim_verification.remove_claims(corrected, removable), _CLAIM_REMOVED_NOTE
        return corrected, None
    if verdict.mostly_unconfirmed and needs_lookup(question):
        return answer, _CLAIMS_UNCONFIRMED_NOTE
    return answer, None

# Placeholders ("[REF-none]" beside "the sources do not state this") cite
# nothing and are dropped like an invented number.
_CITATION_VARIANT = re.compile(
    # Parentheses too: "(REF‑7)" left every sentence of a correct laptop-VAT
    # answer looking uncited, and it escalated.
    r"\s?[\[【［(]\s*REF[\s\-‐‑‒–—_]?(\d+|none|n/?a|unknown|\?+|x+)\s*[\]】］)]", re.I,
)


_INVENTED_MARKER = re.compile(
    # Fullwidth brackets never belong in an answer: "【calculate Misstatement
    # to materiality ratio】" (39 characters) passed the earlier 30 limit.
    r"\s?(?:【[^】\n]{0,160}】|[\[［]\s*(?:CALC|CALCULATION|SRC|SOURCE)[\s\-‐‑‒–—_]?\d+\s*[\]］])", re.I,
)


# Only the marker words, bare or carrying a figure: "[calculator]" and
# "[calculation basis]" are the reader's text and were being deleted (25 Oct 2026).
_CALCULATED_TAG = re.compile(
    r"\[\s*calculat(?:ed|ion|e)\b(?:\s+result)?\s*[:=]?\s*((?:[^\]\n]{0,40}?\d[^\]\n]{0,40}?)?)\]", re.I)
# A tool call written into the answer as text instead of made: '【calculate:
# expression="180000 * 20000 / 200000", label="Allocated price"}】', sometimes
# unclosed. Shown to users in table cells on 22 Oct 2026. Needs a tool name and
# key="value" arguments, so ordinary prose ("calculate: the formula is…") stays.
_TOOL_CALL_TEXT = re.compile(
    r"\s?【?\s*(?:functions\.)?(?:calculate|render_chart|search_web|search_knowledge_base|get_exchange_rate|"
    r"get_market_data|get_economic_indicator)\s*[:(]\s*\{?\s*\w+\s*=\s*\"[^】\n]*?(?:\}(?:\s*】)?|】)",
)


# Kriton's own tool tags, in the forms the model wrote them on 22 Oct 2026:
# "(calculated with tool – see calculation “NRV total A”)", "(tool – “Total
# inventory”)", "(derived manually)", and sentences about "the exact
# calculation tool". Only these forms: ordinary prose — "use a calculation tool
# such as Excel", "(machine tool – depreciated over 5 years)", "(a machine
# tool: cost $50,000)" — is never touched.
_LABEL = r"[“\"][^”\"\n]{1,60}[”\"]"
_TOOL_MENTION = re.compile(
    r"[ \t]*\(\s*(?:"
    rf"tool\s*[–—-]\s*{_LABEL}"
    rf"|calculated\s+with\s+(?:the\s+)?(?:exact\s+)?(?:calculation\s+)?tool\s*[–—-]\s*see\s+calculation\s+{_LABEL}"
    rf"|see\s+calculation\s+{_LABEL}"
    r"|derived\s+manually|calculated\s+(?:directly|manually)|computed\s+manually"
    r")\s*\)",
    re.I,
)
_TOOL_SENTENCE = re.compile(
    r"(?:(?<=^)|(?<=[.!?]\s)|(?<=\n))[ \t]*[^.!?\n|]*\bthe\s+exact\s+calculation\s+tool\b[^.!?\n|]*[.!?](?=\s|$)",
    re.I | re.M,
)


# Calculator arguments written out instead of called: a JSON object with an
# "expression" key, fenced or bare (an inventory answer showed
# {"expression": "120000 + 45000", "label": "Total inventory to remove"}).
_TOOL_ARGUMENTS_JSON = re.compile(
    r"```(?:json)?[ \t]*\n?\s*\{[^{}]*\"expressions?\"\s*:[^{}]*\}\s*```"
    r"|(?m:^[ \t]*\{[^{}]*\"expressions?\"\s*:[^{}]*\}[ \t]*$)")


# "Aggregate = 180,000 + 140,000 + 210,000 = 530,000 [The sources provided do
# not state this]": the gap sentence the citation rule asks for, misused as a
# bracketed tag on the answer's own arithmetic and table cells (23 Oct 2026).
# Only the bracketed tag goes; a gap sentence on its own line stays.
_INLINE_GAP_TAG = re.compile(
    r"[ \t]*[\[(]\s*the\s+sources?\s+provided\s+do(?:es)?\s+not\s+state\s+this\.?\s*[\])]", re.I)


# The correction round narrated to the reader (23 Oct 2026): a "Re-calculated
# figures (using the calculator tool)" preamble before "Updated answer with
# calculator-verified numbers (structure unchanged)", "preserving the original
# structure and citations", "(calculation 5)", "(see calculations 1‑3)".
_H = r"[-‑‐–]"
_REVISION_PREAMBLE_END = re.compile(
    r"^[ \t]*(?:#{1,6}[ \t]*)?(?:\*\*|__)?[ \t]*(?:updated|revised|corrected)\s+answer\b[^\n]*\n?", re.I | re.M)
_REVISION_PREAMBLE = re.compile(rf"\bre{_H}?\s?calculated\b|\bcalculator\b", re.I)
_REVISION_SENTENCE = re.compile(
    rf"[^.\n|]*(?:\b(?:preserv|retain|keep)\w*\s+(?:the\s+)?(?:original\s+|same\s+)?structure\s+and\s+citations\b|"
    rf"\b(?:preserv|retain|keep)\w*\s+the\s+(?:original|same)\s+structure\b|\bhave\s+been\s+incorporated\s+throughout\b|\bnow\s+(?:shown|use|uses|reflect\w*)\s+(?:as\s+)?the\s+"
    rf"(?:exact\s+)?(?:results?|figures)\s+of\s+the\s+calculator|\bnow\s+use\s+the\s+calculator{_H}?\s?generated\b"
    rf"|\bremains?\s+the\s+same\s+because\s+the\s+[\w\s]{{0,30}}?\s+(?:are|is)\s+unchanged\b)[^.\n|]*[.]?[ \t]*", re.I)
_CALCULATION_NUMBER = re.compile(
    rf"[ \t]*[\[(](?:see\s+)?calc(?:ulation)?s?\.?\s*(?:id\s*)?\d+(?:\s*(?:{_H}|,|and)\s*\d+)*[\])]"
    rf"|[ \t]*\((?:calculator{_H}?\s?derived\s+)?(?:amounts|figures|results)\s+unchanged\)"
    rf"|[ \t]*\(structure\s+unchanged\)", re.I)
# "IAS 33 §13‑13": a paragraph range whose end is not after its start.
_BAD_PARAGRAPH_RANGE = re.compile(
    rf"(\b(?:IAS|IFRS|ASC|FRS|ISA|AS|SA)\s?\d+(?:{_H}\d+)*)[ \t]*(?:§|¶|para(?:graph)?s?\.?)[ \t]*(\d+){_H}[ \t]*(?:§|¶)?(\d+)")


# "What is tax – a grounded example (corrected)", "Corrected journal entries"
# after a figure-correction round (24 Oct 2026).
_REVISION_TAG = re.compile(r"[ \t]*\((?:corrected|revised|updated|recalculated|re-?calculated)\)", re.I)
_REVISION_HEADING_WORD = re.compile(
    r"^([ \t]*(?:#{1,6}[ \t]+|\*\*|__))(?:corrected|revised|updated|recalculated)\s+(\w)", re.I | re.M)


def _strip_revision_narration(text: str) -> str:
    ends = list(_REVISION_PREAMBLE_END.finditer(text))
    if ends and ends[0].start() < 2000 and _REVISION_PREAMBLE.search(text[:ends[0].start()]):
        text = text[ends[0].end():].lstrip("\n")
    text = _REVISION_SENTENCE.sub("", text)
    text = _REVISION_HEADING_WORD.sub(lambda m: m.group(1) + m.group(2).upper(), _REVISION_TAG.sub("", text))
    text = re.sub(r"\n{3,}", "\n\n", _CALCULATION_NUMBER.sub("", text))
    return _BAD_PARAGRAPH_RANGE.sub(
        lambda m: m.group(1) if int(m.group(3)) <= int(m.group(2)) else m.group(0), text)


def remove_tool_mentions(text: str) -> str:
    """The answer without remarks about Kriton's own tools."""
    text = _strip_revision_narration(text or "")
    text = _TOOL_ARGUMENTS_JSON.sub("", text)
    text = _TOOL_MENTION.sub("", text)
    text = _TOOL_SENTENCE.sub("", text)
    return re.sub(r"([.!?]) {2,}(?=\S)", r"\1 ", re.sub(r"[ \t]+\n", "\n", text))


_INTERNAL_CALC_TAG = re.compile(r"[ \t]*\{\s*\[\s*calc[^\]}]*\]\s*\}|[ \t]*\[\s*calc[-‐‑‒–—_][^\]\n]*\]", re.I)


def normalize_citations(answer: str, valid_refs: set[str]) -> str:
    """Rewrite citation markers to the canonical [REF-N] and drop markers for
    references that do not exist.

    The answer model writes 【REF-8】 and [REF‑8] (non-breaking hyphen) as
    often as [REF-8]; neither the
    release check nor the citation-binding check recognised it, so a correct
    £90,000 answer was held back as uncited. It also invents references
    ([REF-16] with 8 sources), which failed binding for the whole answer.
    Dropping an invented marker is safe: verify_for_release still requires
    every claim to bind to a real, supporting reference, so a claim left
    without one still goes to review."""
    def canonical(match: re.Match[str]) -> str:
        if not match.group(1).isdigit():
            return ""
        ref = f"REF-{int(match.group(1))}"
        return f"{match.group(0)[:1] if match.group(0)[:1].isspace() else ''}[{ref}]" if ref in valid_refs else ""
    # Markers the model invents ("【CALC-1】" after a calculation) cite
    # nothing; fullwidth brackets never belong in an answer once real
    # references have been rewritten to [REF-N] above.
    text = remove_tool_mentions(_TOOL_CALL_TEXT.sub("", answer or ""))
    text = _INLINE_GAP_TAG.sub("", text)
    text = _INVENTED_MARKER.sub("", _CITATION_VARIANT.sub(canonical, text))
    # Calculation references the model writes for itself ("{[calc‑valuation_allowance]}",
    # "[calc-3]") reached the reader (25 Oct 2026); they name nothing the reader can see.
    text = _INTERNAL_CALC_TAG.sub("", text)
    # "**[REF-1]**": the marker is shown as a source link and removed from the
    # text, leaving "****" (an IFRS 16 answer, 28 Oct 2026). Unwrap it; an
    # emphasis left empty by a dropped marker goes too.
    text = re.sub(r"(\*\*|__)\s*((?:\[REF-\d+\][\s,;]*)+?)\s*\1", r"\2", text)
    text = re.sub(r"(?<![*\w])\*\*\*\*(?![*\w])", "", text)
    # "[calculate result £6,486]": keep the figure, drop the bracket label.
    return _CALCULATED_TAG.sub(lambda m: m.group(1).strip(), text)


@dataclass
class AnswerVerification:
    passed: bool
    failures: list[str] = field(default_factory=list)
    # Verbatim answer text of claims that are uncited, cited to a reference
    # that is not in the evidence, or judged contradicted/not in evidence.
    rejected_claims: list[str] = field(default_factory=list)
    # True when every other claim was verified as supported, so removing the
    # rejected ones leaves an answer that can be checked again.
    prunable: bool = False
    # One reason code per rejected claim, in the same order (audit only; see
    # REMOVAL_REASONS). Never "false" for a claim the evidence did not address.
    rejected_reasons: list[str] = field(default_factory=list)
    # Explanatory statements kept as general background rather than removed
    # (Decision C): no figure, date, jurisdiction or tax/legal/accounting rule.
    general_explanations: list[str] = field(default_factory=list)


# A tax rate, threshold or rule asserted as fact still needs a source. A
# plain "budget rate"/"exchange rate" label on the user's own scenario does not.
_RULE_ASSERTION = re.compile(r"\b(?:(?:tax|vat|gst|interest|corporation tax) rate|rate of (?:tax|vat|gst)|"
                             r"(?:standard|reduced|zero) rate|threshold|deadline|must|shall|required|requires|law|"
                             r"rule|standard|registered|registration|allowed|permitted|exempt|zero-rated)\b", re.I)


class VerifiedFigures:
    """Computed results (the calculator's outputs and receipts) and the
    inputs they were computed from (calculator inputs, the user's figures)."""

    def __init__(self, results: set[str], inputs: set[str]):
        self.results, self.inputs = results, inputs
        # Calculator expressions whose operands the user never stated.
        self.assumed: list[str] = []

    def __bool__(self) -> bool:
        return bool(self.results)


_PAY_OBLIGATION = re.compile(r"\b(?:must|has to|have to|needs? to|will need to|is required to)\s+(pay|remit|account for)\b",
                             re.I)


def _from_verified_calculation(claim: str, calculated) -> bool:
    """A statement presenting a verified calculation: it shows at least one
    computed result, every other figure is an input the result came from, and
    it asserts no rule, rate, threshold or deadline. A sentence that only
    repeats the user's figures ("The £120,000 is recognised on day one") is
    still a claim and needs a source."""
    # "The business must pay £14,000 to HMRC" states the result as what is
    # owed, not a rule: it was removed as unsupported (24 Oct 2026). Only the
    # obligation to pay or remit the amount is set aside; any other rule word
    # still needs a source, and every figure must still be calculated.
    if not calculated or _RULE_ASSERTION.search(_PAY_OBLIGATION.sub(r"\1", claim)):
        return False
    results = calculated.results if isinstance(calculated, VerifiedFigures) else set(calculated)
    inputs = calculated.inputs if isinstance(calculated, VerifiedFigures) else set()
    from app.orchestration.figure_reconciliation import material_figures
    keys = [_number_key(value) for _, value in material_figures(claim)]
    if _figures_row(claim):
        # A schedule row also carries running totals and balances of verified
        # figures: "Nov 2025 | £2,000 | £4,000" (2,000 + 2,000), "Remaining
        # contract liability | £18,000" (24,000 − 6,000), "£0 (pending)".
        derived = [key for key in keys if key not in results and _from_result(key, results, results | inputs)]
        return (any(key in results for key in keys) or bool(derived)) and all(
            key in results or key in inputs or key in derived or float(key) == 0 for key in keys)
    return any(key in results for key in keys) and all(key in results or key in inputs for key in keys)


# A note beside a schedule figure: "(assessment pending)", "–", "TBC".
_ROW_NOTE = re.compile(r"^[\s\-–—*()]*(?:[A-Za-z][A-Za-z .,]{0,24})?[\s\-–—*()]*$")


def _figures_row(line: str) -> bool:
    """A table row of figures: a label, then cells that each hold a figure,
    a short note or nothing. A row whose cells state a treatment ("Point in
    time on 31 Oct 2025 if distinct") is a claim, not a schedule line."""
    from app.orchestration.figure_reconciliation import _comma_grouped
    if not line.lstrip().startswith("|"):
        return False
    cells = [cell for cell in line.strip().strip("|").split("|")][1:]
    for cell in cells:
        text = re.sub(r"\[[^\]]*sources?[^\]]*\]", " ", _REF_MARKER.sub(" ", cell))  # "[The sources … do not state this]"
        text = re.sub(r"[£$€₹¥]|\b(?:USD|GBP|EUR|INR)\b|-?\d[\d,]*(?:\.\d+)?\s*%?", " ", _comma_grouped(text))
        if not _ROW_NOTE.match(text):
            return False
    return bool(cells)


def _from_result(key: str, results: set[str], verified: set[str]) -> bool:
    """The sum, difference or product of a calculator result and a verified figure."""
    target = float(key)
    if target == 0:
        return False
    firsts, seconds = [float(item) for item in results][:60], [float(item) for item in verified][:60]
    return any(abs(target - candidate) < 0.006 for a in firsts for b in seconds
               for candidate in (a + b, abs(a - b), a * b))


def unbind_calculated_rows(answer: str, calculated) -> str:
    """A schedule row made of the calculator's figures ("Oct 2025 | £2,000
    [REF-1] | £2,000 [REF-1]") cites an IFRS source that states no such
    amount; the calculator is its provenance. Its markers are removed, so it
    is released as a restated calculation instead of failing as "not in the
    cited evidence". A row that asserts a rule keeps its citations.

    Rows are read top to bottom and an accepted row's figures count as
    verified for the rows below it: a running balance (£22,000, then £20,000
    = 24,000 − 4,000) is built from the rows above. `calculated` is extended
    in place, so the release check reads the schedule the same way."""
    if not calculated or not isinstance(calculated, VerifiedFigures):
        return answer
    from app.orchestration.figure_reconciliation import material_figures
    lines = []
    for line in (answer or "").splitlines():
        bare = _REF_MARKER.sub("", line)
        if _figures_row(bare) and _from_verified_calculation(bare, calculated):
            calculated.results |= {_number_key(value) for _, value in material_figures(bare)}
            line = bare
        lines.append(line)
    return "\n".join(lines)


def _number_key(value: float) -> str:
    return f"{round(float(value), 2):.2f}"


def calculated_figures(result, *, question: str = "", receipts: list[dict] | None = None) -> VerifiedFigures:
    """The verified inputs and outputs of a deterministic calculation, the
    agent's calculator receipts (expression and result), and the figures the
    user stated: a line made only of these is the user's own scenario worked
    out, not a research claim. The FX scenario table (qry-3b42c1c9fc1b) lost
    every row — "Budget 1.25 → £100,000" — as "uncited"."""
    results: set[str] = set()
    inputs: set[str] = set()

    def numbers(text: str) -> set[str]:
        found = set()
        for token in re.findall(r"\d[\d,]*(?:\.\d+)?", text or ""):
            try:
                found.add(_number_key(float(token.replace(",", ""))))
            except ValueError:
                pass
        return found
    if result is not None:
        results |= {_number_key(o.value) for o in result.outputs or [] if o.value is not None}
        inputs |= {_number_key(i.value) for i in result.inputs or [] if i.value is not None}
        # A deterministic schedule's rows are calculator results too: a lease
        # schedule's year-4 and year-5 balances were removed as untraceable.
        for table in getattr(result, "tables", None) or []:
            for row in table.get("rows", []):
                results |= numbers(" ".join(row[1:]))
    stated = numbers(question)
    assumed: list[str] = []
    for receipt in receipts or []:
        operands = numbers(str(receipt.get("expression", "")))
        if not all(_traceable(operand, stated | inputs | results) for operand in operands):
            # An operand the user never gave ("30000 - 2000", a £30,000
            # liability built on a fee nobody said was paid): the arithmetic
            # is right, the premise is not verified, so neither is the result.
            assumed.append(str(receipt.get("expression", "")))
            continue
        results |= numbers(f"{receipt.get('result', '')} {receipt.get('rounded', '')}")
        inputs |= operands
    inputs |= stated
    figures = VerifiedFigures(results, inputs)
    figures.assumed = assumed
    return figures


# A balance that exists only because consideration was received or is due.
_BALANCE = re.compile(r"\b(?:contract liabilit\w*|deferred (?:revenue|income)|unearned (?:revenue|income|portion|amount)|"
                      r"(?:revenue|income) received in advance)\b", re.I)
_RECEIVED = re.compile(r"\b(?:paid|pays|received|receives|collected|prepaid|pre-paid|upfront|up-front|in advance|"
                       r"deposit|invoiced|billed|due)\b", re.I)
BALANCE_NOT_ESTABLISHED = "Not established (consideration received or due not stated)"
_FULL_PAYMENT = re.compile(
    r"\b(?:full|entire|whole|total)\s+(?:payment|amount|price|consideration|contract\s+price|fee)\b[^.\n]{0,30}?"
    r"\b(?:upfront|up-front|in\s+advance|paid|collected|received|on\s+signing)\b"
    r"|\b(?:paid|collected|received|settled)\s+in\s+full\b"
    r"|\b(?:full|entire)\s+payment\b", re.I)
_CONTRACT_TOTAL = re.compile(
    r"(?:[$£€₹])\s?(\d[\d,]*(?:\.\d+)?)\s+contract\b"
    r"|\b(?:total\s+)?(?:contract|transaction)\s+(?:price|value|consideration)\s+(?:of|is|was|=)\s*"
    r"(?:[$£€₹])\s?(\d[\d,]*(?:\.\d+)?)", re.I)


def received_consideration(question: str) -> list[float]:
    """Amounts the user says were paid, received, billed or due: "The customer
    paid £24,000 upfront". "The implementation fee is £6,000" is a price, not
    a receipt."""
    from app.orchestration.figure_reconciliation import material_figures
    found: list[float] = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n", question or ""):
        if _RECEIVED.search(sentence):
            found += [value for shown, value in material_figures(sentence) if not shown.endswith("%")]
    if _FULL_PAYMENT.search(question or ""):
        # "assuming full payment upfront" names no amount: the whole contract
        # price was received. Without it, a correct $72,000 contract liability
        # was removed and the answer marked partial (23 Oct 2026).
        found += [float(next(group for group in m.groups() if group).replace(",", ""))
                  for m in _CONTRACT_TOTAL.finditer(question or "")]
    return list(dict.fromkeys(found))


def _balance_supported(value: float, received: list[float], results: set[str], terms: list[int] = ()) -> bool:
    if not received:
        return False
    totals = list(dict.fromkeys([*received, sum(received)]))
    if value > max(totals) + 0.005:
        return False                                 # more than was ever received
    recognised = [float(item) for item in results] + [0.0]
    if any(abs(total - taken - value) < 0.006 for total in totals for taken in recognised):
        return True
    # A straight-line balance of what was received over a term the question
    # states: £24,000 over 12 months leaves £22,000, £20,000, £18,000 (the
    # monthly £2,000 was worked by hand, so no receipt carries it).
    return any(abs(total * k / n - value) < 0.006 for total in totals for n in terms for k in range(n + 1))


def _stated_terms(question: str) -> list[int]:
    """Contract terms the question states: "a 12-month contract" → 12."""
    return sorted({int(n) for n in re.findall(
        r"\b(\d{1,3})[\s-]*(?:months?|years?|quarters?|weeks?|days?)\b", question or "", re.I) if 2 <= int(n) <= 120})


def unsupported_balances(answer: str, question: str, calculated) -> tuple[str, list[str]]:
    """The answer with every contract-liability (deferred, unearned) figure
    that the stated consideration does not support replaced or removed, and
    the figures concerned. The IFRS 15 schedule ran a £28,000, £26,000,
    £24,000 liability from £30,000 — the £24,000 paid plus a £6,000 fee the
    question never said was paid; its arithmetic was right, its premise was
    not. A balance must be an amount stated as received or due, less revenue
    the calculation recognised. Table cells are qualified so the row's
    verified figures stay; a sentence stating such a balance is removed."""
    from app.orchestration.figure_reconciliation import _comma_grouped, material_figures
    received = received_consideration(question)
    terms = _stated_terms(question)
    results = calculated.results if isinstance(calculated, VerifiedFigures) else set()
    flagged: list[str] = []
    lines = (answer or "").splitlines()
    out: list[str] = []
    columns: set[int] = set()
    for line in lines:
        if not line.lstrip().startswith("|"):
            columns = set()
            pieces = re.split(r"(?<=[.!?])\s+", line)
            kept = []
            for piece in pieces:
                bad = [shown for shown, value in material_figures(piece) if not shown.endswith("%")
                       and not _balance_supported(value, received, results, terms)
                       and _number_key(value) not in results] if _BALANCE.search(piece) else []
                if bad:
                    flagged += bad
                    continue
                kept.append(piece)
            if pieces and not kept and line.strip():
                continue
            out.append(" ".join(kept) if len(kept) != len(pieces) else line)
            continue
        cells = line.strip().strip("|").split("|")
        if not columns and not set(line.strip()) <= set("|-: "):
            header = [i for i, cell in enumerate(cells) if _BALANCE.search(cell)]
            if header and not material_figures(_comma_grouped(line)):
                columns = set(header)
                out.append(line)
                continue
        for index in columns:
            if index < len(cells):
                bad = [shown for shown, value in material_figures(cells[index])
                       if not _balance_supported(value, received, results, terms)]
                if bad:
                    flagged += bad[:1]                   # the balance, not the operand beside it
                    cells[index] = f" {BALANCE_NOT_ESTABLISHED} "
        out.append("|" + "|".join(cells) + "|" if columns else line)
    return "\n".join(out), list(dict.fromkeys(flagged))


# Counts and unit conversions a calculation may use without the user stating
# them: "× 3" months, "÷ 12", "× 100" for a percentage, "÷ 365" days.
_CONSTANTS = {_number_key(n) for n in (*range(0, 13), 24, 52, 100, 360, 365, 1000)}


def _traceable(operand: str, verified: set[str]) -> bool:
    """A user-stated figure, an earlier verified result, a counting constant,
    a percentage written as a fraction (45% as 0.45), or one step from those
    (0.55 = 1 − 0.45)."""
    if operand in verified or operand in _CONSTANTS:
        return True
    value = float(operand)
    known = [float(item) for item in verified | _CONSTANTS]
    if any(abs(value * 100 - k) < 0.006 or abs(value / 100 - k) < 0.000006 for k in known):
        return True
    # Combinations of verified figures only (and 1, for "1 − 0.45"): with the
    # counting constants too, 31 (a date) × 1,000 "traced" an invented 31,000.
    known = [float(item) for item in verified][:80] + [1.0]
    known += [k / 100 for k in known]
    return any(abs(value - c) < 0.006 for a in known for b in known
               for c in (a + b, a - b, a * b, a / b if b else 0.0))


_CURRENT = re.compile(r"\b(?:current|currently|today|at present|presently|this tax year)\b", re.I)


def _period_mismatch(claim: str, question: str) -> bool:
    """A question about a specific past period ("between March 1987 and March
    1988") is not answered by today's position: "The current UK registration
    threshold is £90,000" was kept under the 1987 Isle of Man answer."""
    from datetime import date
    years = [int(y) for y in re.findall(r"\b(19\d{2}|20\d{2})\b", question or "")]
    if not years or max(years) >= date.today().year - 1 or re.search(r"\b(?:current|today|now|latest)\b", question, re.I):
        return False
    return bool(_CURRENT.search(claim))


def _jurisdiction_mismatch(claim: str, refs: set[str], *, question_jurisdictions: list[str],
                           source_jurisdictions: dict[str, str], evidence_by_ref: dict[str, str]) -> str | None:
    """The source's jurisdiction when every reference the claim cites belongs
    to a different jurisdiction from the one the question is about, and
    nothing makes it applicable. A UK HMRC table cited for "the VAT
    threshold in the Isle of Man in 1987" established the UK's thresholds,
    not the Isle of Man's. Not a mismatch: a claim that names the source's
    jurisdiction itself ("In the UK, …" — a comparison or a caveat), or a
    source whose own text names the jurisdiction asked about (shared rules,
    shown by the evidence rather than assumed)."""
    from app.orchestration.source_taxonomy import detect_jurisdictions
    if not question_jurisdictions or not refs:
        return None
    # A publisher's location does not restrict its FX observations or general
    # explanations to local law. Mixed FX/tax questions still require the tax
    # claims to cite the applicable jurisdiction's authority.
    if (is_general_explanation(claim) or re.search(r"\b(?:reference|exchange|spot|FX) rate\b", claim, re.I)) \
            and not (_RULE_ASSERTION.search(claim) or _EXTERNAL_RULE.search(claim)):
        return None
    sources = {ref: source_jurisdictions.get(ref) for ref in refs}
    if any(jurisdiction is None or jurisdiction in question_jurisdictions for jurisdiction in sources.values()):
        return None
    named_in_claim = set(detect_jurisdictions(claim, infer_from_tax_terms=False))
    for ref, jurisdiction in sources.items():
        if jurisdiction in named_in_claim:
            return None
        named_in_source = set(detect_jurisdictions(evidence_by_ref.get(ref, ""), infer_from_tax_terms=False))
        if named_in_source & set(question_jurisdictions):
            return None
    return next(iter(sources.values()))


async def verify_for_release(answer: str, *, question: str, evidence: list[str],
                             requires_authority: bool, chart_artifacts: list[str] | None = None,
                             source_jurisdictions: dict[str, str] | None = None,
                             calculated: set[str] | None = None) -> AnswerVerification:
    guidance = operational_guidance_claims(answer, question) if requires_authority else []
    authoritative_lines = []
    for line, in_guidance in _operational_section_lines(answer):
        if in_guidance:
            for statement, _ in _release_claim_pairs(line):
                if statement in guidance:
                    line = line.replace(statement, "", 1)
        authoritative_lines.append(line)
    authoritative_answer = "\n".join(authoritative_lines) if guidance else answer
    if guidance and not _release_claim_pairs(authoritative_answer):
        return AnswerVerification(True, general_explanations=guidance)
    result = await _verify_authoritative_answer(
        authoritative_answer, question=question, evidence=evidence, requires_authority=requires_authority,
        chart_artifacts=chart_artifacts, source_jurisdictions=source_jurisdictions, calculated=calculated,
    )
    result.general_explanations = list(dict.fromkeys(guidance + result.general_explanations))
    # A safe guidance section can survive removal of unsupported rule claims.
    if guidance and not result.passed and not evidence and not result.rejected_claims:
        result.rejected_claims = [original for original, _ in _release_claim_pairs(authoritative_answer)]
        result.rejected_reasons = ["missing_citation"] * len(result.rejected_claims)
    if guidance and result.rejected_claims:
        result.prunable = True
    return result


async def _verify_authoritative_answer(answer: str, *, question: str, evidence: list[str],
                                      requires_authority: bool, chart_artifacts: list[str] | None = None,
                                      source_jurisdictions: dict[str, str] | None = None,
                                      calculated: set[str] | None = None) -> AnswerVerification:
    """Only a complete, supported verdict releases authoritative model prose.

    This runs after every corrective rewrite. Self-contained calculations and
    deterministic descriptions use their own validation, not a model judge.
    Every claim is judged, so a failure lists exactly which statements were
    rejected (see prune_rejected_claims).
    """
    if not requires_authority:
        return AnswerVerification(True)
    from app.orchestration.answer_formatting import verified_chart_presentation
    pairs = [(original, claim) for original, claim in _release_claim_pairs(answer)
             if not verified_chart_presentation(original, answer, chart_artifacts or [])]
    # "VAT = £480." restates the deterministic calculator's verified result;
    # the calculator is its provenance, not a research source. Filtered here,
    # before the evidence check: a mixed request whose research part found
    # nothing had its verified £480 withheld for "evidence unavailable".
    # Cited or not: "the amount due to HMRC for the quarter is £14,000 [REF-1]"
    # restates the calculator's result, which no source states, and was
    # removed as "not in cited evidence" (24 Oct 2026). _from_verified_calculation
    # still refuses any sentence that asserts a rule, rate or threshold.
    restated = [original for original, _ in pairs if _from_verified_calculation(original, calculated)]
    pairs = [(original, claim) for original, claim in pairs if original not in restated]
    own_arithmetic = _user_arithmetic(pairs, answer, question)
    pairs = [(original, claim) for original, claim in pairs if original not in own_arithmetic]
    restated += own_arithmetic
    if not pairs:
        if restated:
            return AnswerVerification(True)
        # An answer that only says the evidence is missing makes no claim to
        # verify. Released, it tells the reader so, as the governed-answer
        # policy requires; escalated, a plain "the sources do not state this"
        # became a review case and the reader got no answer at all.
        pieces = re.split(r"(?<=[.!?])\s+|\n", answer)
        if any(is_evidence_gap_statement(piece) or _is_pure_arithmetic(piece) for piece in pieces):
            # Only arithmetic on the user's figures (re-checked line by line
            # by validate_answer_calculations) or an honest evidence gap.
            return AnswerVerification(True)
        return AnswerVerification(False, ["No verifiable answer claims"])
    if not evidence:
        if restated and all(is_general_explanation(original) for original, _ in pairs):
            # A verified calculation with general explanation around it: kept,
            # labelled (Decision C). General text alone answers no question
            # that needs a source.
            return AnswerVerification(True, general_explanations=[original for original, _ in pairs])
        if restated or (calculated and any(_from_verified_calculation(line, calculated)
                                           for line in answer.splitlines())):
            # Verified calculations beside claims that need a source: the
            # claims are removed (pruned and checked again), not the
            # calculations with them. General explanation stays (Decision C).
            unsupported = [original for original, _ in pairs if not is_general_explanation(original)]
            return AnswerVerification(False, ["Required authoritative evidence is unavailable"],
                                      rejected_claims=unsupported, prunable=True,
                                      rejected_reasons=["missing_citation"] * len(unsupported))
        return AnswerVerification(False, ["Required authoritative evidence is unavailable"])
    if not claim_verification.enabled():
        return AnswerVerification(False, ["Required claim verification is disabled"])
    if len(pairs) > 60:
        return AnswerVerification(False, ["Answer exceeds the bounded claim verification budget"])
    available = {ref for item in evidence for ref in re.findall(r"\[(REF-\d+)\]", item)}
    from app.orchestration.source_taxonomy import detect_jurisdictions
    question_jurisdictions = detect_jurisdictions(question) if source_jurisdictions else []
    evidence_by_ref = {}
    for item in evidence:
        for ref in re.findall(r"\[(REF-\d+)\]", item[:12]):
            evidence_by_ref[ref] = evidence_by_ref.get(ref, "") + " " + item
    failures: list[str] = []
    rejected: list[str] = []
    reasons: list[str] = []
    cited = []
    for original, claim in pairs:
        if (re.search(r'\bcomposition\b', claim, re.I)
                and re.search(r'monthly\s+output\s+tax\s+liability|output\s+tax\s+liability[^.]{0,60}per\s+month', claim, re.I)):
            rejected.append(original)
            reasons.append("policy_rule:composition_threshold_label")
            failures.append('Monthly output-tax liability for a registration procedure was mislabelled as composition-scheme eligibility')
            continue
        if (re.search(r'\bgst\b', question, re.I)
                and re.search(r'\b(?:india|indian|bangalore|bengaluru)\b', question, re.I)
                and re.search(r'\b(?:registration|register|threshold)\b', question, re.I)
                and not re.search(r'10\s*lakhs?|10,00,000', question, re.I)
                and re.search(r'\bservices\b[^.\n]{0,100}?(?:10\s*lakhs?|10,00,000)|(?:10\s*lakhs?|10,00,000)[^.\n]{0,100}?\bservices\b', claim, re.I)
                and not re.search(r'\b(?:states?|manipur|mizoram|nagaland|tripura|special[- ]category)\b', claim, re.I)):
            rejected.append(original)
            reasons.append("policy_rule:state_service_threshold")
            failures.append('A state-specific service registration threshold was stated without its state condition')
            continue
        if (re.search(r'\bcorporation tax\b', question, re.I)
                and (re.search(r'\b(?:ordinary|non[-‑ ]ring[-‑ ]fence)\b', question, re.I) or not re.search(r'\b(?:ring[-‑ ]fence|oil|gas)\b', question, re.I))
                and re.search(r'\bring[-‑ ]fence\b', claim, re.I)
                and not re.search(r'\b(?:only|not|except|oil|gas)\b', claim, re.I)):
            rejected.append(original)
            reasons.append("policy_rule:ring_fence_rate")
            failures.append('A special ring-fence rate was applied to an ordinary-company question')
            continue
        if (re.search(r'\b(?:export|exports|us client|foreign)\b', question, re.I)
                and re.search(r'without (?:charging|payment of|paying) IGST', claim, re.I)
                and re.search(r'refund of (?:the )?IGST paid', claim, re.I)
                and not re.search(r'alternativ|instead|if.*pay|with payment', claim, re.I)):
            rejected.append(original)
            reasons.append("policy_rule:export_igst_refund")
            failures.append('Export without IGST payment was conflated with a refund of IGST paid')
            continue
        if (re.search(r'\bgst\b', question, re.I) and re.search(r'registration', question, re.I)
                and re.search(r'inter[-‑ ]state', claim, re.I) and re.search(r'\bservices\b', claim, re.I)
                and re.search(r'regardless of turnover|irrespective of turnover', claim, re.I)
                and not re.search(r'exempt|except|unless|subject to|notification', claim, re.I)):
            rejected.append(original)
            reasons.append("policy_rule:interstate_exemptions")
            failures.append('Inter-state service registration omitted turnover exemptions')
            continue
        refs = set(re.findall(r"\[(REF-\d+)\]", claim))
        if _period_mismatch(original, question):
            rejected.append(original)
            reasons.append("effective_date_mismatch")
            failures.append("A claim about the current position was given for a question about a past period")
            continue
        mismatch = _jurisdiction_mismatch(original, refs, question_jurisdictions=question_jurisdictions,
                                          source_jurisdictions=source_jurisdictions or {},
                                          evidence_by_ref=evidence_by_ref) if refs and refs <= available else None
        if mismatch:
            rejected.append(original)
            reasons.append("jurisdiction_mismatch")
            failures.append(f"A {mismatch} source was cited for a claim about {', '.join(question_jurisdictions)}")
            continue
        if refs and refs <= available:
            from app.orchestration.derived_tax_rows import split_tax_row
            derived = split_tax_row(claim, answer, question)
            if derived is not None:
                claim, calculation_error = derived
                if calculation_error:
                    rejected.append(original)
                    reasons.append("calculation_error")
                    failures.append(calculation_error)
                    continue
            cited.append((original, claim, refs))
        else:
            rejected.append(original)
            reasons.append("missing_citation")
            failures.append("A factual claim lacks a valid citation to retrieved evidence")
    supported = 0
    batches = [cited[start:start + claim_verification.MAX_CLAIMS]
               for start in range(0, len(cited), claim_verification.MAX_CLAIMS)]
    # Batches are independent, so they run a few at a time: one after another,
    # a long answer (a review of a pasted document, 40+ claims) spent most of
    # the 105 s request deadline here and failed as "temporarily unavailable".
    gate = asyncio.Semaphore(_VERIFY_CONCURRENCY)

    async def judge(batch):
        batch_claims = [claim for _, claim, _ in batch]
        async with gate:
            verdict = await claim_verification.verify_claims(batch_claims, evidence, question)
            if not verdict.ran:
                # One retry: a timed-out or malformed verdict escalated a correct
                # "the threshold is £90,000, not £85,000" answer to review.
                verdict = await claim_verification.verify_claims(batch_claims, evidence, question)
        return verdict

    verdicts = await asyncio.gather(*(judge(batch) for batch in batches))
    for batch, verdict in zip(batches, verdicts):
        if not verdict.ran or verdict.checked != len(batch):
            return AnswerVerification(False, ["Claim verification unavailable or incomplete"])
        for index, (original, _, refs) in enumerate(batch, start=1):
            if index in verdict.rejected_ids:
                rejected.append(original)
                reasons.append("contradicted_by_cited_source" if index in verdict.contradicted_ids
                               else "not_in_cited_evidence")
                failures.append("Answer contains contradicted or unsupported claims")
            elif not set(verdict.evidence_refs.get(index, [])) & refs:
                rejected.append(original)
                reasons.append("citation_not_bound")
                failures.append("Claim verification did not bind a supported claim to its citation")
            else:
                supported += 1
    # Decision C: a statement rejected only for lacking a source, that is
    # general explanation, is kept as general background. Never for a
    # contradiction, a policy rule, a calculation error or a jurisdiction or
    # date mismatch — those are findings about the statement, not a gap.
    # Only beside a real answer — a supported claim or a verified calculation:
    # "Here is some general guidance" is not an answer to "Singapore GST rate?".
    general = [claim for claim, reason in zip(rejected, reasons)
               if reason in _GAP_ONLY_REASONS and is_general_explanation(claim)] if (supported or restated) else []
    if general:
        kept = [(claim, reason) for claim, reason in zip(rejected, reasons) if claim not in general]
        rejected, reasons = [c for c, _ in kept], [r for _, r in kept]
    if not rejected:
        return AnswerVerification(True, general_explanations=general)
    # Name the rejected sentences: "contradicted or unsupported claims" alone
    # told neither a reviewer nor a developer what to look at.
    failures = list(dict.fromkeys(failures)) + [
        "Rejected: " + "; ".join(f"\"{claim[:120]}\"" for claim in rejected[:3])
    ]
    return AnswerVerification(
        False, failures, rejected_claims=rejected, prunable=supported > 0 or bool(general) or bool(own_arithmetic),
        rejected_reasons=reasons,
        general_explanations=general,
    )


_GAP_ONLY_REASONS = {"missing_citation", "not_in_cited_evidence", "citation_not_bound"}
# Anything that makes a statement a specific claim a reader could act on:
# figures, dates, places, and tax, legal, accounting-treatment or standards
# vocabulary. Those keep their full evidence requirement.
_SPECIFIC_CLAIM = re.compile(
    r"\d|[£$€₹%]|\b(?:tax|vat|gst|hmrc|irs|cbic|duty|duties|tax rate|vat rate|interest rate|rate of|threshold|"
    r"deadline|due date|penalt\w*|fine[sd]?|laws?|legal\w*|legislat\w*|regulat\w*|acts?|sections?|rules?|standards?|ifrs|ias|"
    r"gdpr|ccpa|hipaa|sox|data[- ]protection|privacy\s+(?:requirements?|obligations?)|"
    r"gaap|frs|asc|ind as|must|shall|required|requires|mandatory|obliged|entitled|allowed|permitted|prohibited|"
    r"exempt\w*|recogni[sz]\w*|measur\w*|depreciat\w*|amorti[sz]\w*|impair\w*|capitali[sz]\w*|deductib\w*|"
    r"reclaim\w*|refund\w*|liabilit\w*|registered|registration|filing|disclos\w*|current|currently|latest|today)\b",
    re.I)


# A tax, legal or reporting regime: named beside a calculation on the user's
# own figures, it brings in a fact that needs a source, not arithmetic.
_EXTERNAL_RULE = re.compile(
    r"\b(?:corporation tax|income tax|capital gains tax|inheritance tax|withholding tax|vat|gst|hmrc|irs|cbic|"
    r"national insurance|ifrs|ias|gaap|frs|ind as|section \d+\w*|legislation|regulations?|statutory|"
    r"tax (?:rate|band|bracket|slab|relief|allowance|credit)s?)\b", re.I)


def is_figure_statement(statement: str) -> bool:
    """A statement of the user's own scenario figures ("At the budget rate
    the sterling cost is £100,000"): it carries a figure and asserts no tax,
    legal or accounting rule. Removed, it was unverified arithmetic, not a fact
    the sources failed to confirm."""
    from app.orchestration.figure_reconciliation import material_figures
    return bool(material_figures(statement)) and not _RULE_ASSERTION.search(statement) \
        and not _EXTERNAL_RULE.search(statement)


def unsourced_rule_statements(answer: str, calculated) -> list[str]:
    """Statements in a self-contained calculation's answer that bring in a
    tax, legal or reporting rule: "After corporation tax at 19%, profit would
    be £437,400" beside an operating forecast that said to ignore tax. Such an
    answer has no sources and skips the claim check, so these are removed. A
    line that only restates the verified calculation ("VAT = £2,400 × 20% =
    £480" on the user's own rate) is arithmetic, not one of them."""
    return [original for original, _ in _release_claim_pairs(answer)
            if _EXTERNAL_RULE.search(original) and not _from_verified_calculation(original, calculated)
            and not _NOT_SUPPLIED.search(original)]


# Says a fact is missing rather than stating it: "Tax expense and profit after
# tax (no tax rate or provision given)" is the disclosure the user asked for.
_NOT_SUPPLIED = re.compile(
    r"\bno\s+(?:[\w-]+\s+){0,5}(?:given|provided|supplied|stated|available)\b"
    r"|\bnot\s+(?:been\s+)?(?:given|provided|supplied|stated|available|known)\b"
    r"|\b(?:cannot|can't|could not)\s+be\s+(?:confirmed|determined|calculated|verified)\b"
    r"|\b(?:unknown|missing)\b", re.I)


def is_general_explanation(statement: str) -> bool:
    """General background a professional would state without a citation:
    "An executable bank quote includes the bank's spread and settlement
    terms", "A month-end close usually starts with bank reconciliations".
    Not: a figure, a date, a place, or any tax, legal or accounting rule."""
    from app.orchestration.source_taxonomy import detect_jurisdictions
    text = _REF_MARKER.sub("", statement or "").strip(" -*•")
    return (len(text) >= 15 and not _SPECIFIC_CLAIM.search(text)
            and not detect_jurisdictions(text, infer_from_tax_terms=False))


def requests_operational_guidance(question: str) -> bool:
    return bool(re.search(
        r"\b(?:operational\s+(?:framework|guidance|plan|checklist)|(?:response|preparedness|containment)\s+"
        r"(?:plan|framework|checklist)|(?:prepare|draft|create)\b[^.\n]{0,80}\b(?:audit\s+)?(?:response\s+)?checklist)\b",
        question or "", re.I))


def operational_guidance_claims(answer: str, question: str) -> list[str]:
    """Only labelled, optional process suggestions bypass factual sourcing.

    A heading alone cannot exempt a rule, amount, jurisdiction or accounting
    treatment. Retain the existing conservative general-explanation check.
    """
    # The heading and the content classify a suggestion. Its evidence
    # requirement must not depend on one exact wording of the user's ask.
    # Coverage is checked separately against the complete original request.
    kept: list[str] = []
    for line, in_guidance in _operational_section_lines(answer):
        if not in_guidance:
            continue
        for original, claim in _release_claim_pairs(line):
            # "Tax correspondence" names the workflow's subject; it does
            # not assert a tax rule. All remaining specificity checks apply.
            process_text = re.sub(r"\btax\b", "", original, flags=re.I)
            if (re.match(r"^(?:consider|designate|collect|organise|organize|assign|establish|appoint|"
                         r"keep|compile|reconcile|set up|maintain|compare|document|route|track|review|coordinate)\s+", claim, re.I)
                    and is_general_explanation(process_text)):
                kept.append(original)
    return kept


def _operational_section_lines(answer: str):
    """Nested topic headings stay inside the labelled guidance section."""
    level = None
    for line in (answer or "").splitlines():
        heading = re.match(r"^\s*(#{1,6})\s+(.+?)\s*$", line)
        bold_heading = re.fullmatch(r'\s*\*\*(.{1,120}?)\*\*\s*', line) if not heading else None
        if bold_heading:
            heading = re.match(r'^(#) (.+)$', '# ' + bold_heading[1])
        if heading:
            depth = len(heading.group(1))
            title = heading.group(2).strip(" *#").lower()
            if re.fullmatch(r'(?:general operational guidance|optional (?:process|practical|documentation|supporting[- ]document) suggestions|practical suggestions)'
                            r'\s*(?:\([^\n()]*\))?', title):
                level = depth
            elif level is not None and (depth <= level or re.search(r'\b(?:requirements?|obligations?|mandatory)\b', title)):
                level = None
            yield line, False
        else:
            yield line, level is not None


_REF_MARKER = re.compile(r"\s*\[REF-\d+\]")
_NUMBER_TOKEN = re.compile(r"\d[\d,]*(?:\.\d+)?")


def unbind_arithmetic_citations(answer: str, known: str) -> str:
    """A research citation does not support arithmetic on the user's own
    figures: "£2,400 × 20 % = £480 [REF-3]" cited a VAT-return source for a
    multiplication (ps-mixed-vat-and-deadline). On a line that is only
    arithmetic and whose operands all come from the question or the verified
    calculation, the markers are removed; the calculator is its provenance.
    A line that also states a rate or rule keeps its citation."""
    known_numbers = {token.replace(",", "") for token in _NUMBER_TOKEN.findall(known or "")}
    lines = []
    for line in (answer or "").splitlines():
        if _REF_MARKER.search(line):
            bare = _REF_MARKER.sub("", line)
            operands = _NUMBER_TOKEN.findall(bare.split("=", 1)[0])
            if (_is_pure_arithmetic(bare.strip(" -*•")) and operands
                    and all(token.replace(",", "") in known_numbers for token in operands)):
                line = bare
        lines.append(line)
    return "\n".join(lines)


def prune_rejected_claims(answer: str, rejected: list[str], note: str | None = None,
                          facts: str | None = None) -> str:
    """The answer without the rejected statements, and without bullets or
    list introductions they leave empty. The result must be verified again.
    `note` replaces the default line under a heading the removal emptied.
    With `facts` (the user's figures and the calculator's results), a line
    calculated from a figure only the removed statements gave goes too."""
    pruned = claim_verification.remove_claims(answer, rejected, note=note)
    if facts is not None:
        pruned = claim_verification.without_dependent_figures(pruned, rejected, facts)
    lines = [line for line in pruned.splitlines() if line.strip() not in ("-", "*", "•")]
    return claim_verification.mark_emptied_headings(re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip(), before=answer,
                                                     note=note)


def release_claims(answer: str) -> list[str]:
    """Check qualitative assertions too; headings and code are not claims."""
    return [claim for _, claim in _release_claim_pairs(answer)]


# "Current ratio = 2,50,000 ÷ 1,00,000 = 2.50" is arithmetic on the user's
# own figures, which no source can support; validate_answer_calculations
# re-checks every such line and escalates a wrong one. Requiring a citation
# for it made the model answer nine calculations with "the sources provided
# do not state this".
# A currency code may follow a figure or lead a result ("10,000 GBP × 0.20 =
# 2,000 GBP", "= EUR 11,781.34").
_ARITHMETIC_LINE = re.compile(
    r"[\d)]\s*[%]?\s*(?:[A-Z]{3}\s*)?[+\-−–*/×÷x^]\s*[(₹£$€]?\s*(?:[A-Z]{3}\s*)?[\d(][^=\n]*="
    r"\s*[-−]?\s*[₹£$€]?\s*(?:[A-Z]{3}\s*)?[\d(]"
)
_STATED_FACT = re.compile(r"\b(?:is|are|was|were|applies|apply|must|charged|rate of)\b", re.I)


# Words that bring in a figure from outside the user's facts, or confirm one
# as a fact: "Yes, it is correct: the rate is 6.5%." for "Is the current
# repo rate at 6.5%?" repeats the user's figure but asserts the outside fact.
_OUTSIDE_FACT = re.compile(r"\b(?:average|typical(?:ly)?|benchmark|industry|market|median|normally|usually|"
                           r"current(?:ly)?|still|in\s+force|correct|confirm\w*|yes|today|latest)\b", re.I)


def _user_arithmetic(pairs: list[tuple[str, str]], answer: str, question: str) -> list[str]:
    """Statements that only do arithmetic on the user's own figures, in words
    or as a table row: "Gross profit is £300,000." for revenue £800,000 and
    cost of sales £500,000. No source states such a figure, so strict mode
    removed it as uncited while "= £300,000" was kept (Stage 4, 27 Oct 2026).

    Every figure must be the user's or correct arithmetic from them (the
    figure check, with the user's text as the only evidence), and the
    statement must assert no rate, rule, threshold, standard, obligation or
    accounting treatment. Never exempted merely because some figures are the
    user's: a statement that only repeats them ("Ask the auditor how to treat
    the £120,000") is still a claim. Cited statements are judged as usual."""
    from app.orchestration.calculation_service import validate_answer_calculations
    from app.orchestration.figure_reconciliation import material_figures, unreconciled_figures
    given = {value for _, value in material_figures(question or "")}
    if not pairs or not given:
        return []
    unsupported = set(unreconciled_figures(answer, question, "", question))

    def arithmetic_only(text: str) -> bool:
        figures = [shown for shown, _ in material_figures(text)]
        return bool(figures) and not unsupported.intersection(figures) and not (
            re.search(r"\[REF-\d+\]", text) or _RULE_ASSERTION.search(text) or _PAY_OBLIGATION.search(text)
            or _TREATMENT_CONTENT.search(text) or _FRAMEWORK_REFERENCE.search(text) or _OUTSIDE_FACT.search(text)
            or validate_answer_calculations(text))

    def computes(text: str) -> bool:
        return any(value not in given for _, value in material_figures(text))

    candidates = [original for original, _ in pairs if arithmetic_only(original)]
    # A worked table's rows restating the user's inputs stand with its result row.
    tables_computing = {_table_of(answer, row) for row in candidates if row.startswith("|") and computes(row)}
    return [original for original in candidates
            if computes(original) or (original.startswith("|") and _table_of(answer, original) in tables_computing)]


def _table_of(answer: str, row: str) -> int:
    """The line number where the table holding `row` starts, or -1."""
    lines = answer.splitlines()
    at = next((index for index, line in enumerate(lines) if line.strip() == row.strip()), None)
    if at is None:
        return -1
    while at > 0 and lines[at - 1].lstrip().startswith("|"):
        at -= 1
    return at


def _is_pure_arithmetic(piece: str) -> bool:
    """A label and an equation only. "The standard rate is 20%, so VAT =
    £1,000 × 20% = £200" also asserts a rate, so it still needs a source."""
    return bool(_ARITHMETIC_LINE.search(piece)) and not _STATED_FACT.search(piece.split("=", 1)[0])


_BOLD_ONLY = re.compile(r"(\*\*|__)[^*_]+\1")
_GAP_STATEMENT = re.compile(
    r"\b(?:sources?|evidence|guidance|documents?)\b[^.]*?\b(?:do(?:es)?\s+not|don['’]t|doesn['’]t)\s+"
    r"(?:state|specify|cover|include|give|provide|mention|say|address|confirm|establish|contain|list|show|detail|explain|resolve|demonstrate)\b"
    r"|\bnot\s+(?:stated|covered|specified|given|available|provided|included|found)\s+in\s+the\s+(?:provided\s+|cited\s+|retrieved\s+)?"
    r"(?:sources?|evidence)\b"
    # "The sources provided do not contain information on India's GST
    # threshold" was rejected as an uncited claim and the answer escalated.
    r"|\b(?:sources?|evidence)\b[^.]*?\b(?:has|have|contains?)\s+no\s+(?:information|figure|data|details?)\b",
    re.I,
)
# Anything a gap statement could smuggle a fact in with.
_SPECIFIC_VALUE = re.compile(r"\d|[£$€₹%]|\blakh\b|\bcrore\b|\bmillion\b", re.I)


def is_evidence_gap_statement(text: str) -> bool:
    """"The sources provided do not state this." asserts only that evidence
    is missing, which the prompt asks for. Uncited, it was pruned as a claim,
    so a question the sources could not answer vanished from the answer
    instead of being acknowledged. Only a statement with no figure, rate or
    amount qualifies, so it cannot carry an unsourced fact."""
    return bool(_GAP_STATEMENT.search(text)) and not _SPECIFIC_VALUE.search(text)


# "To answer this question you would need to consult an organisation's
# accounting policies…" after a gap statement points elsewhere; it states
# nothing, so the answer is still only a gap (QA case E02).
_REFERRAL = re.compile(
    r"^(?:to answer (?:this|the) question,?\s+)?(?:you\s+(?:would|will|may|might)\s+(?:need|have)\s+to|please)\s+"
    r"(?:consult|refer\s+to|check|review|see)\b",
    re.I,
)


def is_referral(text: str) -> bool:
    return bool(_REFERRAL.search(text.strip())) and not _SPECIFIC_VALUE.search(text)


_VISUAL_POINTER = re.compile(
    r"^(?:the|this|a)\s+(?:\w+\s+){0,3}(?:chart|graph|plot|table|diagram|flowchart|visual(?:isation|ization)?)\b"
    r"[^.]*\b(?:below|above|attached|following)\b", re.I,
)


def _is_visual_pointer(piece: str) -> bool:
    """"The chart below visualises the converted amounts." points at the
    rendered chart and states no fact; checked as a claim it failed the
    release check and the rewrite discarded a correct answer. A pointer that
    carries a figure is still checked."""
    return bool(_VISUAL_POINTER.search(piece.strip())) and not _SPECIFIC_VALUE.search(piece)


def _row_label_refs(row: str, lines: list[str]) -> str:
    """A comparison table often restates figures cited just above it
    ("Australia – 10% [REF-7]" then "| Australia | 10% | 100 | 1,100 |").
    Checked without a citation every row was removed, leaving an empty table;
    the row is checked against the references of the cited lines that name
    its label instead."""
    cells = [cell.strip(" *_") for cell in row.strip().strip("|").split("|")]
    label = cells[0] if cells else ""
    if len(label) < 3 or not re.search(r"[A-Za-z]", label):
        return ""
    refs: list[str] = []
    from app.orchestration.source_taxonomy import detect_jurisdictions
    countries = detect_jurisdictions(label, infer_from_tax_terms=False)
    in_fence = False
    for other in lines:
        if other.strip().startswith("```"):
            in_fence = not in_fence
            continue
        same_country = len(countries) == 1 and countries[0] in detect_jurisdictions(other, infer_from_tax_terms=False)
        if in_fence or other.strip().startswith("|") or not (label.lower() in other.lower() or same_country):
            continue
        refs += re.findall(r"\[REF-\d+\]", other)
    return " ".join(dict.fromkeys(refs))


# An open question or a research step is not a statement of fact: "Whether the
# UK thresholds … applied in the Isle of Man …", "To establish the exact
# threshold, an authoritative Manx source is required", "Until such a source
# is located, the UK figures should be reported only as UK thresholds" were
# removed as uncited claims (qry-6b7bd952fa31). Kept narrow: "Revenue should
# be treated as deferred income" is still a claim.
_NON_ASSERTION = re.compile(
    r"^(?:whether\b|to (?:establish|confirm|determine|verify)\b|until\b)|\bshould be reported only as\b|\?\s*$",
    re.I)
_SYSTEM_NOTICES = ("The answer included figures that could not be matched to verified data",
                   "Here is the verified working:", "The full written answer could not be completed",
                   "Explanations and recommendations were not completed", "**Calculations from the figures provided**",
                   "**Retrieved data (sourced)**", claim_verification.FIGURES_REMOVED_NOTE,
                   claim_verification.FIGURE_MISATTRIBUTED_NOTE, "Not charted:")


def _release_claim_pairs(answer: str) -> list[tuple[str, str]]:
    """(verbatim text, text as checked) for every claim. A sentence without
    its own citation is checked against its paragraph's references."""
    pairs: list[tuple[str, str]] = []
    in_fence = False
    heading = ""
    lines = answer.splitlines()
    for index, line in enumerate(lines):
        line = line.strip()
        if _BOLD_ONLY.fullmatch(line) or line.startswith("#"):
            heading = line.strip("#*_ ").strip()
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not line or line.startswith("#") or re.fullmatch(r"[|:\-\s]+", line):
            continue
        if line.startswith("|") and index + 1 < len(lines) and re.fullmatch(r"[|:\-\s]+", lines[index + 1]):
            continue
        # Kriton's own withheld notice and the heading of its verified working
        # are system statements, not claims: rejected as uncited, they turned
        # a withheld answer with verified working into "no answer"
        # (qry-f7c7ad8f72ff).
        if line.startswith(_SYSTEM_NOTICES):
            continue
        # "For the Annual Accounting Scheme the deadlines differ:" introduces
        # the cited list below it; the list items are the claims. A bold-only
        # line ("**UK VAT registration threshold**") or a restated question
        # ("Is the VAT threshold £85,000?") is a heading: pruning them as
        # uncited claims left bare "****" lines in a multi-question answer.
        if not re.search(r"\[REF-\d+\]", line) and (
            line.endswith(":") or line.endswith("?") or _BOLD_ONLY.fullmatch(line)
        ):
            continue
        paragraph_refs = " ".join(dict.fromkeys(re.findall(r"\[REF-\d+\]", line)))
        if line.startswith("|") and not paragraph_refs:
            paragraph_refs = _row_label_refs(line, lines)
        in_illustration = is_illustration_heading(heading)
        for piece in ([line] if line.startswith("|") else claim_verification.sentences(line)):
            piece = claim_verification.without_leading_heading(piece.strip()).strip(" -*•")
            if (is_evidence_gap_statement(piece) or _is_pure_arithmetic(piece) or _is_visual_pointer(piece)
                    or _NON_ASSERTION.search(piece)):
                continue
            # The hypothetical entity and amounts of a labelled example are not
            # claims; a sentence there stating a rule still is.
            if in_illustration and is_scenario_sentence(piece):
                continue
            inline_heading = claim_verification._LEADING_HEADING.match(line)
            context = inline_heading.group(1).strip("*_ ") if inline_heading else heading
            # A bare figure under a heading ("30 % [REF-1]" beneath "UK
            # corporation tax rate for £300,000 profit") is a claim too: at
            # under 15 characters it was never checked, and the ring-fence
            # 30% rate was shown as an ordinary company's rate.
            short_figure = len(piece) < 15 and _SPECIFIC_VALUE.search(piece)
            if (len(piece) >= 15 or short_figure) and piece not in (original for original, _ in pairs):
                # Long assertions are also checked, rather than silently skipped.
                checked = piece
                if paragraph_refs and not re.search(r"\[REF-\d+\]", piece):
                    checked += " " + paragraph_refs
                if context and (short_figure or inline_heading):
                    # The heading says what the figure answers.
                    checked = f"{context}: {checked}"
                pairs.append((piece, checked))
    return pairs


# Naming the framework a supplied scenario is to be worked under is not a
# request for the framework's text: "classify this lease under US GAAP (ASC
# 842)" with the lease terms given. Read as a lookup, every sentence needed a
# citation, the library holds no ASC passages, and seven of ten scenario
# questions on 22 Oct 2026 came back "the sources do not establish this".
_FRAMEWORK_REFERENCE = re.compile(
    r"\b(?:US\s+GAAP|UK\s+GAAP|GAAP|IFRS(?:\s?\d+)?|IAS\s?\d+|Ind\s?AS(?:\s?\d+)?|ASC\s?\d+(?:-\d+)*|"
    r"AU-?C\s?\d+|ISA\s?\d+|FRS\s?\d+|AICPA|PCAOB|FASB|IASB|"
    r"(?:accounting|auditing|financial\s+reporting)\s+standards?|standards?)\b",
    re.I,
)
# Statistical and contractual limits are not statutory limits.
_ANALYTICAL_LIMIT = re.compile(
    r"\b(?:upper|lower|tolerable|misstatement|error|precision|materiality|credit|overdraft|confidence|"
    r"borrowing|spending)\s+(?:misstatement\s+)?limits?\b", re.I,
)
# Asking what the authority itself says still needs the authority.
_ABOUT_THE_AUTHORITY = re.compile(
    r"\bwhat\s+(?:does|do|did)\b[^?]{0,80}\b(?:say|says|require|requires|state|states|permit|permits)\b"
    r"|\b(?:summari[sz]e|quote|cite|paragraph|para\.?)\b", re.I,
)
_SUPPLIED_RATE = re.compile(
    r"\b(?:tax|vat|gst|rate)\b[^.%\n]{0,40}?\d+(?:\.\d+)?\s?%|\d+(?:\.\d+)?\s?%\s*(?:tax|vat|gst|rate)\b", re.I,
)
_APPLIED_GUIDANCE = re.compile(
    r"\b(?:rules?|requirements?|guidance|principles?|methods?|methodology|frameworks?|approach)\b", re.I)
_TAX_WORDS = re.compile(r"\b(?:tax(?:es|ation|able)?|vat|gst|pre-tax)\b", re.I)
# Only with its own stated amount: "determine the net deferred tax asset"
# with no tax rate given still needs a source for the rate.
_TAX_LINE_ITEM = re.compile(
    r"\b(?:(?:income|sales|deferred|payroll|current|corporate)\s+)?tax(?:es)?\s+"
    r"(?:payable|receivable|expense|liabilit(?:y|ies)|assets?|provision|paid|refundable|benefit)\b"
    r"(?=[^.\n;]{0,40}?(?:[£$€₹]\s?\d|\b\d{1,3}(?:,\d{2,3})+\b))", re.I)
_AUDIT_OPINION = re.compile(r"\baudit\s+opinion\b", re.I)
_SCENARIO_FIGURE = re.compile(r"[£$€₹]\s?\d|\b\d[\d,]*(?:\.\d+)?\s?%|\b\d{1,3}(?:,\d{2,3})+\b")


def applies_to_supplied_facts(question: str, context: str) -> bool:
    """The authority terms in the question only name the framework a supplied
    scenario is worked under, or a tax the user gave the rate for."""
    from app.orchestration.calculation_service import verifies_current_fact
    # Confirming that a quoted rate is still current needs a current source,
    # however many figures the scenario supplies (review R1).
    if (_ABOUT_THE_AUTHORITY.search(question) or verifies_current_fact(question)
            or len(_SCENARIO_FIGURE.findall(context or "")) < 2):
        return False
    from app.orchestration.calculation_service import _ACCOUNTING_CURRENT
    # Line items first: removing "tax" below left "Current Income Payable",
    # which then read as a request for a current rate (22 Oct 2026).
    residual = _ANALYTICAL_LIMIT.sub(" ", _FRAMEWORK_REFERENCE.sub(" ", _ACCOUNTING_CURRENT.sub(" ", question)))
    if _FRAMEWORK_REFERENCE.search(question):
        # "applying US GAAP Lower of Cost or NRV rules" to the supplied
        # inventory: the framework's rules are what is being applied.
        residual = _APPLIED_GUIDANCE.sub(" ", residual)
    if _SUPPLIED_RATE.search(context):
        residual = _TAX_WORDS.sub(" ", residual)
    # A balance-sheet or income-statement line, not a tax rule: "Income Tax
    # Payable decreased by $12,000" made a cash-flow reconciliation strictly
    # sourced, and its correct steps were pruned as uncited (23 Oct 2026).
    residual = _TAX_LINE_ITEM.sub(" ", residual)
    if supplies_a_professional_scenario(context):
        # The opinion consequence of the scenario's own misstatements is
        # applying auditing standards to supplied facts: a materiality
        # question was answered with gap tags and no opinion (23 Oct 2026).
        residual = _AUDIT_OPINION.sub(" ", residual)
    return not _authority_terms(residual)


_REF = re.compile(r"\[REF-\d+\]")
_PROSE_HEADING = re.compile(r"^\s*(?:#{1,6}\s|(?:\*\*|__)[^*_]+(?:\*\*|__):?\s*$)")


_TABLE_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)*\|?\s*$")
_LIST_MARKER = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
# A lead-in ("Key points:", "Journal entry on 1 January:") introduces content;
# it states nothing itself.
_LEAD_IN = re.compile(r"^[^.!?]{1,80}:\s*$")
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")
# Short statements that point elsewhere or answer nothing themselves.
_NON_CLAIM = re.compile(
    r"^\W*(?:see|refer\s+to|as)\s+(?:above|below|note|table)|^\W*(?:not\s+applicable|n/?a|none|continued|"
    r"to\s+be\s+confirmed|tbc|yes|no)\W*$", re.I)
# The last word of a two-word sentence that makes it an assertion: a past
# tense ("Rates increased.") or a verb from this list ("Titan qualifies.").
# A suffix guess could not tell "qualifies" from "entries" or "points".
_SHORT_CLAIM_VERBS = frozenset(
    "rose fell grew rise rises fall falls grow grows apply applies exist exists hold holds held paid sold "
    "lost won met is are was were has have had does do did remain remains stand stands stood "
    "qualify qualifies consolidate consolidates control controls own owns exceed exceeds meet meets fail fails "
    "pass passes increase increases decrease decreases vary varies depend depends matter matters "
    "recognise recognises recognize recognizes capitalise capitalises capitalize capitalizes "
    "accrue accrues lapse lapses mature matures default defaults".split())


def _is_short_claim(statement: str, words: list[str]) -> bool:
    """A complete assertion under three words: "Rates increased.", "Revenue
    rose." — not a pointer ("See above.") or a label ("Journal entries.")."""
    if len(words) != 2 or _NON_CLAIM.search(statement) or not re.search(r"[.!]\s*$", statement):
        return False
    last = words[-1].lower()
    return last.endswith("ed") or last in _SHORT_CLAIM_VERBS


def uncited_explanations(text: str) -> list[str]:
    """Claims without a [REF-N] marker: each sentence and each table body row.
    Not headings, lead-ins, table header rows, removal notes or calculations on
    the user's figures (checked by the calculation checks, not by a source).
    A short claim counts ("Titan consolidates Silo." — the final review found
    a six-word minimum let it through), two-word ones too ("Rates
    increased."); pointers and labels ("See above.", "Journal entries.") and
    one-word replies do not."""
    from app.orchestration.calculation_service import shows_arithmetic
    from app.orchestration.claim_verification import is_removal_note
    lines = (text or "").splitlines()
    statements: list[str] = []
    in_fence = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not stripped or _PROSE_HEADING.match(stripped) or _LEAD_IN.match(stripped):
            continue
        if stripped.startswith("|"):
            following = lines[index + 1].strip() if index + 1 < len(lines) else ""
            if not _TABLE_SEPARATOR.match(stripped) and not _TABLE_SEPARATOR.match(following):
                statements.append(stripped)
            continue
        statements += _SENTENCE_BREAK.split(_LIST_MARKER.sub("", stripped))
    found = []
    for statement in statements:
        words = re.findall(r"[A-Za-z]{2,}", statement)
        if ((len(words) < 3 and not _is_short_claim(statement, words)) or _REF.search(statement)
                or is_removal_note(statement)
                or shows_arithmetic(statement) or _LEAD_IN.match(statement)):
            continue
        found.append(statement)
    return found


# An accounting or audit task on facts the question supplies, with no named
# standard: "the following items are noticed at the inventory count …
# determine whether each lot is included … draft the adjusting entry" was
# forced to answer from searches that returned nothing (23 Oct 2026).
_PROFESSIONAL_TASK = re.compile(
    r"\b(?:journal\s+entr(?:y|ies)|adjusting\s+entr(?:y|ies)|classify|recogni[sz]e|measure|include[sd]?|"
    r"exclude[sd]?|present(?:ed|ation)?|disclos\w*|audit\w*|auditor|misstatement|inventory|receivables?|"
    r"provision|liabilit(?:y|ies)|revenue|lease|impair\w*|consolidat\w*|hedge|derivative|pension|"
    r"segment|restructur\w*|deferred\s+tax|depreciat\w*|amorti[sz]\w*|fair\s+value)\b", re.I)


def supplies_a_professional_scenario(question: str) -> bool:
    """The question sets out its own facts (two or more figures) and asks for
    an accounting or audit treatment of them."""
    return len(_SCENARIO_FIGURE.findall(question or "")) >= 2 and bool(_PROFESSIONAL_TASK.search(question or ""))


def names_an_authority(question: str) -> bool:
    """The wording calls for an authority or names a framework: a standard,
    rule, US GAAP, PCAOB, ASC 810."""
    return _authority_terms(question) or bool(_FRAMEWORK_REFERENCE.search(question or ""))


def requires_authoritative_evidence(question: str, context: str = "") -> bool:
    """Every claim must be cited from governed or official sources. With the
    supplied scenario as context, applying a named framework to the user's own
    facts is a professional explanation instead: it may use professional
    knowledge, labelled as not source-verified."""
    from app.orchestration.derived_output import is_derived_output_request
    head, separator, subject = (question or "").partition(" Context: ")
    if separator and subject.strip() and is_derived_output_request(head):
        # A follow-up chip ("Explain this with a grounded example. Context:
        # what is tax") is held to its subject's standard, not to the word
        # "tax" in it: strictly sourced, a general example lost "corporate tax
        # is levied on profit" and a cited comparison table (24 Oct 2026). A
        # subject that needs sources (a rate, a threshold) still does.
        return requires_authoritative_evidence(subject.strip(), context)
    if not _authority_terms(question):
        return False
    return not (context and applies_to_supplied_facts(question, context))


_TAX_EXCLUDED = re.compile(
    r"\b(?:assum\w*\s+|with\s+)?(?:no|without|ignor\w*|exclud\w*|ex\.?|net\s+of|before)\s+(?:any\s+)?"
    r"(?:vat|gst|sales\s+tax|tax(?:es)?)\b",
    re.I,
)


def _authority_terms(question: str) -> bool:
    """Whether the wording calls for an authority (GitHub main's definition
    leniency, verbatim); the context exemption is applied by the caller."""
    # Tax ruled out is not a tax question: "the journal entry for a $12,000
    # invoice …, assuming no tax" was held to official tax sources and a
    # correct Dr Receivable / Cr Revenue was withheld (QA case A03).
    text = _TAX_EXCLUDED.sub(" ", question or "")
    lowered = text.lower()
    # Pure definitions of terms ("what is X", "define X") need not be forced
    # into the strict citation regime that can trigger an evidence-gap answer.
    # However, explanations of standards/rules that are regulatory ("explain IFRS 16")
    # must remain authoritative per existing tests.
    if re.match(r"^\s*explain\b", text, re.I):
        if re.search(r"\b(?:ifrs|gaap|ias|frs|uk gaap|us gaap|ind as)\b", lowered) or re.search(r"\b(?:vat|gst|tax|hmrc|regulation|law|act|compliance|deadline|rate|penalt)\b", lowered):
            pass  # fall through to strict checks
        elif re.search(r"\b(?:rate|rates|threshold|thresholds|slab|slabs|due date|deadline|penalt(?:y|ies)|exemption|refund|percentage|%\b)\b", lowered):
            pass
        else:
            # Generic "explain X" (not regulatory) could be definition-like; but test expects "Explain IFRS 16" to require authority
            pass  # continue to checks below
    if re.match(r"^\s*(?:what is|what'?s|define|meaning of|describe|tell me (?:about|what))\b", text, re.I):
        if re.search(r"\b(?:rate|rates|threshold|thresholds|slab|slabs|due date|deadline|penalt(?:y|ies)|exemption|refund|registration threshold|turnover|percentage|%\b)\b", text, re.I):
            pass
        elif re.search(r"\b(?:ifrs|gaap|ias|frs|uk gaap|us gaap|ind as)\b", lowered):
            pass  # regulatory standards still require authority
        else:
            return False
    if re.match(r"^\s*explain(?: in simple terms)?\b", text, re.I) and re.search(r"\b(?:ifrs|gaap|ias|frs|uk gaap|us gaap|ind as)\b", lowered):
        pass  # require authority
    elif re.match(r"^\s*explain(?: in simple terms)?\b", text, re.I) and not re.search(r"\b(?:rate|rates|threshold|deadline|penalt|compliance|filing|return|law|act|regulation)\b", lowered):
        # Pure explanatory non-regulatory could be treated as definition-like only if not matching other rules
        # but safer to let other rules decide; don't force False here
        pass
    return needs_lookup(text) or bool(re.search(
        r"\b(?:vat|gst|tax|taxation|hmrc|cbic|filing|statutory|legislation|regulation|"
        # "Due date for GSTR-3B" was answered unsourced, adding a wrong
        # "nil returns are due on the 10th".
        r"compliance|legal|deadline|refund|cash accounting|flat rate|audit opinion|"
        r"due dates?|late fees?|penalt(?:y|ies)|gstr-?\w*|tds|tcs|"
        # Statutory payroll: PF/ESI were computed from memory with a wrong
        # ESI wage ceiling (₹10,000; it is ₹21,000) and no citation.
        r"pf|epf|esi|esic|provident fund|gratuity|national insurance|nic|paye|social security|"
        r"medicare|fica|minimum wage|living wage|sick pay|maternity pay|employment allowance|"
        r"withholding)\b", text, re.I,
    ))


@dataclass
class ReleaseDecision:
    escalate: bool
    text: str
    note: str | None = None


def decide_release_failure(answer: str, check: AnswerVerification, *, risk_level: str,
                           validation_passed: bool) -> ReleaseDecision:
    """Only independently reverified prose may survive a failed check.

    The caller already attempts correction and reverified pruning. Remaining
    failures become an evidence gap; a verifier outage cannot release claims.
    Existing safety and high-risk escalation policies remain in force.
    """
    if risk_level == "HIGH" or not validation_passed:
        return ReleaseDecision(escalate=True, text=answer)
    return ReleaseDecision(
        escalate=False, text="The sources provided do not establish an answer to this.",
        note="I could not verify an answer against the available evidence. Please try again.",
    )


# ── Evidence validation (reliability plan phase 4, 24 Oct 2026) ──────────────
# verify_for_release judges claims against their cited evidence, but only for
# answers that need authoritative sourcing, and through a model. These checks
# are deterministic and run on every released answer: a citation's presence
# is not proof, so a figure must be in the very source cited for it, and the
# source must be in force for the period, of the jurisdiction asked about,
# not withdrawn, not contradicted by another cited source, and of a kind that
# can state the rule. Findings are disclosed and audited; nothing is invented
# or rewritten to look supported.

@dataclass(frozen=True)
class EvidenceFinding:
    code: str
    statement: str
    refs: tuple[str, ...]
    message: str


EVIDENCE_FINDING_CODES = ("figure_not_in_cited_source", "jurisdiction_mismatch", "outside_effective_period",
                          "withdrawn_source", "conflicting_sources", "no_authoritative_source")
# The cited evidence does not bear the statement out: the answer is not
# presented as fully source-grounded, and a reviewer should check it.
UNSUPPORTED_FINDING_CODES = {"figure_not_in_cited_source", "jurisdiction_mismatch", "outside_effective_period",
                             "withdrawn_source", "conflicting_sources"}
# Every finding asks for review; a web or professional-body source is a
# question of authority for the rule's jurisdiction, not proof the statement
# is wrong, so it is a source-authority review that leaves the status alone.
REVIEW_FINDING_CODES = UNSUPPORTED_FINDING_CODES | {"no_authoritative_source"}
EVIDENCE_NOTE_PREFIX = "Evidence check"
AUTHORITY_NOTE_PREFIX = "Source-authority review"

_WITHDRAWN = re.compile(
    r"\bthis (?:guidance|page|publication|notice|manual|form|document|collection) (?:was|has been) "
    r"(?:withdrawn|archived|replaced|superseded)\b|\bwithdrawn on \d|\bno longer (?:applies|in force|valid|current)\b"
    r"|\bhas been (?:superseded|repealed|revoked)\b|\bwas repealed\b", re.I)
_RULE_CLAIM = re.compile(
    r"%|[£$€₹]\s?\d|\b(?:rate|threshold|limit|allowance|deadline|due\s+date|must|shall|required|requires|mandatory|"
    r"penalt\w*|exempt\w*|zero[- ]rated|(?:IFRS|IAS|ASC|FRS|Ind\s?AS)\s?\d+)\b", re.I)
_HISTORY = re.compile(r"\b(?:from|until|before|after|since|previously|formerly|was|were|prior|between|"
                      r"19\d{2}|20\d{2})\b", re.I)
_KEY_STOP = {"the", "a", "an", "is", "are", "was", "of", "at", "to", "for", "be", "by", "on", "in", "and", "its",
             "it", "this", "that", "currently", "now", "set", "charged", "applies", "apply", "per", "with"}
_GOVERNING = {"official", "internal", "document", "data"}


def _figure_key(statement: str, shown: str) -> str:
    """The two content words before a figure — "standard rate" in "the
    standard rate of VAT is 20%" — or "" when there are not two."""
    before = statement[:statement.find(shown)] if shown in statement else ""
    words = [w for w in re.findall(r"[a-z]+", before.lower()) if w not in _KEY_STOP and w not in ("vat", "gst")]
    return " ".join(words[-2:]) if len(words) >= 2 else ""


def _kind(shown: str) -> str:
    from app.orchestration.figure_reconciliation import _is_percentage
    return "percent" if _is_percentage(shown) else "amount"


def _rule_figures(statement: str) -> list[tuple[str, float, float, float]]:
    """(as written, value, amount, tolerance) for each rate or money figure."""
    from app.orchestration.figure_reconciliation import _amount, _scaled_tolerance, material_figures
    figures = []
    for shown, value in material_figures(statement):
        if _kind(shown) == "percent" or re.search(r"[£$€₹]", shown):
            figures.append((shown, value, _amount(shown, value), _scaled_tolerance(shown, value)))
    return figures


def _states(text: str, shown: str, amount: float, tolerance: float) -> bool:
    from app.orchestration.figure_reconciliation import _direct_values, _percent_values, is_known
    pool = _percent_values(text, "") if _kind(shown) == "percent" else _direct_values(text, "")
    return is_known(amount, pool, tolerance)


def _source_disagrees(text: str, key: str, shown: str, amount: float, tolerance: float) -> bool:
    """A source sentence on the same figure (same two key words, same kind)
    that states another value and not this one, outside a dated history."""
    for sentence in re.split(r"(?<=[.!?])\s+|\n", text or ""):
        lowered = sentence.lower()
        if not key or not all(word in lowered for word in key.split()) or _HISTORY.search(sentence):
            continue
        same_kind = [(s, a, t) for s, _, a, t in _rule_figures(sentence) if _kind(s) == _kind(shown)]
        if same_kind and not any(abs(a - amount) <= max(t, tolerance) for _, a, t in same_kind):
            return True
    return False


def _period(question: str):
    from datetime import date
    years = [int(y) for y in re.findall(r"\b(19\d{2}|20\d{2})\b", question or "")]
    if years and not re.search(r"\b(?:current|today|now|latest)\b", question or "", re.I):
        return date(min(years), 1, 1), date(max(years), 12, 31)
    today = date.today()
    return today, today


def evidence_findings(answer: str, *, question: str, evidence_by_ref: dict[str, str], citations: list,
                      facts: str = "", derived: list[float] = (),
                      conflict_version_ids: list[str] = ()) -> list[EvidenceFinding]:
    """What the cited evidence does not bear out, statement by statement.

    `citations` are the answer's SourceCitations (their authority,
    jurisdiction and dates); `evidence_by_ref` the full text behind each
    reference; `facts` the user's own figures and `derived` calculator results,
    which no source needs to state. An illustrative example's scenario lines
    state no rule and are not checked."""
    from app.orchestration.derived_output import scenario_text
    from app.orchestration.figure_reconciliation import _direct_values, is_known
    from app.orchestration.source_taxonomy import (
        ACCOUNTING, AUDIT, PAYROLL, TAX, detect_jurisdictions, detect_topics, jurisdiction_label,
    )
    meta = {citation.ref_id: citation for citation in citations or []}
    scenario = {line.strip() for line in scenario_text(answer).splitlines() if line.strip()}
    known = _direct_values(facts, "") + list(derived)
    question_jurisdictions = detect_jurisdictions(question)
    start, end = _period(question)
    conflicts = set(conflict_version_ids or ())
    findings: list[EvidenceFinding] = []
    stated: dict[tuple[str, str], list[tuple[float, float, tuple[str, ...], str]]] = {}

    def add(code, statement, refs, message):
        findings.append(EvidenceFinding(code, statement, tuple(refs), message))

    for original, _ in _release_claim_pairs(answer):
        if any(original in line for line in scenario):
            continue
        refs = tuple(ref for ref in dict.fromkeys(re.findall(r"\[(REF-\d+)\]", original)) if ref in evidence_by_ref)
        if not refs:
            continue
        sources = [meta.get(ref) for ref in refs]
        withdrawn = [ref for ref in refs if _WITHDRAWN.search(evidence_by_ref[ref])]
        if withdrawn:
            add("withdrawn_source", original, withdrawn,
                "a cited source says it has been withdrawn or superseded, so it may no longer apply")
        stale = [ref for ref, source in zip(refs, sources)
                 if source and ((source.effective_to and source.effective_to < start)
                                or (source.effective_from and source.effective_from > end))]
        if stale:
            period = f"{start.year}" if start.year == end.year else f"{start.year}–{end.year}"
            add("outside_effective_period", original, stale,
                f"a cited source version was not in force for the period asked about ({period})")
        if any(source and source.source_version_id in conflicts for source in sources):
            add("conflicting_sources", original, refs,
                "a cited source is registered as conflicting with another source used for this answer")
        jurisdictions = {ref: source.jurisdiction for ref, source in zip(refs, sources) if source and source.jurisdiction}
        mismatch = _jurisdiction_mismatch(original, set(refs), question_jurisdictions=question_jurisdictions,
                                          source_jurisdictions=jurisdictions, evidence_by_ref=evidence_by_ref)
        if mismatch and len(jurisdictions) == len(refs):
            add("jurisdiction_mismatch", original, refs,
                f"a source for {jurisdiction_label(mismatch)} is cited for a statement about "
                f"{', '.join(jurisdiction_label(j) for j in question_jurisdictions)}")
        if (_RULE_CLAIM.search(original) and detect_topics(original) & {TAX, ACCOUNTING, AUDIT, PAYROLL}
                and all(source and source.authority and source.authority not in _GOVERNING for source in sources)):
            where = question_jurisdictions or detect_jurisdictions(original)
            add("no_authoritative_source", original, refs,
                f"a {' / '.join(jurisdiction_label(j) for j in where) + ' ' if where else ''}tax or accounting rule "
                f"is supported only by {' and '.join(sorted({s.authority for s in sources}))} sources, not by the "
                "official guidance or standard")
        if re.search(r"[=×÷]", original) or all(source and source.authority == "document" for source in sources):
            continue
        cited_text = " ".join(evidence_by_ref[ref] for ref in refs)
        for shown, _, amount, tolerance in _rule_figures(original):
            if is_known(amount, known, tolerance):
                continue
            key = _figure_key(original, shown)
            if key and not _HISTORY.search(original):
                stated.setdefault((key, _kind(shown)), []).append((amount, tolerance, refs, original))
            if not _states(cited_text, shown, amount, tolerance):
                elsewhere = any(_states(text, shown, amount, tolerance)
                                for ref, text in evidence_by_ref.items() if ref not in refs)
                add("figure_not_in_cited_source", original, refs,
                    f"{shown.strip()} is not stated in the source cited for it"
                    + (" (another retrieved source states it)" if elsewhere else ""))
                continue
            disagreeing = [ref for ref in refs if not _states(evidence_by_ref[ref], shown, amount, tolerance)
                           and _source_disagrees(evidence_by_ref[ref], key, shown, amount, tolerance)]
            if disagreeing:
                add("conflicting_sources", original, refs,
                    f"the cited sources disagree on the {key}: {', '.join(disagreeing)} states a different figure "
                    f"from {shown.strip()}")
    # The answer itself gives one figure two values from different sources.
    for (key, _), values in stated.items():
        distinct = []
        for amount, tolerance, refs, statement in values:
            if not any(abs(amount - other) <= max(tolerance, t) for other, t, _, _ in distinct):
                distinct.append((amount, tolerance, refs, statement))
        if len(distinct) > 1 and len({refs for _, _, refs, _ in distinct}) > 1:
            add("conflicting_sources", distinct[1][3], tuple(ref for *_, refs, _ in distinct for ref in refs),
                f"the answer gives the {key} as different figures from different sources")
    unique: dict[tuple[str, str], EvidenceFinding] = {}
    for finding in findings:
        unique.setdefault((finding.code, finding.statement), finding)
    return list(unique.values())


def evidence_notes(findings: list[EvidenceFinding]) -> list[str]:
    """The limitations shown with the answer: what its evidence does not
    support, to be reviewed before it is relied on, and apart from it the
    rules whose source should be checked for authority."""
    unsupported = [f.message for f in findings if f.code in UNSUPPORTED_FINDING_CODES]
    authority = [f.message for f in findings if f.code == "no_authoritative_source"]
    notes = []
    if unsupported:
        notes.append(f"{EVIDENCE_NOTE_PREFIX}: " + "; ".join(dict.fromkeys(unsupported))
                     + ". Have these statements reviewed before relying on them.")
    if authority:
        notes.append(f"{AUTHORITY_NOTE_PREFIX}: " + "; ".join(dict.fromkeys(authority))
                     + ". Check the rule against the official source for its jurisdiction.")
    return notes


# ── What was verified, kept apart (reliability brief, 24 Oct 2026) ───────────
# "Answered — calculated and verified" was shown for any engine calculation and
# "source grounded" for any answer with one citation, so arithmetic or a
# single source read as proof of the whole answer. Each part is now judged on
# its own, from the findings and notes the pipeline already produced.

# A note that the result rests on something not confirmed.
ASSUMPTION_MARKERS = re.compile(r"\bassumes?\b|\bdoes not (?:confirm|establish)\b|\bnames no country\b", re.I)
_PARTLY_SOURCED = ("Partly source-verified", "Statements the cited sources do not support", "could not be confirmed",
                   "General explanation", "Incomplete answer")


# A claim of accounting or tax treatment, not a word that also appears in
# arithmetic: "credit terms", "provision of services" and "deferred payment"
# state no treatment, while "the reverse charge applies" and "revenue
# recognition" do (32 reviewed sentences, 25 Oct 2026).
_ACCOUNT = (r"(?:revenue|income|sales|assets?|liabilit\w*|expenses?|costs?|gains?|losses?|leases?|receivables?|"
            r"payables?|equity|inventory|cash|bank|reserves?|right-of-use|goodwill|provisions?|accruals?)")
_TREATMENT_CONTENT = re.compile("|".join([
    # An entry: a debit side and a credit side ("Dr. Smith" is a title), or the words.
    r"\b(?:Dr|Debit)\b(?!\.\s*[A-Z][a-z]+\b(?!\s+" + _ACCOUNT + r"))[\s\S]{0,160}?\b(?:Cr|Credit)\b",
    r"\bjournal\s+entr(?:y|ies)\b|\b(?:debit|credit)\s+(?:the\s+)?[A-Z]?[a-z\-]+\s+(?:account|" + _ACCOUNT + r")\b",
    r"\b(?:IFRS|IAS|ASC\s?\d|US\s+GAAP|FRS\s?\d|Ind\s?AS)\b",
    r"\brecogni[sz](?:e|es|ed|ing)\b[^.\n;]{0,30}\b" + _ACCOUNT,
    r"\brecognition\s+of\s+(?:the\s+|an?\s+)?(?:[\w-]+\s+)?" + _ACCOUNT,
    r"\b" + _ACCOUNT + r"\s+recogni(?:[sz]ed|tion)\b",
    r"\b(?:capitali[sz]\w*|amorti[sz]\w*|depreciat\w*|impair\w*|reclassif\w*)\b",
    r"\b(?:accrual|accrued\s+" + _ACCOUNT + r")\b",
    r"\bdeferred\s+(?:revenue|income|tax|consideration)\b|\bdefer(?:s|red|ring)?\s+(?:the\s+)?(?:revenue|income|recognition)\b",
    r"\b(?:make|recogni[sz]e|create|book|record)\s+a\s+provision\b|\bprovisions?\s+for\b",
    # Tax treatment: entitlement to input tax, and the status of a supply.
    r"\b(?:claim|eligible|entitled|cannot|can\s?not|blocked|reverse|recover\w*)\b[^.\n]{0,60}"
    r"\b(?:input\s+tax\s+credit|ITC|input\s+(?:VAT|tax|GST))\b",
    r"\b(?:input\s+tax\s+credit|ITC|input\s+(?:VAT|tax|GST))\b[^.\n]{0,40}\b(?:claim\w*|recover\w*|blocked|eligible|disallow\w*)\b",
    r"\breverse[\s-]charge\b|\b(?:exempt|zero[\s-]rated|outside\s+the\s+scope|place\s+of\s+supply|partial\s+exemption)\b",
]), re.I)


def _treatment_claims_cited(text: str) -> bool | None:
    """None when the text claims no treatment; otherwise whether every claim's
    sentence (an entry's lines together) carries its own [REF-n]. One cited
    sentence beside an uncited journal is not a cited treatment."""
    claims = list(_TREATMENT_CONTENT.finditer(text))
    if not claims:
        return None
    for claim in claims:
        start = max(text.rfind(mark, 0, claim.start()) for mark in (". ", "\n\n", "\n- ", "\n* "))
        ends = [i for i in (text.find(mark, claim.end()) for mark in (". ", "\n\n")) if i != -1]
        end = min(ends) + 1 if ends else len(text)
        trailing = re.match(r"\s*\[REF-\d+\]", text[end:])  # "…over time. [REF-1]"
        sentence = text[max(start, 0):end + (trailing.end() if trailing else 0)]
        if not re.search(r"\[REF-\d+\]", sentence):
            return False
    return True


def verification_breakdown(*, completeness: str | None, citations: int, limitations: list[str], calculation=None,
                           receipts: int = 0, mismatches=(), treatment=(), evidence=(), computed: bool = False,
                           source_binding: bool | None = None, answer_text: str = ""):
    """The answer's verification, part by part. `calculation` is the canonical
    engine result; `mismatches` the answer's figures that differ from it;
    `treatment` accounting-treatment findings; `evidence` evidence findings."""
    from app.orchestration.schemas import VerificationBreakdown
    # Nothing is verified for an answer that was not given: the withheld
    # ASC 606 answer showed "Arithmetic: verified" (25 Oct 2026).
    answered = completeness != "none"
    arithmetic = ("mismatch" if mismatches else "verified" if answered and (calculation is not None or receipts)
                  else "not_applicable")
    if citations and source_binding is False:
        sources = "unsupported"
    elif citations:
        partial = (any(finding.code in REVIEW_FINDING_CODES for finding in evidence)
                   or any(marker in item for item in limitations or []
                          for marker in (*_PARTLY_SOURCED, EVIDENCE_NOTE_PREFIX, AUTHORITY_NOTE_PREFIX)))
        sources = "partial" if partial else "verified"
    else:
        sources = "not_applicable" if calculation is not None or computed else "unsupported"
    notes = [*(calculation.notes if calculation is not None else []), *(limitations or [])]
    if treatment or any(ASSUMPTION_MARKERS.search(note) for note in notes):
        assumptions = "stated"
    else:
        assumptions = "confirmed" if calculation is not None else "not_applicable"
    cited = _treatment_claims_cited(answer_text or "") if answered else None
    if treatment:
        treatment_state = "issue_found"
    elif cited is None:
        treatment_state = "not_applicable"
    else:
        # The evidence review checks cited figures, jurisdiction, dates and
        # withdrawn or conflicting sources; it does not prove the source
        # states the treatment, which is why the reader is told "cited".
        treatment_state = "cited_checks_passed" if cited and sources == "verified" else "not_verified"
    if completeness == "none":
        overall = "not_verified"
    elif (completeness == "complete" and arithmetic != "mismatch" and sources in ("verified", "not_applicable")
          and assumptions in ("confirmed", "not_applicable") and not treatment
          and treatment_state == "not_applicable"
          and "verified" in (arithmetic, sources)):
        overall = "fully_verified"
    elif arithmetic == "verified" or sources in ("verified", "partial"):
        overall = "partially_verified"
    else:
        overall = "not_verified"
    return VerificationBreakdown(arithmetic=arithmetic, sources=sources, assumptions=assumptions,
                                 treatment=treatment_state, overall=overall,
                                 calculation_id=calculation.fingerprint() if calculation is not None else None)
