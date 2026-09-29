"""
Swimlane diagrams — a process flow where every step names who performs it.

The user states the lanes themselves, as ``Role: Step`` stages joined by
arrows:

    "Show the purchase-to-pay process as a swimlane:
     Clerk: Raise PO -> Manager: Approve PO -> Finance: Pay supplier"

Same data-honesty rule as extraction.py: lanes and steps come only from the
user's own query text, never from the model. Each stage is kept as a single
"Role: Step" node label, so the ordinary process-flow renderers still show a
readable flow when the swimlane image cannot be drawn.

The picture itself is rendered by a self-hosted Kroki service (PlantUML
activity diagram) — see diagram_router.py. PlantUML source is generated here
from validated labels only; no caller-supplied text reaches Kroki unchecked.
"""
from __future__ import annotations

import re

SWIMLANE_CAPABILITY_ID = "swimlane_diagram"

_MAX_STAGES = 40
_MAX_ROLE_LEN = 40
_MAX_STEP_LEN = 60

SWIMLANE_REQUEST = re.compile(r"\bswim[\s-]?lanes?\b", re.I)
_ARROW_SPLIT = re.compile(r"\s*(?:-->|->|→)\s*")
# No ":", ";", "|", quotes, brackets or newlines in either part: each of those
# is PlantUML syntax (":" and ";" delimit an activity, "|" a lane), so keeping
# them out here is what makes the generated source safe by construction.
_ROLE = r"[A-Za-z][\w&/ .'-]{0,%d}" % (_MAX_ROLE_LEN - 1)
_STEP = r"[A-Za-z0-9][\w&/ ,.'()-]{0,%d}" % (_MAX_STEP_LEN - 1)
_LANE_LABEL = re.compile(r"^\s*(%s?)\s*:\s*(%s?)\s*$" % (_ROLE, _STEP))


def split_lane_label(label: str) -> tuple[str, str] | None:
    """``"Clerk: Raise PO"`` -> ``("Clerk", "Raise PO")``; None if the label
    does not name a role, or contains characters PlantUML would interpret."""
    match = _LANE_LABEL.match(label or "")
    if not match:
        return None
    role, step = match.group(1).strip(), match.group(2).strip()
    return (role, step) if role and step else None


def extract_swimlane_stages(query: str) -> list[str] | None:
    """Ordered ``"Role: Step"`` labels from an explicit swimlane request.

    Returns None unless the query asks for a swimlane AND every arrow-joined
    stage after the request names its role — a partial parse would silently
    drop steps, so it is all or nothing.
    """
    q = query or ""
    request = SWIMLANE_REQUEST.search(q)
    if not request:
        return None
    payload_start = q.find(":", request.end())
    if payload_start == -1:
        return None
    payload = q[payload_start + 1:].strip().rstrip(".!?")
    parts = [part.strip() for part in _ARROW_SPLIT.split(payload) if part.strip()]
    if not 2 <= len(parts) <= _MAX_STAGES:
        return None
    stages: list[str] = []
    for part in parts:
        lane = split_lane_label(part)
        if lane is None:
            return None
        stages.append(f"{lane[0]}: {lane[1]}")
    return stages


def downgrade_if_laneless(spec) -> None:
    """A swimlane was asked for, but the stages carry no roles (e.g. "as a
    swimlane: A -> B -> C"). Draw the ordinary flowchart and say why, rather
    than a swimlane with every step crammed into one unnamed lane."""
    if all(split_lane_label(node.label) for node in spec.nodes):
        return
    spec.capability_id = "flowchart_basic"
    spec.variant = "BASIC_FLOWCHART"
    note = ("A swimlane needs a role for each step (for example "
            "\"Clerk: Raise PO -> Manager: Approve PO\"); showing a process flow instead.")
    spec.summary = f"{note} {spec.summary}" if spec.summary else note


_THEMES = {
    "light": {"ink": "#17211f", "box": "#f7faf8", "brand": "#16799a", "line": "#c7d0ce"},
    "dark": {"ink": "#e6ecea", "box": "#1f2a28", "brand": "#5fb3cf", "line": "#3a4745"},
}


def build_plantuml(labels: list[str], theme: str = "light") -> str | None:
    """PlantUML activity diagram with one lane per role, in first-seen order.
    None if any label fails validation — nothing unvalidated is emitted."""
    if not 2 <= len(labels) <= _MAX_STAGES:
        return None
    lanes = [split_lane_label(label) for label in labels]
    if any(lane is None for lane in lanes):
        return None
    colors = _THEMES.get(theme, _THEMES["light"])
    lines = [
        "@startuml",
        "skinparam shadowing false",
        "skinparam backgroundColor transparent",
        f"skinparam defaultFontColor {colors['ink']}",
        f"skinparam ActivityBackgroundColor {colors['box']}",
        f"skinparam ActivityBorderColor {colors['brand']}",
        f"skinparam ArrowColor {colors['brand']}",
        f"skinparam SwimlaneBorderColor {colors['line']}",
        f"skinparam SwimlaneTitleFontColor {colors['ink']}",
        f"skinparam ActivityStartColor {colors['brand']}",
        f"skinparam ActivityEndColor {colors['brand']}",
    ]
    current_role = None
    for index, (role, step) in enumerate(lanes):
        if role != current_role:
            lines.append(f"|{role}|")
            current_role = role
        if index == 0:
            lines.append("start")
        lines.append(f":{step};")
    lines += ["stop", "@enduml"]
    return "\n".join(lines)
