"""
Trial extractor for PolicyEngine-US's parameter YAML files (a large,
well-structured dataset of US federal/state tax and benefit program rules —
see https://github.com/PolicyEngine/policyengine-us,
policyengine_us/parameters/**/*.yaml). Each file has a plain-English
`description`, dated historical `values`, and often a `metadata.reference`
with a real legal citation (title + URL).

Unlike the IRS Direct File Fact Dictionary (XML business-rule logic), these
files are already close to prose — this extractor is much simpler and
doesn't need to filter out derivation logic.

This is a standalone trial — it does not write to the database or register
anything in source_library. Given the scale here (9,873 files across the
whole repo vs. 35 for Direct File), it's meant to be run against ONE
subfolder at a time (e.g. gov/irs/deductions/), not the whole parameters/
tree, until scope is deliberately decided.

Usage:
    python3 scripts/extract_policyengine_params.py <path-to-topic-folder>
"""
import sys
from pathlib import Path

import yaml


class _TolerantSafeLoader(yaml.SafeLoader):
    """PolicyEngine uses `0000-01-01` as a literal "since the beginning of
    time" placeholder key in many `values:` maps (e.g. .../cdcc/phase_out/
    amended_structure/applies.yaml) — real, deliberate data, not a typo.
    PyYAML's default timestamp resolver tries to build a real
    datetime.date(0, 1, 1) for it and raises ValueError (year 0 is out of
    range), which previously caused this extractor to skip the ENTIRE file
    (confirmed losing 30%+ of files in some folders, including real dollar
    thresholds with live legal citations). Falls back to the raw string for
    any date it can't construct, instead of failing the whole document."""

    @staticmethod
    def _construct_yaml_timestamp(loader, node):
        try:
            return yaml.SafeLoader.construct_yaml_timestamp(loader, node)
        except ValueError:
            return loader.construct_scalar(node)


_TolerantSafeLoader.add_constructor(
    "tag:yaml.org,2002:timestamp", _TolerantSafeLoader._construct_yaml_timestamp
)


_RESERVED_TOP_KEYS = {"description", "metadata", "values", "brackets"}

# How many dated history entries to keep per value/breakdown key — see the
# comment in _format_values for why 8 (not fewer).
_MAX_HISTORY_ENTRIES = 8


def extract_params(folder: str) -> list[dict]:
    params = []
    for path in sorted(Path(folder).rglob("*.yaml")):
        try:
            with open(path) as f:
                doc = yaml.load(f, Loader=_TolerantSafeLoader)
        except Exception as exc:
            print(f"  SKIPPED (parse error): {path}: {exc}", file=sys.stderr)
            continue
        if not isinstance(doc, dict):
            continue

        description = (doc.get("description") or "").strip()
        values = doc.get("values")
        # Graduated/marginal-rate parameters (income tax brackets, etc.) use
        # a completely different top-level shape — a `brackets:` list of
        # {threshold: {...}, rate: {...}} (or {..., amount: {...}} for flat-
        # dollar brackets like CTC's per-child amount) dicts — instead of
        # `values:`. A real gap found while checking live Kriton answers:
        # every file using this shape (70+ files just in the folders
        # already registered, including every state income tax bracket
        # schedule and CTC's actual dollar amounts) was silently extracted
        # as having no values at all.
        brackets = doc.get("brackets")
        metadata = doc.get("metadata") or {}
        label = (metadata.get("label") or "").strip()
        unit = metadata.get("unit", "")
        # Bracket schemas name their unit fields inconsistently
        # (threshold_unit/rate_unit for percentage brackets like income tax,
        # threshold_unit/amount_unit for flat-value brackets like CTC or SSA
        # retirement age) — and crucially, amount_unit isn't always
        # currency. A real bug found via a live Kriton answer: SSA's full
        # retirement age table has threshold_unit=year, amount_unit=month
        # (783 = 65y3mo, not a dollar figure) — guessing "amount key present
        # → dollars" formatted it as "$783" and produced a nonsensical
        # table, which likely also contributed to a repetition-loop failure
        # (confusing data → confused generation).
        threshold_unit = metadata.get("threshold_unit", "")
        value_unit = metadata.get("rate_unit") or metadata.get("amount_unit") or ""
        references = metadata.get("reference") or []

        # A third shape: parameters broken down by a dimension (e.g.
        # filing status) have no `values:`/`brackets:` key at all — the
        # breakdown categories (SINGLE, JOINT, ...) are themselves top-level
        # keys, each holding its own date-dict, flagged by
        # metadata.breakdown (e.g. auto_loan_interest/phase_out/start.yaml).
        breakdown = None
        if values is None and not brackets and metadata.get("breakdown"):
            candidate = {k: v for k, v in doc.items() if k not in _RESERVED_TOP_KEYS}
            if candidate:
                breakdown = candidate

        if not description and not label:
            continue
        if values is None and not brackets and not breakdown:
            continue  # nothing numeric to report — pure description-only entries are covered elsewhere

        params.append({
            "relative_path": str(path.relative_to(Path(folder).parent if Path(folder).parent.exists() else folder)),
            "label": label,
            "description": description,
            "unit": unit,
            "threshold_unit": threshold_unit,
            "value_unit": value_unit,
            "values": values,
            "brackets": brackets,
            "breakdown": breakdown,
            "references": references,
        })
    return params


def _unwrap_date_dict(field):
    """Some bracket sub-fields nest their date history one level deeper,
    under their own `values:` key alongside a sibling `metadata:` key (e.g.
    credits/ctc/amount/base.yaml: `threshold: {values: {...}, metadata:
    {...}}`), instead of being a flat date-dict directly. Unwrap either
    shape into a plain date-dict."""
    if isinstance(field, dict) and isinstance(field.get("values"), dict):
        return field["values"]
    return field


def _most_recent(date_value) -> tuple:
    """Returns (date_str_or_None, value) for the most recent entry in a
    date-keyed dict, or (None, date_value) unchanged if it isn't a dict at
    all (some bracket fields are bare scalars, not date histories)."""
    date_value = _unwrap_date_dict(date_value)
    if not isinstance(date_value, dict):
        return None, date_value
    if not date_value:
        return None, None
    items = sorted(date_value.items(), key=lambda kv: str(kv[0]))
    return items[-1]


def _format_values(values) -> str:
    if values is None:
        return "(no values provided)"
    if isinstance(values, dict):
        # Show the most recent history, not everything — some of these go
        # back to the 1980s and a full dump would blow the per-chunk context
        # budget. _MAX_HISTORY_ENTRIES=8 (not fewer) specifically because a
        # real Kriton test asked "2020 vs today" and got only the current
        # year — most of these dated maps span exactly 2019-2026 (8 years),
        # so a 5-entry cap was silently dropping the older half of exactly
        # the range users ask to compare.
        items = sorted(values.items(), key=lambda kv: str(kv[0]))
        recent = items[-_MAX_HISTORY_ENTRIES:]
        lines = [f"  {date}: {val}" for date, val in recent]
        if len(items) > _MAX_HISTORY_ENTRIES:
            lines.insert(0, f"  (showing {len(recent)} most recent of {len(items)} historical values)")
        return "\n".join(lines)
    return f"  {values}"


def _format_unit_value(val, unit: str) -> str:
    """Formats a number according to its REAL declared unit — never guessed
    from which field name held it. A confirmed bug from a live Kriton
    answer: SSA's full-retirement-age table has threshold_unit=year,
    amount_unit=month (its 'amount' field is months, e.g. 782 = 65y2mo),
    but guessing "amount key present -> dollars" formatted the whole table
    as nonsensical dollar figures ("$1,938", "$782"), and the model then
    visibly struggled/looped trying to make sense of it."""
    if not isinstance(val, (int, float)):
        return str(val)
    if unit == "currency-USD":
        return f"${val:,}"
    if unit == "/1":
        return f"{val * 100:.3f}%"
    if unit:
        return f"{val:,} {unit}"
    return f"{val:,}"


def _format_brackets(brackets, threshold_unit: str = "", value_unit: str = "") -> str:
    if not brackets or not isinstance(brackets, list):
        return "(no bracket values provided)"
    lines = ["  Current bracket schedule (most recent effective threshold/value per bracket):"]
    for i, bracket in enumerate(brackets):
        if not isinstance(bracket, dict):
            continue
        thresh_date, thresh_val = _most_recent(bracket.get("threshold"))
        # Brackets use either 'rate' or 'amount' for the per-bracket value —
        # never both — but which field is present says nothing about its
        # unit; that always comes from threshold_unit/value_unit above.
        value_date, value_val = _most_recent(bracket.get("amount") if "amount" in bracket else bracket.get("rate"))
        thresh_str = _format_unit_value(thresh_val, threshold_unit)
        value_str = _format_unit_value(value_val, value_unit)
        lines.append(
            f"    Bracket {i + 1}: from {thresh_str} (effective {thresh_date or 'unknown'}) "
            f"— value {value_str} (effective {value_date or 'unknown'})"
        )
    return "\n".join(lines)


def _format_breakdown(breakdown) -> str:
    """A real gap found via a live Kriton test: this originally showed only
    the single most-recent value per breakdown key (e.g. filing status) —
    fine for a parameter with one effective date (like the auto-loan
    phase-out threshold), but silently dropped years of real history for
    parameters like the standard deduction, which has a distinct dated
    value per year back to 2019. A user asking "2020 vs today" got a
    context with only the current year in it, and the model looped trying
    to find a 2020 figure that had already been discarded."""
    if not breakdown:
        return "(no values provided)"
    lines = []
    for key, date_dict in breakdown.items():
        if not isinstance(date_dict, dict):
            val_str = f"${date_dict:,}" if isinstance(date_dict, (int, float)) else str(date_dict)
            lines.append(f"  {key}: {val_str}")
            continue
        items = sorted(date_dict.items(), key=lambda kv: str(kv[0]))
        recent = items[-_MAX_HISTORY_ENTRIES:]
        entries = ", ".join(
            f"${val:,} (effective {date})" if isinstance(val, (int, float)) else f"{val} (effective {date})"
            for date, val in recent
        )
        lines.append(f"  {key}: {entries}")
    return "\n".join(lines)


def format_as_text(topic: str, params: list[dict]) -> str:
    lines = [f"# PolicyEngine-US Parameters — {topic}", ""]
    for p in params:
        heading = p["label"] or p["relative_path"]
        lines.append(f"## {heading}")
        lines.append(f"(parameter: {p['relative_path']})")
        if p["description"]:
            lines.append(p["description"])
        if p["unit"]:
            lines.append(f"Unit: {p['unit']}")
        lines.append("Values:")
        if p.get("brackets"):
            lines.append(_format_brackets(p["brackets"], p["threshold_unit"], p["value_unit"]))
        elif p.get("breakdown"):
            lines.append(_format_breakdown(p["breakdown"]))
        else:
            lines.append(_format_values(p["values"]))
        for ref in p["references"]:
            if isinstance(ref, dict) and ref.get("title"):
                href = f" — {ref['href']}" if ref.get("href") else ""
                lines.append(f"Reference: {ref['title']}{href}")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 extract_policyengine_params.py <path-to-topic-folder>")
        sys.exit(1)

    folder = sys.argv[1]
    topic = Path(folder).name
    params = extract_params(folder)
    text = format_as_text(topic, params)

    print(f"Extracted {len(params)} parameters from {folder}", file=sys.stderr)
    print(f"Output length: {len(text)} chars", file=sys.stderr)
    print(text)
