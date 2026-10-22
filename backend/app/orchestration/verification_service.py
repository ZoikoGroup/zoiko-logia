"""Answer correction and the final evidence verification release gate."""
from __future__ import annotations
import asyncio
import re
from typing import Callable, Awaitable
from dataclasses import dataclass, field
from app.orchestration import claim_verification
from app.orchestration.telemetry import StageMetrics
from app.domains.model_gateway import service as model_gateway_service
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
        corrected = await metrics.run(
            "composition.claim_correction",
            model_gateway_service.run_grounded_completion(
                grounded_input + claim_verification.correction_request(answer, verdict.contradicted),
            ),
        )
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
    r"\s?(?:【[^】\n]{0,30}】|[\[［]\s*(?:CALC|CALCULATION|SRC|SOURCE)[\s\-‐‑‒–—_]?\d+\s*[\]］])", re.I,
)


_CALCULATED_TAG = re.compile(r"\[\s*calculat\w*(?:\s+result)?\s*[:=]?\s*([^\]\n]{0,40})\]", re.I)


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
    text = _INVENTED_MARKER.sub("", _CITATION_VARIANT.sub(canonical, answer or ""))
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


def _from_verified_calculation(claim: str, calculated) -> bool:
    """A statement presenting a verified calculation: it shows at least one
    computed result, every other figure is an input the result came from, and
    it asserts no rule, rate, threshold or deadline. A sentence that only
    repeats the user's figures ("The £120,000 is recognised on day one") is
    still a claim and needs a source."""
    if not calculated or _RULE_ASSERTION.search(claim):
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


def received_consideration(question: str) -> list[float]:
    """Amounts the user says were paid, received, billed or due: "The customer
    paid £24,000 upfront". "The implementation fee is £6,000" is a price, not
    a receipt."""
    from app.orchestration.figure_reconciliation import material_figures
    found: list[float] = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n", question or ""):
        if _RECEIVED.search(sentence):
            found += [value for shown, value in material_figures(sentence) if not shown.endswith("%")]
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
    restated = [original for original, _ in pairs
                if not re.search(r"\[REF-\d+\]", original) and _from_verified_calculation(original, calculated)]
    pairs = [(original, claim) for original, claim in pairs if original not in restated]
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
        False, failures, rejected_claims=rejected, prunable=supported > 0 or bool(general), rejected_reasons=reasons,
        general_explanations=general,
    )


_GAP_ONLY_REASONS = {"missing_citation", "not_in_cited_evidence", "citation_not_bound"}
# Anything that makes a statement a specific claim a reader could act on:
# figures, dates, places, and tax, legal, accounting-treatment or standards
# vocabulary. Those keep their full evidence requirement.
_SPECIFIC_CLAIM = re.compile(
    r"\d|[£$€₹%]|\b(?:tax|vat|gst|hmrc|irs|cbic|duty|duties|tax rate|vat rate|interest rate|rate of|threshold|"
    r"deadline|due date|penalt\w*|fine[sd]?|law|legal\w*|legislat\w*|regulat\w*|act|section|rule|standard|ifrs|ias|"
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


def prune_rejected_claims(answer: str, rejected: list[str], note: str | None = None) -> str:
    """The answer without the rejected statements, and without bullets or
    list introductions they leave empty. The result must be verified again.
    `note` replaces the default line under a heading the removal emptied."""
    pruned = claim_verification.remove_claims(answer, rejected, note=note)
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


def _is_pure_arithmetic(piece: str) -> bool:
    """A label and an equation only. "The standard rate is 20%, so VAT =
    £1,000 × 20% = £200" also asserts a rate, so it still needs a source."""
    return bool(_ARITHMETIC_LINE.search(piece)) and not _STATED_FACT.search(piece.split("=", 1)[0])


_BOLD_ONLY = re.compile(r"(\*\*|__)[^*_]+\1")
_GAP_STATEMENT = re.compile(
    r"\b(?:sources?|evidence|guidance|documents?)\b[^.]*?\b(?:do(?:es)?\s+not|don['’]t|doesn['’]t)\s+"
    r"(?:state|specify|cover|include|give|provide|mention|say|address|confirm|establish|contain|list|show)\b"
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
_TAX_WORDS = re.compile(r"\b(?:tax(?:es|ation|able)?|vat|gst|pre-tax)\b", re.I)
_SCENARIO_FIGURE = re.compile(r"[£$€₹]\s?\d|\b\d[\d,]*(?:\.\d+)?\s?%|\b\d{1,3}(?:,\d{2,3})+\b")


def applies_to_supplied_facts(question: str, context: str) -> bool:
    """The authority terms in the question only name the framework a supplied
    scenario is worked under, or a tax the user gave the rate for."""
    if _ABOUT_THE_AUTHORITY.search(question) or len(_SCENARIO_FIGURE.findall(context or "")) < 2:
        return False
    residual = _ANALYTICAL_LIMIT.sub(" ", _FRAMEWORK_REFERENCE.sub(" ", question))
    if _SUPPLIED_RATE.search(context):
        residual = _TAX_WORDS.sub(" ", residual)
    return not _authority_terms(residual)


def requires_authoritative_evidence(question: str, context: str = "") -> bool:
    """Every claim must be cited from governed or official sources. With the
    supplied scenario as context, applying a named framework to the user's own
    facts is a professional explanation instead: it may use professional
    knowledge, labelled as not source-verified."""
    if not _authority_terms(question):
        return False
    return not (context and applies_to_supplied_facts(question, context))


def _authority_terms(question: str) -> bool:
    return needs_lookup(question) or bool(re.search(
        r"\b(?:vat|gst|tax|taxation|hmrc|cbic|filing|statutory|legislation|regulation|"
        # "Due date for GSTR-3B" was answered unsourced, adding a wrong
        # "nil returns are due on the 10th".
        r"compliance|legal|deadline|refund|cash accounting|flat rate|audit opinion|"
        r"due dates?|late fees?|penalt(?:y|ies)|gstr-?\w*|tds|tcs|"
        # Statutory payroll: PF/ESI were computed from memory with a wrong
        # ESI wage ceiling (₹10,000; it is ₹21,000) and no citation.
        r"pf|epf|esi|esic|provident fund|gratuity|national insurance|nic|paye|social security|"
        r"medicare|fica|minimum wage|living wage|sick pay|maternity pay|employment allowance|"
        r"withholding)\b", question, re.I,
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
