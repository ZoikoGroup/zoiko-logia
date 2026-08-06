"""
Does the retrieved evidence actually cover every subject the query named?

The failure this exists to stop, observed on a real query: asked to compare
accounts payable with accrued expenses, retrieval returned an accounts-
payable process document and nothing on accrued expenses. The bundle reported
"sufficient confidence" — it had four eligible sources, they just all
described one half of the question — and the answer was a confident
accounts-payable process checklist. A different question, answered well.

Bundle-level confidence cannot catch that. It measures how much evidence
arrived, not whether the evidence spans what was asked. A comparison of two
subjects needs support for BOTH, and one subject with plenty of evidence
looks identical to two subjects with half the evidence each.

So this asks a different question, per subject, and reports the gap. It never
suppresses an answer: composition is told what is missing and says so, which
is a better outcome than either a refusal or a confident half-answer.

Deliberately deterministic. No model call, no embedding — a query naming two
subjects is a syntactic fact, and paying an LLM round trip to notice it would
put a network call on the critical path of every request.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Markers where every subject FOLLOWS the marker: "compare X and Y".
# Ordered longest-first, since "compared to" contains "compare".
_PREFIX_MARKERS: tuple[str, ...] = (
    "differences between",
    "difference between",
    "distinguish between",
    "compare",
    "contrast",
)

# Markers with a subject on EACH SIDE: "X vs Y". Treating these as prefix
# markers silently dropped the left-hand subject — "FRS 102 vs FRS 105"
# yielded one subject and so was never checked as a comparison at all.
_INFIX_MARKERS: tuple[str, ...] = (
    " compared with ",
    " compared to ",
    " versus ",
    " vs. ",
    " vs ",
)

# Leading interrogative scaffolding stripped from the left-hand side of an
# infix comparison, so "What is FRS 102 vs FRS 105" yields "FRS 102" rather
# than "is FRS 102". Stripped word by word rather than by one regex: a
# character class like [^A-Z0-9] under re.IGNORECASE excludes lowercase
# letters too, so it stops at the first word instead of consuming the run.
_LEADING_FILLER = frozenset({
    "what", "whats", "which", "how", "when", "why", "is", "are", "was", "were",
    "does", "do", "did", "can", "could", "should", "would", "the", "a", "an",
    "between", "difference", "differences", "tell", "me", "about", "explain",
})


# Presentation lead-in on the LEFT of an infix comparison. Word-by-word
# filler stripping cannot remove this: it stops at the first non-filler word,
# so "Show me a chart of FRS 102 vs FRS 105" kept the whole phrase as the
# subject and would have printed it in a user-facing limitation. Everything
# up to and including the presentation noun/verb, plus any connective, goes.
_LEADING_PRESENTATION = re.compile(
    r"^.*?\b(?:chart|graph|table|plot|diagram|visuali[sz]e|visuali[sz]ation|"
    r"show|display|give|list|summar\w*|breakdown)\b\s*(?:me\s+)?"
    r"(?:of|for|on|showing|between)?\s*",
    re.IGNORECASE,
)


def _strip_leading_filler(text: str) -> str:
    stripped = _LEADING_PRESENTATION.sub("", text)
    # Only accept the presentation strip if it left something; otherwise the
    # whole left side WAS the subject and the regex over-matched.
    words = (stripped if stripped.strip() else text).split()
    while words and re.sub(r"[^a-z]", "", words[0].lower()) in _LEADING_FILLER:
        words.pop(0)
    return " ".join(words)

# Splits the subject phrase into its parts.
_SUBJECT_SEPARATOR = re.compile(r"\s+(?:and|or|versus|vs\.?|against)\s+|\s*[,;/]\s*", re.IGNORECASE)

# Trailing presentation instructions that are not part of any subject —
# "compare X and Y **in a table**" names two subjects, not three.
_PRESENTATION_TAIL = re.compile(
    r"\s*(?:in|as|using|with)\s+(?:a\s+|an\s+|the\s+)?"
    r"(?:table|chart|graph|list|checklist|timeline|summary|bullet points?|"
    r"side by side|comparison)\b.*$",
    re.IGNORECASE,
)

# Words that are never a subject on their own, so a split that produces one
# is treated as noise rather than a missing subject.
_STOPWORDS = frozenset({
    "it", "them", "these", "those", "this", "that", "both", "each", "one",
    "other", "others", "the", "a", "an", "and", "or", "any", "all",
    # Function words that survive the length filter and would otherwise
    # count as "significant" when a trailing qualifier stays attached to a
    # subject ("FRS 105 for a micro-entity").
    "for", "with", "under", "from", "when", "what", "how", "does", "are",
    "its", "their", "than", "then", "into", "upon", "per", "was", "were",
})

_MIN_SUBJECT_LENGTH = 3
_MAX_SUBJECTS = 4

# A subject counts as covered when this many of its significant words appear
# in the evidence. Full containment is too strict — "accounts payable" should
# be satisfied by evidence discussing "accounts payable", but "accrued
# expenses at the reporting date" should not require that exact phrase.
_COVERAGE_TOKEN_RATIO = 0.6


@dataclass(frozen=True)
class SubjectCoverage:
    subject: str
    covered: bool
    # Titles of the sources that support it, for the answer to name.
    supporting_titles: tuple[str, ...] = ()
    # Best rank among the supporting sources; None when uncovered. Lets an
    # answer distinguish "supported by a standard" from "supported only by
    # discovery", which is a materially different claim.
    best_rank: int | None = None


@dataclass(frozen=True)
class CoverageReport:
    subjects: tuple[SubjectCoverage, ...]

    @property
    def is_multi_subject(self) -> bool:
        return len(self.subjects) > 1

    @property
    def uncovered(self) -> tuple[str, ...]:
        return tuple(item.subject for item in self.subjects if not item.covered)

    @property
    def is_complete(self) -> bool:
        return bool(self.subjects) and not self.uncovered

    @property
    def is_partial(self) -> bool:
        """Some subjects covered, some not — the case that produced a
        confident answer to a different question."""
        return bool(self.uncovered) and len(self.uncovered) < len(self.subjects)


def _stem(word: str) -> str:
    """Crude plural stripping, so a subject matches evidence that inflects it
    differently.

    "accrued expenses" against text saying "an accrued expense" is the single
    most likely mismatch in this domain, and exact matching failed it — the
    subject scored 1 of 2 words and was reported as uncovered. Stemming is
    applied only to the query's subject; the evidence is searched by
    substring, so "expens" finds both "expense" and "expenses".

    Deliberately not a real stemmer. Over-truncation here costs a slightly
    looser match on a coverage heuristic; under-truncation costs a false
    "no source material" claim, which is the worse error.
    """
    if word.endswith("ies") and len(word) > 5:
        return word[:-3]
    if word.endswith("es") and len(word) > 4:
        return word[:-2]
    if word.endswith("s") and len(word) > 3:
        return word[:-1]
    return word


def _significant_words(text: str) -> list[str]:
    return [
        _stem(word) for word in re.findall(r"[a-z0-9]+", text.lower())
        if word not in _STOPWORDS and len(word) > 2
    ]


def extract_subjects(query: str) -> tuple[str, ...]:
    """Subjects a comparison-shaped query names, or () for anything else.

    Returns () rather than guessing for a single-subject query: a coverage
    report over one subject adds nothing that bundle confidence does not
    already say, and inventing subjects from ordinary prose would generate
    false gaps.
    """
    lowered = query.lower()

    candidate_text = ""
    infix = next((m for m in _INFIX_MARKERS if m in lowered), None)
    if infix is not None:
        index = lowered.index(infix)
        left = _strip_leading_filler(query[:index]).strip(" ?.!:;\"'")
        right = query[index + len(infix):]
        # Rejoined with "and" so the one separator handles both halves, and a
        # three-way "X vs Y and Z" still splits correctly.
        candidate_text = f"{left} and {right}" if left else right
    else:
        prefix = next((m for m in _PREFIX_MARKERS if m in lowered), None)
        if prefix is None:
            return ()
        candidate_text = query[lowered.index(prefix) + len(prefix):]

    tail = _PRESENTATION_TAIL.sub("", candidate_text).strip(" ?.!:;")
    if not tail:
        return ()

    parts = []
    for part in _SUBJECT_SEPARATOR.split(tail):
        cleaned = part.strip(" ?.!:;\"'").strip()
        if len(cleaned) < _MIN_SUBJECT_LENGTH:
            continue
        if cleaned.lower() in _STOPWORDS:
            continue
        if not _significant_words(cleaned):
            continue
        parts.append(cleaned)

    # One subject is not a comparison — the marker matched something like
    # "compare the treatment under IFRS 16", which names a single topic.
    return tuple(parts[:_MAX_SUBJECTS]) if len(parts) > 1 else ()


def _chunk_supports(subject: str, chunk_text: str, chunk_title: str) -> bool:
    words = _significant_words(subject)
    if not words:
        return False
    haystack = f"{chunk_title} {chunk_text}".lower()
    hits = sum(1 for word in words if word in haystack)
    return hits / len(words) >= _COVERAGE_TOKEN_RATIO


def assess_coverage(
    query: str,
    chunks: list[dict],
    *,
    ranks_by_source_id: dict[str, int] | None = None,
) -> CoverageReport:
    """Which named subjects the retrieved evidence actually supports.

    Runs over the merged chunk set rather than per provider, so evidence from
    a document, a live source and a web result all count toward the same
    subject — the union is what the answer is built from.
    """
    subjects = extract_subjects(query)
    if not subjects:
        return CoverageReport(subjects=())

    ranks = ranks_by_source_id or {}
    assessed: list[SubjectCoverage] = []
    for subject in subjects:
        titles: list[str] = []
        best: int | None = None
        for chunk in chunks:
            metadata = chunk.get("metadata", {}) or {}
            title = str(metadata.get("title") or "")
            if not _chunk_supports(subject, str(chunk.get("text") or ""), title):
                continue
            if title and title not in titles:
                titles.append(title)
            rank = metadata.get("authority_rank") or ranks.get(str(metadata.get("source_id") or ""))
            if rank is not None and (best is None or int(rank) < best):
                best = int(rank)
        assessed.append(SubjectCoverage(
            subject=subject, covered=bool(titles), supporting_titles=tuple(titles[:4]),
            best_rank=best,
        ))
    return CoverageReport(subjects=tuple(assessed))


def coverage_instruction(report: CoverageReport) -> str:
    """What composition must be told, or "" when there is nothing to say.

    Phrased as a requirement rather than a suggestion because the failure
    mode is a model filling the gap from its own knowledge — which is exactly
    what a grounded product must not do, and what makes the gap invisible.
    """
    if not report.is_multi_subject or report.is_complete:
        return ""
    missing = ", ".join(f'"{subject}"' for subject in report.uncovered)
    if not report.is_partial:
        return (
            f"Evidence requirement: the retrieved sources do not cover {missing}. "
            "State plainly that you cannot compare these subjects from the available "
            "sources, and do not describe the missing subject from general knowledge."
        )
    covered = ", ".join(
        f'"{item.subject}"' for item in report.subjects if item.covered
    )
    return (
        f"Evidence requirement: the retrieved sources cover {covered} but do not cover "
        f"{missing}. Answer only on what is covered, state explicitly that {missing} "
        "is not supported by the available sources, and do not substitute general "
        "knowledge for it."
    )


def coverage_limitation(report: CoverageReport) -> str | None:
    """The user-facing limitation line, for the answer's limitations list."""
    if not report.is_multi_subject or report.is_complete:
        return None
    missing = ", ".join(report.uncovered)
    return (
        f"No source material was found for: {missing}. "
        "The answer is limited to the subjects the library covers."
    )
