"""Compare two upstream-canary reports and surface only what CHANGED.

Run from ``backend``::

    python scripts/diff_provider_health.py previous.json current.json

Why a diff and not just the report: two of Kriton's official sources fail
persistently for reasons no code change can fix (the EU FSF distribution and
the OFAC redirect both refuse this deployment's egress). A job that goes red
every day for those teaches everyone to ignore it, and then the day a
working source breaks, the signal lands in a channel nobody reads.

So the alerting condition is a TRANSITION, not a state:

  * a source that was working and now is not  -> alert
  * a source that was broken and now works    -> report (the fix landed)
  * a source that was broken and still is     -> silence

Exit code 1 means something changed for the worse, which is the only
condition worth interrupting someone for. A persistent, already-known
failure exits 0.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Anything not in this set counts as "not working" for transition purposes.
# "stale" is deliberately included as working-but-degraded rather than
# failed: a source publishing late is a different problem from one that
# cannot be reached, and conflating them makes both harder to act on.
_WORKING = frozenset({"live", "stale", "skipped"})


def _statuses(report: dict) -> dict[str, str]:
    return {item["provider"]: item["status"] for item in report.get("providers", [])}


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _annotate(level: str, message: str) -> None:
    """GitHub Actions annotation, and a plain line elsewhere. Keeps this
    runnable locally without pretending to be in CI."""
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::{level}::{message}")
    else:
        print(f"[{level}] {message}")


def _write_summary(lines: list[str]) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    with open(summary_path, "a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def compare(previous: dict, current: dict) -> dict[str, list[str]]:
    """Classify each provider by how its status CHANGED.

    Pure, so the transition rules can be tested without a filesystem — the
    IO and the GitHub-specific rendering stay in main().
    """
    now = _statuses(current)
    before = _statuses(previous)
    return {
        # A first run, or a report from before a provider existed, must not
        # read as "everything just broke": an unknown previous state is not
        # a regression, so only providers present in both are compared.
        "regressions": sorted(
            name for name, status in now.items()
            if status not in _WORKING and name in before and before[name] in _WORKING
        ),
        "recoveries": sorted(
            name for name, status in now.items()
            if status in _WORKING and name in before and before[name] not in _WORKING
        ),
        "persistent": sorted(
            name for name, status in now.items()
            if status not in _WORKING and name in before and before[name] not in _WORKING
        ),
        "new": sorted(set(now) - set(before)),
    }


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2

    previous = _load(Path(argv[0]))
    current = _load(Path(argv[1]))
    if not current:
        _annotate("error", "no current provider-health report to compare")
        return 2

    now = _statuses(current)
    before = _statuses(previous)
    changes = compare(previous, current)
    regressions = changes["regressions"]
    recoveries = changes["recoveries"]
    persistent = changes["persistent"]
    new_providers = changes["new"]

    lines = ["## Upstream canary", "", f"Counts: `{current.get('summary', {}).get('counts', {})}`", ""]
    for name in regressions:
        _annotate("warning", f"{name} stopped working (now {now[name]})")
        lines.append(f"- 🔴 **{name}** stopped working — now `{now[name]}`, was `{before[name]}`")
    for name in recoveries:
        _annotate("notice", f"{name} recovered (now {now[name]})")
        lines.append(f"- 🟢 **{name}** recovered — now `{now[name]}`, was `{before[name]}`")
    if persistent:
        lines.append(f"- ⚪ Still failing, already known: {', '.join(persistent)}")
    if new_providers:
        lines.append(f"- 🆕 Not in the previous report: {', '.join(new_providers)}")
    if not (regressions or recoveries):
        lines.append("- No change since the previous run.")

    _write_summary(lines)
    print("\n".join(lines))
    return 1 if regressions else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
