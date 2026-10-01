"""Replace model-written extrema and steady-trend claims with measured facts."""
import math
import re
from dataclasses import dataclass

from app.orchestration.websearch import WebSource


@dataclass(frozen=True)
class SeriesFacts:
    """One normalized set of observations drives both prose and tables."""

    title: str
    points: tuple[tuple[str, float], ...]

    def summary(self) -> str:
        first, last = self.points[0], self.points[-1]
        maximum = max(value for _, value in self.points)
        minimum = min(value for _, value in self.points)
        highs = ", ".join(p for p, v in self.points if v == maximum)
        lows = ", ".join(p for p, v in self.points if v == minimum)
        deltas = [b[1] - a[1] for a, b in zip(self.points, self.points[1:])]
        movement = " The series includes both increases and decreases." if (
            any(d > 0 for d in deltas) and any(d < 0 for d in deltas)
        ) else ""
        def fmt(value: float) -> str:
            # Two decimals, as the answer's tables show them — "11.9894"
            # beside a table of "11.99" reads as a different figure.
            return f"{round(value, 2):g}"

        return (
            f"{self.title}: from {fmt(first[1])} in {first[0]} to {fmt(last[1])} in {last[0]}. "
            f"The maximum is {fmt(maximum)} in {highs}; the minimum is {fmt(minimum)} in {lows}.{movement}"
        )


def series_facts(sources: list[WebSource]) -> list[SeriesFacts]:
    facts = []
    seen = set()
    for source in sources:
        # Only chronological observations belong in a trend summary.
        points = tuple(sorted((p, v) for p, v in (source.series or [])
                              if re.fullmatch(r"\d{4}(?:[-QqM\d]+)?", p) and math.isfinite(v)))
        key = (source.title, points)
        if len(points) < 2 or key in seen:
            continue
        seen.add(key)
        facts.append(SeriesFacts(source.title, points))
    return facts


_SUMMARY_CLAIM = re.compile(
    r"\b(?:peak(?:ed|s)?|maximum|minimum|steadily|steady|"
    r"upward trajectory|downward trajectory|sharp (?:jump|rise|fall|increase|decrease))\b", re.I,
)


_TABLE_PERIOD = re.compile(r"^\s*\|\s*\**(\d{4}(?:[-QqM\d]+)?)\**\s*\|", re.M)


def _shown_periods(fact: SeriesFacts, text: str) -> SeriesFacts:
    """The series narrowed to the periods the answer's own table shows.

    A tool fetches up to 20 years; when the answer tabulates the last 10, a
    summary of all 20 ("maximum 11.99 in 2010") contradicts the table right
    above it. Without such a table the whole retrieved series is described."""
    shown = set(_TABLE_PERIOD.findall(text))
    points = tuple((p, v) for p, v in fact.points if p in shown)
    return SeriesFacts(fact.title, points) if len(points) >= 2 else fact


def ground_series_summary(text: str, sources: list[WebSource]) -> str:
    """Swap sentences claiming a peak, low or steady trend for the summary
    measured from the retrieved series. Tables, chart fences and every other
    sentence are kept; the measured summary is inserted once, where the first
    such claim stood."""
    summaries = [_shown_periods(fact, text).summary() for fact in series_facts(sources)]
    if not summaries:
        return text
    output: list[str] = []
    in_fence = False
    replaced = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            output.append(line)
            continue
        if in_fence or line.lstrip().startswith("|"):
            output.append(line)
            continue
        sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])", line)
        kept = []
        for sentence in sentences:
            if _SUMMARY_CLAIM.search(sentence):
                if not replaced:
                    kept.append("\n\n".join(summaries))
                    replaced = True
            else:
                kept.append(sentence)
        output.append(" ".join(kept))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(output)).strip()
