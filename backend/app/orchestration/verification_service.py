"""Answer correction and the final evidence verification release gate."""
from __future__ import annotations
import re
from typing import Callable, Awaitable
from dataclasses import dataclass, field
from app.orchestration import claim_verification
from app.orchestration.telemetry import StageMetrics
from app.domains.model_gateway import service as model_gateway_service
from app.orchestration.calculation_service import needs_lookup

_MODEL_PROVIDER_FAILURE = "Kriton is temporarily unable to reach the language model provider."

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
    claims = claim_verification.extract_claims(answer)
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


async def verify_for_release(answer: str, *, question: str, evidence: list[str],
                             requires_authority: bool, chart_artifacts: list[str] | None = None) -> AnswerVerification:
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
    if not pairs:
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
        return AnswerVerification(False, ["Required authoritative evidence is unavailable"])
    if not claim_verification.enabled():
        return AnswerVerification(False, ["Required claim verification is disabled"])
    if len(pairs) > 60:
        return AnswerVerification(False, ["Answer exceeds the bounded claim verification budget"])
    available = {ref for item in evidence for ref in re.findall(r"\[(REF-\d+)\]", item)}
    failures: list[str] = []
    rejected: list[str] = []
    cited = []
    for original, claim in pairs:
        if (re.search(r'\bcomposition\b', claim, re.I)
                and re.search(r'monthly\s+output\s+tax\s+liability|output\s+tax\s+liability[^.]{0,60}per\s+month', claim, re.I)):
            rejected.append(original)
            failures.append('Monthly output-tax liability for a registration procedure was mislabelled as composition-scheme eligibility')
            continue
        if (re.search(r'\bgst\b', question, re.I)
                and re.search(r'\b(?:india|indian|bangalore|bengaluru)\b', question, re.I)
                and re.search(r'\b(?:registration|register|threshold)\b', question, re.I)
                and not re.search(r'10\s*lakhs?|10,00,000', question, re.I)
                and re.search(r'\bservices\b[^.\n]{0,100}?(?:10\s*lakhs?|10,00,000)|(?:10\s*lakhs?|10,00,000)[^.\n]{0,100}?\bservices\b', claim, re.I)
                and not re.search(r'\b(?:states?|manipur|mizoram|nagaland|tripura|special[- ]category)\b', claim, re.I)):
            rejected.append(original)
            failures.append('A state-specific service registration threshold was stated without its state condition')
            continue
        if (re.search(r'\bcorporation tax\b', question, re.I)
                and (re.search(r'\b(?:ordinary|non[-‑ ]ring[-‑ ]fence)\b', question, re.I) or not re.search(r'\b(?:ring[-‑ ]fence|oil|gas)\b', question, re.I))
                and re.search(r'\bring[-‑ ]fence\b', claim, re.I)
                and not re.search(r'\b(?:only|not|except|oil|gas)\b', claim, re.I)):
            rejected.append(original)
            failures.append('A special ring-fence rate was applied to an ordinary-company question')
            continue
        if (re.search(r'\b(?:export|exports|us client|foreign)\b', question, re.I)
                and re.search(r'without (?:charging|payment of|paying) IGST', claim, re.I)
                and re.search(r'refund of (?:the )?IGST paid', claim, re.I)
                and not re.search(r'alternativ|instead|if.*pay|with payment', claim, re.I)):
            rejected.append(original)
            failures.append('Export without IGST payment was conflated with a refund of IGST paid')
            continue
        if (re.search(r'\bgst\b', question, re.I) and re.search(r'registration', question, re.I)
                and re.search(r'inter[-‑ ]state', claim, re.I) and re.search(r'\bservices\b', claim, re.I)
                and re.search(r'regardless of turnover|irrespective of turnover', claim, re.I)
                and not re.search(r'exempt|except|unless|subject to|notification', claim, re.I)):
            rejected.append(original)
            failures.append('Inter-state service registration omitted turnover exemptions')
            continue
        refs = set(re.findall(r"\[(REF-\d+)\]", claim))
        if refs and refs <= available:
            from app.orchestration.derived_tax_rows import split_tax_row
            derived = split_tax_row(claim, answer, question)
            if derived is not None:
                claim, calculation_error = derived
                if calculation_error:
                    rejected.append(original)
                    failures.append(calculation_error)
                    continue
            cited.append((original, claim, refs))
        else:
            rejected.append(original)
            failures.append("A factual claim lacks a valid citation to retrieved evidence")
    supported = 0
    for start in range(0, len(cited), claim_verification.MAX_CLAIMS):
        batch = cited[start:start + claim_verification.MAX_CLAIMS]
        batch_claims = [claim for _, claim, _ in batch]
        verdict = await claim_verification.verify_claims(batch_claims, evidence, question)
        if not verdict.ran:
            # One retry: a timed-out or malformed verdict escalated a correct
            # "the threshold is £90,000, not £85,000" answer to review.
            verdict = await claim_verification.verify_claims(batch_claims, evidence, question)
        if not verdict.ran or verdict.checked != len(batch):
            return AnswerVerification(False, ["Claim verification unavailable or incomplete"])
        for index, (original, _, refs) in enumerate(batch, start=1):
            if index in verdict.rejected_ids:
                rejected.append(original)
                failures.append("Answer contains contradicted or unsupported claims")
            elif not set(verdict.evidence_refs.get(index, [])) & refs:
                rejected.append(original)
                failures.append("Claim verification did not bind a supported claim to its citation")
            else:
                supported += 1
    if not rejected:
        return AnswerVerification(True)
    # Name the rejected sentences: "contradicted or unsupported claims" alone
    # told neither a reviewer nor a developer what to look at.
    failures = list(dict.fromkeys(failures)) + [
        "Rejected: " + "; ".join(f"\"{claim[:120]}\"" for claim in rejected[:3])
    ]
    return AnswerVerification(
        False, failures, rejected_claims=rejected, prunable=supported > 0,
    )


def prune_rejected_claims(answer: str, rejected: list[str]) -> str:
    """The answer without the rejected statements, and without bullets or
    list introductions they leave empty. The result must be verified again."""
    pruned = claim_verification.remove_claims(answer, rejected)
    lines = [line for line in pruned.splitlines() if line.strip() not in ("-", "*", "•")]
    return claim_verification.mark_emptied_headings(re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip())


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
    r"|\bnot\s+(?:stated|covered|specified|given|available)\s+in\s+the\s+(?:provided\s+|cited\s+|retrieved\s+)?"
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
        for piece in ([line] if line.startswith("|") else claim_verification.sentences(line)):
            piece = claim_verification.without_leading_heading(piece.strip()).strip(" -*•")
            if is_evidence_gap_statement(piece) or _is_pure_arithmetic(piece) or _is_visual_pointer(piece):
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


def requires_authoritative_evidence(question: str) -> bool:
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
