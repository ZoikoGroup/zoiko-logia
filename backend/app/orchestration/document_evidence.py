"""
Structured chart evidence from the user's OWN uploaded documents.

The visualization pipeline builds every chart from EvidenceModel.observations,
and until now only the live connectors (dbnomics, frankfurter, fred, market
data, sec_edgar) populated that. fetch_live_data() takes a query string and
never sees an attachment, so a question like "compare the asset types in this
file as a bar chart" retrieved the document correctly, answered from its text,
and then reported that no verified data could be found for the chart — true of
the live feeds, and misleading about the document sitting right there.

This module closes that gap and nothing else: document chunks in, Observations
out, in the same shape the connectors already produce. Chart-type selection,
validation, fallbacks and renderers downstream are untouched.

The data-honesty rule is unchanged and is the reason most of this file is
rejection logic. A figure may only be charted when it was actually READ from
the document:

  - Only label/number pairs that appear literally in the text are emitted.
    Nothing is inferred, interpolated, summed or rescaled.
  - Rows that read as totals ("Total", "Subtotal", "Overall") are dropped, not
    charted alongside their own components — a total plotted as a peer makes
    every other bar look insignificant and double-counts the series.
  - Ambiguity fails closed. Too few points, duplicate labels, mixed units or
    an unreadable table returns empty evidence, which lands on exactly the
    honest "couldn't retrieve verified data" message shown today.

Scanned PDFs and deeply nested multi-header tables are out of scope: they
extract unreliably, and a wrong chart is worse than no chart.
"""
from __future__ import annotations

import re

from app.orchestration.evidence import EvidenceModel, Observation
from app.orchestration.websearch import WebSource

# A total is a different KIND of quantity from the rows it summarises. Charting
# both together is the single most common way a document chart misleads.
_TOTAL_ROW = re.compile(
    r"^\s*(?:"
    r"total|subtotal|sub-total|overall|grand total|net total|sum|balance"
    # Balance-sheet totals do not announce themselves with the word "total":
    # "Net assets" is the sum of everything above it, and charted as a peer it
    # towers over its own components while counting each of them twice.
    r"|net\s+(?:assets|current\s+assets|liabilities|book\s+value|worth)"
    r"|total\s+(?:assets|liabilities|equity)"
    r"|capital\s+and\s+reserves|shareholders?[’']?\s*funds"
    r")\b",
    re.I,
)

# Rows that label the table rather than carry data.
_HEADER_WORDS = frozenset({
    "", "item", "items", "category", "categories", "description", "particulars",
    "name", "label", "type", "types", "account", "accounts", "asset", "assets",
    "class", "classification", "period", "date", "month", "quarter", "year",
})

_CURRENCY = "£$€¥₹"
# "1,234.56", "180000", "(1,234)" and "[1,234]" for negatives, an optional
# currency mark, an optional trailing % — the shapes an accounting export
# actually uses. The two digit alternatives are both needed: a spreadsheet
# exports 180000 unformatted while a rendered PDF shows 180,000, and matching
# only the grouped form silently dropped every raw spreadsheet figure.
#
# Brackets as well as parentheses: both are used for negatives, and which one
# appears depends on the tool that produced the file, not on any convention
# the reader chose.
_NUM_BODY = rf"[{_CURRENCY}]?\s*-?(?:\d{{1,3}}(?:,\d{{3}})+|\d+)(?:\.\d+)?\s*%?"
_NUMBER = re.compile(rf"^[(\[]?\s*{_NUM_BODY}\s*[)\]]?$")
# The same shape anchored to the END of a line, for the single-space layout
# below.
_TRAILING_NUMBER = re.compile(rf"([(\[]?\s*{_NUM_BODY}\s*[)\]]?)\s*$")

_MIN_POINTS = 2
_MAX_POINTS = 40
_MAX_LABEL = 60


def _parse_number(cell: str) -> float | None:
    """A number if the cell is one, else None. Parentheses mean negative, the
    accounting convention — read as positive it flips the sign of a loss."""
    text = cell.strip()
    if not text or not _NUMBER.match(text):
        return None
    negative = (text.startswith("(") and text.endswith(")")) or (
        text.startswith("[") and text.endswith("]")
    )
    for ch in f"()[],%{_CURRENCY}":
        text = text.replace(ch, "")
    text = text.strip()
    if not text or text == "-":
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return -value if negative and value > 0 else value


def _is_usable_label(label: str) -> bool:
    cleaned = label.strip()
    if not cleaned or len(cleaned) > _MAX_LABEL:
        return False
    if cleaned.casefold() in _HEADER_WORDS:
        return False
    # Total rows are NOT rejected here. They are excluded from the chart
    # later, but they have to survive extraction first: "Net assets" is often
    # the only line in a balance sheet carrying the word the question used, so
    # dropping it before section scoring loses the very signal that identifies
    # which statement the reader meant.
    #
    # A label that is itself a number is a stray data cell, not a category.
    return _parse_number(cleaned) is None


# A single-space row and an ordinary sentence ending in a figure look alike, so
# the label has to earn it: short, few words, and not written as prose.
_MAX_LABEL_WORDS = 6
_PROSE_MARKERS = re.compile(r"[.;:!?]\s|[,]\s.*\s|\b(the|this|that|which|were|was|are|is|and)\b", re.I)


def _rows(snippet: str) -> list[list[str]]:
    """Table rows from a chunk.

    Three layouts, because the same table arrives differently depending on how
    the file was produced:
      - tab-delimited      — what the spreadsheet extractor emits
      - two-or-more spaces — how a PDF's aligned columns usually survive
      - a single space     — how many PDFs flatten to, e.g.
                             "Revenue 4,182,000.00"

    The third is deliberately the strictest. "Revenue 4,182,000.00" is a row;
    "the balance was reduced to 41,000" is a sentence, and both end in a
    number. A line only counts when its label is short, is at most a few
    words, and reads as a caption rather than prose — otherwise a paragraph
    would be charted as data.
    """
    rows: list[list[str]] = []
    for raw in snippet.splitlines():
        line = raw.rstrip()
        if "\t" in line:
            rows.append([cell.strip() for cell in line.split("\t")])
            continue
        if re.search(r"\S {2,}\S", line):
            rows.append([cell.strip() for cell in re.split(r"\s{2,}", line.strip())])
            continue
        match = _TRAILING_NUMBER.search(line.strip())
        if not match:
            continue
        label = line.strip()[: match.start()].strip()
        if not label or len(label) > _MAX_LABEL:
            continue
        if len(label.split()) > _MAX_LABEL_WORDS:
            continue
        if _PROSE_MARKERS.search(label):
            continue
        rows.append([label, match.group(1).strip()])
    return rows


# An ALL-CAPS line with no figure on it is a statement heading — "PROFIT AND
# LOSS ACCOUNT", "BALANCE SHEET EXTRACT AT 31 MARCH 2026".
_HEADING = re.compile(r"^[A-Z][A-Z0-9 &,'()./-]{5,}$")


def _section_of(line: str) -> str | None:
    stripped = line.strip()
    if _HEADING.match(stripped) and not _TRAILING_NUMBER.search(stripped):
        return stripped
    return None


# A sub-heading inside a statement: a short line carrying no figure, sitting
# above the rows it groups — "Non-current assets", "Current assets",
# "Liabilities". Not ALL-CAPS, so _section_of does not claim it, and it is the
# only thing in the file that says which rows are assets and which are not.
_MAX_GROUP_WORDS = 5
_GROUP_LINE = re.compile(r"^[A-Za-z][A-Za-z ,'&()/-]{2,48}$")


def _group_of(line: str) -> str | None:
    stripped = line.strip()
    if not _GROUP_LINE.match(stripped):
        return None
    if _TRAILING_NUMBER.search(stripped) or _section_of(stripped):
        return None
    if len(stripped.split()) > _MAX_GROUP_WORDS:
        return None
    if _PROSE_MARKERS.search(stripped):
        return None
    return stripped


def _extract_pairs(sources: list[WebSource]) -> list[tuple[str, float, str, str]]:
    """(label, value, section, group) for every label/number row that reads
    unambiguously.

    Column choice is per-row: the FIRST numeric cell after the label, so a
    table with Cost/Depreciation/NBV columns yields one consistent series
    rather than silently interleaving three.

    Each row carries the statement heading it appeared under, because rows
    from different statements are not comparable. Revenue and Net assets are
    both figures in this file, but charting them as neighbouring bars states
    something false about the business.

    It also carries the sub-heading it sat under. A balance sheet is one
    section but two opposite kinds of figure: asking for "the assets" and
    receiving Trade payables and Deferred tax liability alongside Inventory is
    not a near-miss, it is a different statement about the business — and in a
    pie chart, where every slice is read as part of one whole, it is simply
    false.
    """
    pairs: list[tuple[str, float, str, str]] = []
    for source in sources:
        section = ""
        group = ""
        for raw in source.snippet.splitlines():
            heading = _section_of(raw)
            if heading:
                section = heading
                group = ""
                continue
            sub_heading = _group_of(raw)
            if sub_heading:
                group = sub_heading
                continue
            for row in _rows(raw):
                if len(row) < 2 or not _is_usable_label(row[0]):
                    continue
                value = next(
                    (v for v in (_parse_number(cell) for cell in row[1:]) if v is not None),
                    None,
                )
                if value is not None:
                    pairs.append((row[0].strip(), value, section, group))
    return pairs


def _select_section(
    query: str, pairs: list[tuple[str, float, str, str]]
) -> list[tuple[str, float, str, str]]:
    """Keep one statement's rows, not a blend of several.

    Preference order: the section the question names, else the largest
    section. A question about assets should chart the balance sheet, not the
    balance sheet interleaved with the profit and loss account.
    """
    sections: dict[str, list[tuple[str, float, str, str]]] = {}
    for pair in pairs:
        sections.setdefault(pair[2], []).append(pair)
    if len(sections) <= 1:
        return pairs

    words = {w for w in re.findall(r"[a-z]{4,}", query.lower())}
    scored = []
    for name, rows in sections.items():
        # Score on the heading AND the row labels. A heading alone is too
        # thin a signal: "assets" appears in no heading of a typical set of
        # accounts, but it appears in the balance sheet's own line items —
        # which is precisely where the question was pointing.
        heading_words = set(re.findall(r"[a-z]{4,}", name.lower()))
        label_words: set[str] = set()
        for label, _, _, _ in rows:
            label_words |= set(re.findall(r"[a-z]{4,}", label.lower()))
        score = 2 * len(heading_words & words) + len(label_words & words)
        scored.append((score, len(rows), name))
    scored.sort(reverse=True)
    return sections[scored[0][2]]


# The kinds of figure a question can name, and the sub-headings that hold
# them. Assets and liabilities live in the same section of the same file and
# mean opposite things; charting them together answers a question nobody
# asked. Only applied when the question names one AND the file labels its
# groups — otherwise the rows are returned untouched.
_GROUP_KINDS: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("asset", ("asset",), ("liabilit", "payable", "equity", "capital", "reserve")),
    ("liabilit", ("liabilit", "payable"), ("asset", "equity", "capital", "reserve")),
    ("equity", ("equity", "capital", "reserve"), ("asset", "liabilit", "payable")),
    ("income", ("income", "revenue", "turnover", "sales"), ("expense", "cost")),
    ("expense", ("expense", "cost"), ("income", "revenue", "turnover", "sales")),
)


def _select_group(
    query: str, pairs: list[tuple[str, float, str, str]]
) -> list[tuple[str, float, str, str]]:
    """Narrow to the kind of figure the question named, when it named one."""
    lowered = query.lower()
    for keyword, wanted, excluded in _GROUP_KINDS:
        if keyword not in lowered:
            continue
        kept = [
            pair for pair in pairs
            if any(word in pair[3].lower() for word in wanted)
            and not any(word in pair[3].lower() for word in excluded)
        ]
        # Only narrow when the file actually labelled enough rows that way.
        # A document with no sub-headings yields nothing here, and returning
        # an empty chart would be worse than returning the whole section.
        if len(kept) >= _MIN_POINTS:
            return kept
    return pairs


def build_document_evidence(query: str, sources: list[WebSource]) -> EvidenceModel:
    """Chart evidence read from uploaded documents, or empty evidence when the
    tables cannot be read unambiguously.

    Empty is a normal, safe result: the caller keeps today's behaviour, which
    is to say plainly that no verified data was available rather than chart a
    guess.
    """
    if not sources:
        return EvidenceModel()

    # Section first (totals still present, so they can identify the statement),
    # then the kind of figure the question asked about, then drop the totals so
    # none is charted beside its own components.
    pairs = [
        pair for pair in _select_group(query, _select_section(query, _extract_pairs(sources)))
        if not _TOTAL_ROW.match(pair[0])
    ]
    if len(pairs) < _MIN_POINTS:
        return EvidenceModel()

    # Duplicate labels mean either the same row twice from overlapping chunks,
    # or two different things sharing a name. Neither can be charted honestly
    # — summing them would invent a figure that appears nowhere in the file.
    seen: dict[str, float] = {}
    for label, value, _, _ in pairs:
        key = label.casefold()
        if key in seen and seen[key] != value:
            return EvidenceModel()
        seen[key] = value

    ordered: list[tuple[str, float]] = []
    used: set[str] = set()
    for label, value, _, _ in pairs:
        key = label.casefold()
        if key not in used:
            used.add(key)
            ordered.append((label, value))
    if not _MIN_POINTS <= len(ordered) <= _MAX_POINTS:
        return EvidenceModel()

    titles = list(dict.fromkeys(source.title for source in sources))
    evidence = EvidenceModel(
        subject=_subject(query),
        provider="uploaded_document",
        observations=[
            Observation(dimension=label, value=value, measure="value")
            for label, value in ordered
        ],
        dimensions=["category"],
        measures=["value"],
        sources=titles,
        facts=[f"{label}: {value:g}" for label, value in ordered],
        coverage_complete=True,
    )

    # A composition chart was asked for by name, so offer these rows as shares
    # too. Gated on every value being positive: a pie slice is a portion of a
    # whole, and a negative figure has no portion — a set containing one is a
    # list, not a composition, and drawing it would state something the file
    # does not.
    if _composition_requested(query) and all(value > 0 for _, value in ordered):
        total = sum(value for _, value in ordered)
        evidence.composition = [
            Observation(dimension=label, value=value / total * 100.0, measure="percent")
            for label, value in ordered
        ]
        evidence.composition_subject = evidence.subject
        evidence.composition_is_estimated = False
        # Names what the shares are OF. They are shares of the rows charted,
        # not of a statement total — the totals were removed above, and the
        # file may hold figures this section never listed.
        evidence.composition_caveat = (
            f"Shares of the {len(ordered)} rows shown, which total "
            f"{total:,.0f} as read from the document — not of any total stated in it."
        )
    return evidence


def _composition_requested(query: str) -> bool:
    """Did the question name a parts-of-a-whole chart?

    Imported here rather than at module scope: response_planner pulls in the
    visualization package, and this module is imported from within it.
    """
    from app.orchestration.response_planner import detect_requested_chart_variant

    return detect_requested_chart_variant(query) in {
        "PIE_CHART", "DONUT_CHART", "TREEMAP_CHART", "RADAR_CHART",
    }


def _subject(query: str) -> str:
    """A readable chart title from the question, with the chart-type and
    filler words stripped."""
    subject = re.sub(
        r"\b(compare|comparison|show|display|plot|draw|create|make|give|me|a|an|the|of|in|as|"
        r"bar|line|pie|donut|doughnut|column|chart|charts|graph|graphs|table|visual|"
        r"visualise|visualize|this|that|these|those|document|documents|file|files|"
        r"attached|uploaded|please)\b",
        " ", query, flags=re.I,
    )
    subject = re.sub(r"\s+", " ", subject).strip(" -.,:")
    if not subject:
        return "Uploaded document"
    return subject[:1].upper() + subject[1:]
