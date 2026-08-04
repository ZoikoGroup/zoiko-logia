"""
The validated dataset every visual is derived from.

presentation.py already had the property that matters: a chart's numbers come
from a table in the answer that passed Checkpoint C, never from anything the
model emitted as chart data. What it lacked was an addressable artifact in
between — so nothing could state which column carried which unit, which row
came from which citation, or whether the same evidence would produce the same
visual twice.

This module is that artifact. A Dataset is:

  * columns, each with a declared unit and dtype
  * rows of already-validated cell text
  * per-ROW provenance, not per-dataset — "every value is cited" is only a
    checkable claim if each row names its own source
  * a content hash over the data alone, so a visual is reproducible and
    cacheable, and an audit export can be compared to what a user saw

Two rules follow from having it, and they are the reason it exists:

1. A visual kind is chosen by PRECONDITIONS over the dataset's shape, never
   by asking a model what kind of chart to draw. Query types are unbounded;
   dataset shapes are a small closed set. That is what makes the selection
   hold across a diverse query mix without enumerating query categories.
2. A dataset that fails validation produces no visual at all. It never
   produces a partially-correct one. The table is already rendered as
   accessible text, so the fallback costs the reader nothing.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Literal

# The kinds a dataset can legitimately support. Deliberately smaller than the
# set of renderers anyone might want: a kind exists here only when there is a
# dataset shape that can satisfy its preconditions. Adding a kind with no
# reachable precondition produces a renderer that never fires.
VisualKind = Literal["metric", "bar", "line", "area", "donut", "table"]

ColumnType = Literal["category", "numeric", "temporal", "text"]

# A dataset wider or longer than this is a table, not a chart. Both bounds
# match what _chart_from_table already enforced; they are stated here so a
# new kind cannot quietly acquire different limits.
MAX_CHART_ROWS = 12
MIN_CHART_ROWS = 2
MAX_CHART_COLUMNS = 6
MAX_CHART_SERIES = 4
# A line needs enough points to describe a trend. Two points describe a
# difference, which is a bar comparison.
MIN_LINE_POINTS = 2

_TEMPORAL_HEADER = re.compile(r"\b(period|quarter|month|year|date)\b", re.I)
_YEAR_VALUE = re.compile(r"^\d{4}$")
_NUMBER = re.compile(
    r"^\s*(?P<open>\()?\s*(?P<sign>-|−)?\s*(?P<currency>[$£€])?\s*"
    r"(?P<number>\d[\d,]*(?:\.\d+)?)\s*(?P<percent>%)?\s*(?P<code>USD|GBP|EUR)?\s*\)?\s*$",
    re.I,
)


@dataclass(frozen=True)
class DatasetColumn:
    name: str
    dtype: ColumnType
    # "%", "USD", "GBP", "EUR", or "" when the values carry no unit. Declared
    # per column so a mixed-unit axis is a precondition failure rather than a
    # chart nobody notices is wrong — plotting GBP beside a percentage is the
    # most common silently-incorrect chart in financial reporting.
    unit: str = ""


@dataclass(frozen=True)
class Dataset:
    dataset_id: str
    title: str
    columns: tuple[DatasetColumn, ...]
    # Cell text exactly as it appeared in the validated answer. Kept as text
    # rather than parsed numbers so the rendered visual and the accessible
    # table cannot disagree about a rounding.
    rows: tuple[tuple[str, ...], ...]
    # One entry per row, each naming the citations that support it. Empty
    # tuples are permitted and are what `unsupported_rows` reports — the
    # dataset records what provenance exists, and validation decides whether
    # that is enough.
    row_provenance: tuple[tuple[str, ...], ...] = ()
    source_kind: Literal["answer_table", "live_metric", "record_list"] = "answer_table"
    # Set when rows were dropped or aggregated to fit a rendering bound, so a
    # reader is told "20 of 340 rows" instead of silently seeing 20.
    total_row_count: int | None = None

    @property
    def numeric_columns(self) -> tuple[int, ...]:
        return tuple(i for i, column in enumerate(self.columns) if column.dtype == "numeric")

    @property
    def is_truncated(self) -> bool:
        return self.total_row_count is not None and self.total_row_count > len(self.rows)

    @property
    def units(self) -> frozenset[str]:
        return frozenset(
            column.unit for column in self.columns
            if column.dtype == "numeric" and column.unit
        )

    @property
    def content_hash(self) -> str:
        """Hash of the DATA, not the envelope.

        Deliberately excludes dataset_id, title and provenance: a cache keyed
        on this must hit when the same figures are presented again, and ids
        and titles vary between requests that carry identical data. Including
        a fetch timestamp here — the obvious mistake — would make the hit
        rate zero.
        """
        payload = "␟".join(
            (
                "␞".join(f"{column.name}␝{column.dtype}␝{column.unit}"
                              for column in self.columns),
                *("␞".join(row) for row in self.rows),
            )
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def unsupported_rows(self) -> tuple[int, ...]:
        if not self.row_provenance:
            return ()
        return tuple(
            index for index, citations in enumerate(self.row_provenance) if not citations
        )


@dataclass(frozen=True)
class DatasetIssue:
    code: str
    detail: str


@dataclass(frozen=True)
class VisualDecision:
    """Why a dataset renders the way it does.

    `kind` is never None: a dataset that supports no chart still supports a
    table, and a caller must not have to handle an absent decision. `reasons`
    records what was rejected, which is what makes a missing chart
    explainable instead of mysterious.
    """
    kind: VisualKind
    reasons: tuple[str, ...] = ()
    issues: tuple[DatasetIssue, ...] = ()

    @property
    def renders_chart(self) -> bool:
        return self.kind in {"bar", "line", "area", "donut"}


def parse_numeric(cell: str) -> tuple[str, str] | None:
    """(canonical value, unit) or None when the cell is not a single number.

    Shared with presentation.py's own parser so the dataset's view of what
    counts as numeric cannot drift from the chart builder's.
    """
    match = _NUMBER.match(cell.strip())
    if not match:
        return None
    raw = match.group("number").replace(",", "")
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return None
    if match.group("sign") or match.group("open"):
        value = -value
    currency = match.group("currency") or (match.group("code") or "").upper()
    unit = "%" if match.group("percent") else currency
    return format(value, "f"), unit


_CURRENCY_UNITS = {"$": "USD", "£": "GBP", "€": "EUR"}


def _normalise_unit(unit: str) -> str:
    return _CURRENCY_UNITS.get(unit, unit)


def _classify_column(name: str, values: list[str], is_first: bool) -> DatasetColumn:
    parsed = [parse_numeric(value) for value in values]
    complete = all(item is not None for item in parsed) and bool(parsed)
    units = {_normalise_unit(item[1]) for item in parsed if item is not None and item[1]}

    if is_first:
        # The leading column labels the rows. A year is a temporal label, not
        # a measure — charting it as a series is the classic mistake.
        #
        # The VALUES override a temporal-looking header, not the other way
        # round. A column headed "Year" holding 1, 2, 3, 4, 5 — an ordinal
        # sequence like MACRS recovery years — is not a date axis, and
        # treating it as one produced a dataset that claimed an area chart
        # while the chart builder correctly declined to draw it. Header
        # wording is a hint; what is in the cells is the fact.
        all_years = complete and all(_YEAR_VALUE.match(value.strip()) for value in values)
        if all_years:
            return DatasetColumn(name=name, dtype="temporal")
        if complete:
            # Bare numbers in the label column are data, not labels. Marked
            # numeric so select_visual_kind() rejects the dataset for want of
            # a usable axis rather than plotting a measure against itself.
            return DatasetColumn(name=name, dtype="numeric", unit=next(iter(units), ""))
        if _TEMPORAL_HEADER.search(name):
            return DatasetColumn(name=name, dtype="temporal")
        return DatasetColumn(name=name, dtype="category")

    if complete and len(units) <= 1:
        return DatasetColumn(name=name, dtype="numeric", unit=next(iter(units), ""))
    # An incomplete or mixed-unit column stays textual. It remains visible in
    # the accessible table; it is simply not plottable.
    return DatasetColumn(name=name, dtype="text")


def build_dataset(
    *,
    dataset_id: str,
    title: str,
    headers: list[str],
    rows: list[list[str]],
    row_provenance: list[tuple[str, ...]] | None = None,
    source_kind: Literal["answer_table", "live_metric", "record_list"] = "answer_table",
    total_row_count: int | None = None,
) -> Dataset:
    columns = tuple(
        _classify_column(header, [row[index] for row in rows], is_first=index == 0)
        for index, header in enumerate(headers)
    )
    provenance = tuple(tuple(item) for item in (row_provenance or ()))
    return Dataset(
        dataset_id=dataset_id,
        title=title,
        columns=columns,
        rows=tuple(tuple(row) for row in rows),
        row_provenance=provenance,
        source_kind=source_kind,
        total_row_count=total_row_count,
    )


def validate_dataset(dataset: Dataset, *, require_provenance: bool = False) -> tuple[DatasetIssue, ...]:
    """Structural faults that disqualify a dataset from any chart.

    Not a relevance check. A dataset can be perfectly valid here and still be
    the wrong evidence for the question — this layer guarantees a visual
    faithfully represents its dataset, never that the dataset is the right
    one. Correctness lives upstream in retrieval and the authority hierarchy.
    """
    issues: list[DatasetIssue] = []

    if not dataset.rows:
        issues.append(DatasetIssue("empty_dataset", "no rows"))
    if len({len(row) for row in dataset.rows} | {len(dataset.columns)}) > 1:
        issues.append(DatasetIssue("ragged_rows", "row width does not match the column count"))
    if len(dataset.units) > 1:
        issues.append(DatasetIssue(
            "mixed_units",
            f"numeric columns declare more than one unit: {sorted(dataset.units)}",
        ))
    if dataset.row_provenance and len(dataset.row_provenance) != len(dataset.rows):
        issues.append(DatasetIssue("provenance_row_mismatch", "one provenance entry per row is required"))
    if require_provenance:
        if not dataset.row_provenance:
            issues.append(DatasetIssue("provenance_missing", "no row provenance recorded"))
        elif dataset.unsupported_rows():
            issues.append(DatasetIssue(
                "rows_without_citation",
                f"rows without a citation: {list(dataset.unsupported_rows())}",
            ))
    return tuple(issues)


def select_visual_kind(
    dataset: Dataset,
    *,
    presentation_hint: str = "",
    allow_chart: bool = True,
    require_provenance: bool = False,
) -> VisualDecision:
    """Deterministic kind selection from the dataset's shape.

    `presentation_hint` comes from the classifier and only ever breaks a tie
    the data leaves open (is this a composition or a magnitude comparison?).
    It cannot promote a dataset past a precondition it fails — the data
    decides what is drawable, the reader's intent decides which of the
    drawable options to use.
    """
    issues = validate_dataset(dataset, require_provenance=require_provenance)
    if issues:
        return VisualDecision("table", tuple(issue.code for issue in issues), issues)

    reasons: list[str] = []
    # Every chart needs something to plot AGAINST. A leading column that is
    # itself a measure leaves no axis, and plotting it against its own values
    # is meaningless — the chart builder already declined these, so saying so
    # here keeps the emitted block and the rendered chart in agreement.
    if dataset.columns and dataset.columns[0].dtype not in {"category", "temporal"}:
        return VisualDecision("table", ("no_usable_axis",))

    numeric = dataset.numeric_columns
    if not numeric:
        return VisualDecision("table", ("no_complete_numeric_column",))

    # One row is one number. A chart with a single data point is a stat.
    if len(dataset.rows) == 1:
        return VisualDecision("metric", ("single_row",))

    if not allow_chart:
        return VisualDecision("table", ("chart_not_requested",))
    if len(dataset.rows) < MIN_CHART_ROWS:
        reasons.append("too_few_rows")
    if len(dataset.rows) > MAX_CHART_ROWS:
        reasons.append("too_many_rows")
    if len(dataset.columns) > MAX_CHART_COLUMNS:
        reasons.append("too_many_columns")
    if reasons:
        return VisualDecision("table", tuple(reasons))

    unit = next(iter(dataset.units), "")
    is_temporal = dataset.columns[0].dtype == "temporal"

    # Composition is opt-in. Two non-negative values are a comparison, not a
    # proportion, however tempting a donut looks — so this needs either
    # percentage units or an explicit compositional signal.
    if not is_temporal and len(dataset.columns) == 2 and len(numeric) == 1:
        if unit == "%" or presentation_hint == "compositional":
            return VisualDecision("donut", ("compositional",))

    if is_temporal:
        if len(dataset.rows) < MIN_LINE_POINTS:
            return VisualDecision("table", ("too_few_points_for_a_trend",))
        return VisualDecision("area" if len(numeric) == 1 else "line", ("temporal_axis",))

    return VisualDecision("bar", ("categorical_axis",))
