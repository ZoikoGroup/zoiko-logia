"""Shared grounding of economic explanations for every answering provider."""
import re

from app.domains.model_gateway.tool_registry import ToolResult
from app.orchestration.websearch import WebSource


# A sentence explaining WHY an economic figure moved: a causal connector AND
# a real-world cause. Both are required — a connector alone is ordinary
# reasoning ("Because Japan's rate is lower, no chart is needed"), and
# removing whole lines on "because" alone deleted exactly that conclusion.
_CAUSAL_CONNECTOR = re.compile(
    r"\b(?:because|due to|driven by|attribut(?:ed|able) to|caused by|owing to|as a result of|"
    r"on the back of|fu?ell?ed by|led to|resulted in|contributed to|reflect(?:s|ed|ing)?|"
    r"linked to|thanks to|amid|as (?:the )?econom\w+|as economic activity)\b",
    re.I,
)
_EXTERNAL_CAUSE = re.compile(
    r"\b(?:stimulus|pandemic|covid|lockdown|recession|crisis|war|conflict|sanction|tariff|"
    r"monetary|fiscal|policy|policies|central bank|interest rates?|rate (?:hikes?|cuts?)|"
    r"spending|tax (?:cuts?|receipts|revenues?|reforms?)|borrowing|deficits?|demand|supply|"
    r"commodit\w*|oil|energy|food prices|currency|depreciation of|devaluation|exchange rate|"
    r"investment|consumption|exports? (?:boom|surge|slump)|reforms?|elections?|government|"
    r"recover\w*|fiscal position|economic activity)\b",
    re.I,
)
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z*])")


# Causes that are attributions on their own, even with no connector
# ("after the pandemic-related surge").
_STRONG_CAUSE = re.compile(r"\b(?:pandemic|covid(?:-19)?|stimulus|lockdowns?)\b", re.I)
_CAUSES_ALREADY_DISCLAIMED = re.compile(
    r"\b(?:causes?|drivers?|reasons?)\b[^.\n]{0,60}\bnot (?:established|detailed|stated|given|explained|provided)"
    r"|\bdo(?:es)? not (?:state|establish|explain|detail) (?:the |their |its )?(?:causes?|drivers?|reasons?)",
    re.I,
)
_TREND_WORDS = re.compile(r"\d|\b(?:rose|fell|rise|fall|increase\w*|decrease\w*|declin\w*|peak\w*|"
                          r"grew|growth|drop\w*|climb\w*|eas\w*|rebound\w*|stable|stabilis\w*|stabiliz\w*|higher|lower)\b", re.I)


def _without_cause(sentence: str) -> str | None:
    """The sentence with its unsupported causal part removed, or None when
    nothing worth keeping is left. "Debt fell to 112.72% in 2022 as the
    economy recovered." keeps "Debt fell to 112.72% in 2022." — deleting the
    whole sentence dropped the trend itself."""
    ending = "." if sentence.rstrip().endswith(".") else ""
    connector = _CAUSAL_CONNECTOR.search(sentence)
    if connector and _EXTERNAL_CAUSE.search(sentence[connector.start():]):
        head = sentence[:connector.start()].rstrip(" ,;:—–-")
        return head + ending if _TREND_WORDS.search(head) and len(head.split()) >= 3 else None
    # No connector: drop the comma/dash-separated clause carrying the cause.
    clauses = re.split(r"(,\s+|\s+[—–-]\s+)", sentence)
    kept = [c for c in clauses[::2] if not _STRONG_CAUSE.search(c) and not _EXTERNAL_CAUSE.search(c)]
    head = ", ".join(c.strip(" .") for c in kept if c.strip(" ."))
    head = head[:1].upper() + head[1:]
    return head + ending if head and _TREND_WORDS.search(head) and len(head.split()) >= 3 else None


def ground_economic_narrative(text: str, results: list[ToolResult]) -> str:
    """Keep numeric-only economic evidence from acquiring causal prose.

    Trims the part of a sentence that explains a movement by an outside cause
    the sources do not state ("… due to pandemic stimulus", "after the
    pandemic-related surge"), keeping the description of the numbers; drops
    "commonly cited" boilerplate. Comparisons, conclusions ("Because Japan's
    rate is lower, no chart is needed"), numeric table cells, chart payloads and quoted
    source text are kept. Unsupported causal table cells are replaced. A note is added only when something was removed
    and the answer does not already say the causes are not established.
    """
    return ground_causal_claims(text, [source for result in results for source in result.sources])


def ground_causal_claims(text: str, sources: list[WebSource]) -> str:
    """ground_economic_narrative() for answers composed outside the agent
    loop, which carry retrieved sources rather than tool results."""
    evidence = " ".join(" ".join(source.snippet.casefold().split()) for source in sources)
    kept: list[str] = []
    in_fence = False
    removed = False
    causal_table = False
    lines = text.splitlines()
    for line_index, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        if in_fence or line.lstrip().startswith("```"):
            kept.append(line)
            continue
        if line.lstrip().startswith("|"):
            cells = line.split("|")
            header_row = line_index + 1 < len(lines) and bool(
                re.fullmatch(r"[\s|:\-]+", lines[line_index + 1])
            )
            heading = header_row and bool(re.search(r"\b(?:causes?|drivers?|factors|explanations?)\b", line, re.I))
            causal_table = causal_table or heading
            for index, cell in enumerate(cells):
                normalized = " ".join(cell.strip(" *").casefold().split())
                causal = bool(_EXTERNAL_CAUSE.search(cell) or _STRONG_CAUSE.search(cell))
                if not heading and not header_row and normalized and normalized not in evidence and (
                    (causal and (causal_table or _CAUSAL_CONNECTOR.search(cell) or _STRONG_CAUSE.search(cell)))
                    or (causal_table and len(normalized.split()) > 3
                        and not _CAUSES_ALREADY_DISCLAIMED.search(cell))
                ):
                    cells[index] = " Not established by the retrieved sources. "
                    removed = True
            kept.append("|".join(cells))
            continue
        causal_table = False
        prefix = re.match(r"^\s*(?:[-*]\s+|\d+\.\s+)?", line).group(0)
        sentences = _SENTENCE.split(line[len(prefix):])
        survivors = []
        for sentence in sentences:
            normalized = " ".join(sentence.strip(" *->").casefold().split())
            causal = (
                (_CAUSAL_CONNECTOR.search(sentence) and _EXTERNAL_CAUSE.search(sentence))
                or _STRONG_CAUSE.search(sentence)
            )
            if re.search(r"\bcommonly cited\b", sentence, re.I) and normalized not in evidence:
                removed = True
                continue
            if causal and normalized and normalized not in evidence:
                removed = True
                trimmed = _without_cause(sentence)
                if trimmed:
                    survivors.append(trimmed)
                continue
            survivors.append(sentence)
        if survivors:
            kept.append(prefix + " ".join(survivors))
        elif not line.strip():
            kept.append("")
    if removed and not _CAUSES_ALREADY_DISCLAIMED.search("\n".join(kept)):
        kept.append("\n*The figures come from official statistics, which do not state the causes of these changes.*")
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()


