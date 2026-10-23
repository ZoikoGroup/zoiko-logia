"""Accounting-concept validation, separate from arithmetic (reliability spec
phases 3 and 6).

Arithmetic checks prove a figure, not the treatment around it. On 22 Oct 2026
a share-option answer computed the right $114,000 and cited "IAS 12 / ASC
740" (income taxes) for it, and a monetary-unit-sampling answer used the
attribute-sampling formula n = Z²p(1−p)/d²; both passed every numeric check.
This module checks the concept: which standard governs a topic, which method
a technique uses, and which published reference values a topic relies on.

Deterministic and conservative. A standard reference is corrected only when
its sentence is about exactly one registered topic and names nothing of the
cited standard's own topic; a method is flagged only on an unambiguous
formula. Stable standard numbering only — never rates, thresholds or rules
that change by period or jurisdiction.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Topic:
    name: str
    terms: re.Pattern                 # the sentence is about this topic
    mentions: re.Pattern              # the sentence touches this topic at all
    us_gaap: tuple[str, ...] = ()     # governing standard first: "ASC 718"
    ifrs: tuple[str, ...] = ()        # "IFRS 2", "IAS 12"
    auditing: tuple[str, ...] = ()    # "AU-C 705", "ISA 705"
    also: tuple[str, ...] = ()        # also legitimately cited for it: goodwill under ASC 350 / IAS 36


def _terms(pattern: str) -> re.Pattern:
    return re.compile(rf"\b(?:{pattern})\b", re.I)


TOPICS: tuple[Topic, ...] = (
    Topic("revenue from contracts with customers",
          _terms(r"revenue recognition|performance obligations?|transaction price|stand-?alone selling prices?|"
                 r"contracts? with (?:a |the )?customers?"), _terms(r"revenue|customers?|contracts?"),
          ("ASC 606",), ("IFRS 15",)),
    Topic("leases", _terms(r"leases?|lessee|lessor|right-of-use|ROU asset|lease liabilit(?:y|ies)"), _terms(r"leas\w*|right-of-use|ROU"),
          ("ASC 842",), ("IFRS 16",)),
    Topic("business combinations",
          _terms(r"business combinations?|goodwill|non-?controlling interests?|NCI|purchase price allocation|"
                 r"acquisition method|bargain purchase"), _terms(r"acqui\w*|goodwill|combinations?|NCI|non-?controlling"),
          ("ASC 805",), ("IFRS 3",), also=("ASC 350", "IAS 36", "IAS 38")),
    Topic("impairment of long-lived assets",
          _terms(r"impair(?:ed|ment)|recoverability test|undiscounted (?:future )?cash flows|recoverable amount"),
          _terms(r"impair\w*|recoverab\w*|write-?downs?|carrying amounts?"), ("ASC 360", "ASC 350"), ("IAS 36",)),
    Topic("income taxes",
          _terms(r"deferred tax(?:es)?|income tax(?:es)? (?:expense|provision|payable)|provision for income taxes|"
                 r"temporary differences?|taxable income|tax bases?|valuation allowance"), _terms(r"tax\w*"),
          ("ASC 740",), ("IAS 12",)),
    Topic("share-based payment",
          _terms(r"stock options?|share options?|share-based|stock-based|stock compensation|grant-date fair value|"
                 r"vesting(?: period)?|forfeitures?|employee share|equity-settled"),
          _terms(r"shares?|stock|options?|awards?|vest\w*|grants?"), ("ASC 718",), ("IFRS 2",)),
    Topic("statement of cash flows",
          _terms(r"statements? of cash flows|cash flows? statement|operating activities|indirect method|"
                 r"investing activities|financing activities"), _terms(r"cash"), ("ASC 230",), ("IAS 7",)),
    # AS 1105 was cited for classifying control deficiencies (22 Oct 2026).
    Topic("audit evidence", _terms(r"audit evidence|sufficient appropriate evidence|appropriateness of evidence"),
          _terms(r"evidence"), (), (), ("AU-C 500", "ISA 500", "AS 1105")),
    Topic("modified audit opinions",
          _terms(r"modified opinion|qualified opinion|adverse opinion|disclaimer of opinion|scope limitation|"
                 r"material and pervasive"), _terms(r"opinions?|auditor'?s? report"), (), (), ("AU-C 705", "ISA 705")),
    Topic("audit sampling",
          _terms(r"monetary unit sampling|MUS|probability-proportional-to-size|PPS sampling|sample size|"
                 r"tolerable misstatement|tainting|upper misstatement limit"), _terms(r"sampl\w*"), (), (), ("AU-C 530", "ISA 530")),
    Topic("internal control deficiencies",
          _terms(r"significant deficienc(?:y|ies)|material weakness(?:es)?|control deficienc(?:y|ies)|"
                 r"deficiencies in internal control|internal controls? over financial reporting|evaluation of internal controls?|"
                 r"compensating controls?|segregation of duties"), _terms(r"controls?"), (), (), ("AU-C 265", "ISA 265", "AS 2201")),
)

# A cited standard, as written: "ASC 740", "ASC 740-10", "IAS 12", "IFRS IAS 12",
# "IFRS 2", "AU-C 705", "ISA 705", "AS 2201".
_REFERENCE = re.compile(
    r"\b(?:IFRS\s+(?=IAS\s?\d))?(?P<family>ASC|IAS|IFRS|AU-?C|ISA|AS)\s?(?P<number>\d{1,4})(?:[-‐‑–]\d+)*\b"
)


def _normalise(family: str, number: str) -> str:
    family = "AU-C" if family.upper().replace("-", "") == "AUC" else family.upper()
    return f"{family} {int(number)}"


def _owners(reference: str) -> list[Topic]:
    return [topic for topic in TOPICS if reference in topic.us_gaap + topic.ifrs + topic.auditing]


def _acceptable_for(topic: Topic, reference: str) -> bool:
    return reference in topic.us_gaap + topic.ifrs + topic.auditing + topic.also


# "under ASC 842, not ASC 606": a reference named to contrast it is not a claim.
_CONTRAST_BEFORE = re.compile(r"(?:\bnot|\brather than|\binstead of|\bunlike|\bvs\.?|\bversus|\bthan|\bformerly|\bpreviously|\breplaced)\s*$", re.I)


def _same_family(topic: Topic, reference: str) -> str | None:
    family = reference.split()[0]
    pool = {"ASC": topic.us_gaap, "IAS": topic.ifrs, "IFRS": topic.ifrs,
            "AU-C": tuple(r for r in topic.auditing if r.startswith("AU-C")),
            "ISA": tuple(r for r in topic.auditing if r.startswith("ISA")),
            "AS": tuple(r for r in topic.auditing if r.startswith("AS "))}.get(family, ())
    return pool[0] if pool else None


@dataclass
class ConceptReview:
    text: str
    corrections: list[str] = field(default_factory=list)     # user-facing notes
    removed: list[str] = field(default_factory=list)         # user-facing notes

    @property
    def changed(self) -> bool:
        return bool(self.corrections or self.removed)


def _sentences(line: str) -> list[str]:
    return re.split(r"(?<=[.!?])\s+(?=[A-Z(*])", line)


def correct_standard_references(text: str) -> tuple[str, list[str]]:
    """Replace a cited standard that governs a different topic from its sentence.

    "IAS 12 / ASC 740 — record the grant-date fair value as share-based payment
    expense" becomes "IFRS 2 / ASC 718 — …". Left alone: a sentence naming
    two registered topics, one naming the cited standard's own topic
    ("deferred tax on share options — ASC 740"), and unregistered standards."""
    notes: list[str] = []
    out_lines = []
    for line in (text or "").splitlines():
        if line.strip().startswith("```"):
            out_lines.append(line)
            continue
        pieces = []
        for sentence in _sentences(line):
            topics = [topic for topic in TOPICS if topic.terms.search(sentence)]
            if len(topics) == 1:
                subject = topics[0]

                def fix(match: re.Match, sentence: str = sentence) -> str:
                    cited = _normalise(match.group("family"), match.group("number"))
                    owners = _owners(cited)
                    if (not owners or _acceptable_for(subject, cited)
                            # Any mention of the cited standard's own subject
                            # ("the tax effect of the lease") leaves it alone.
                            or any(owner.mentions.search(sentence) for owner in owners)
                            or _CONTRAST_BEFORE.search(sentence[:match.start()][-24:])):
                        return match.group(0)
                    replacement = _same_family(subject, cited)
                    if replacement is None:
                        return match.group(0)
                    notes.append(f"{cited} → {replacement} ({cited} is the standard on {owners[0].name}; "
                                 f"this statement is about {subject.name})")
                    return replacement

                sentence = _REFERENCE.sub(fix, sentence)
            pieces.append(sentence)
        out_lines.append(" ".join(pieces))
    return "\n".join(out_lines), list(dict.fromkeys(notes))


# Formulas that belong to a different technique from the one asked about.
_ATTRIBUTE_SAMPLING_FORMULA = re.compile(
    r"Z\s*(?:\^\s*2|²)|\bp\s*\(\s*1\s*[-−]\s*p\s*\)|\bZ[- ]value\b", re.I,
)
_MUS_QUESTION = re.compile(r"\bmonetary[- ]unit sampling\b|\bMUS\b|\bprobability[- ]proportional[- ]to[- ]size\b", re.I)
# "Unlike attribute sampling (n = Z²p(1−p)/d²), MUS …" explains the difference.
_CONTRASTS_METHOD = re.compile(r"\battribute sampling\b|\bunlike\b|\brather than\b|\binstead of\b|\bnot used\b", re.I)
MUS_METHOD_NOTE = (
    "The sample-size formula shown was for attribute sampling, not monetary unit sampling, and was removed. "
    "MUS sizes the sample as n = (population book value × confidence factor) ÷ (tolerable misstatement − "
    "expected misstatement × expansion factor), with factors from the auditor's sampling tables."
)


def remove_wrong_method(question: str, text: str) -> tuple[str, list[str]]:
    """Statements using a formula from another technique. Only the formula
    statements go; the rest of the answer stays."""
    if not _MUS_QUESTION.search(question or "") or not _ATTRIBUTE_SAMPLING_FORMULA.search(text or ""):
        return text, []
    kept, removed, in_fence = [], False, False
    for line in (text or "").splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
        if (not in_fence and _ATTRIBUTE_SAMPLING_FORMULA.search(line)
                and not _CONTRASTS_METHOD.search(line)):
            removed = True
            continue
        kept.append(line)
    # Only a removal is reported: a kept contrast is not a correction.
    return ("\n".join(kept), [MUS_METHOD_NOTE]) if removed else (text, [])


def review_concepts(question: str, text: str) -> ConceptReview:
    corrected, corrections = correct_standard_references(text)
    cleaned, removed = remove_wrong_method(question, corrected)
    return ConceptReview(text=cleaned, corrections=corrections, removed=removed)


# Published reference values a figure check would otherwise call unsupported.
# Stable, framework-level guidance only.
_LEASE_CLASSIFICATION = re.compile(
    r"\b(?:major part|substantially all|economic life|lease term|lease classification|finance lease|"
    r"classified as (?:a )?(?:finance|operating))\b", re.I)
_CONFIDENCE = re.compile(r"\bconfidence (?:level|factor)s?\b|\bconfidence\b", re.I)
_AS_THRESHOLD = re.compile(
    r"\b(?:thresholds?|bright[- ]lines?|major part|substantially all|or more|at least|criteri(?:on|a)|tests?|indicators?)\b", re.I)


def reference_percentages(text: str) -> list[float]:
    """ASC 842-10-55-2's 75% (major part of economic life) and 90%
    (substantially all of fair value) bright lines in a lease-classification
    statement; the conventional 90/95/99% confidence levels in a sampling one.
    Called per statement: "rent rose 75%" elsewhere in a lease answer still
    needs support."""
    values: list[float] = []
    # Stated as the test, not as a fact about this lease: "the lease term is
    # 75% of the economic life" is a claim that still needs support.
    if _LEASE_CLASSIFICATION.search(text or "") and _AS_THRESHOLD.search(text or ""):
        values += [75.0, 90.0]
    if _CONFIDENCE.search(text or "") and _terms(r"sampl(?:e|ing)|MUS").search(text or ""):
        values += [90.0, 95.0, 99.0]
    return values
