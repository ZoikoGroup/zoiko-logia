"""
Diagrams rendered by a self-hosted Kroki service: swimlane, sequence, Gantt,
BPMN and ER diagrams.

Each is requested by name and stated by the user in their own words — the
same data-honesty rule as extraction.py, nothing is taken from the model:

    swimlane  "...as a swimlane: Clerk: Raise PO -> Manager: Approve PO"
    bpmn      "...as a BPMN diagram: Clerk: Raise PO -> Manager: Approve PO"
              (roles optional, but on every step or on none)
    sequence  "...as a sequence diagram: Clerk -> Manager: Request approval;
               Manager -> Finance: Approve payment"
    gantt     "...as a Gantt chart: Planning: 2026-01-01 to 2026-01-05;
               Fieldwork: 2026-01-06 to 2026-01-20"
    erd       "...as an ERD: Customer has many Invoice; Invoice has many
               Invoice Line"

The first four are carried as PROCESS_FLOW nodes (one readable label per
step) and the ER diagram as EVIDENCE_GRAPH entities and relationships, so the
existing renderers still draw a usable fallback when Kroki is unavailable.

Diagram source is generated here from labels that pass strict validation;
none of the characters PlantUML or BPMN XML treat as syntax can reach it.
See diagram_router.py for the Kroki call.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from xml.sax.saxutils import quoteattr

SWIMLANE, SEQUENCE, GANTT, BPMN, ERD = "swimlane", "sequence", "gantt", "bpmn", "erd"

# capability_id (capabilities.py) -> diagram kind
KROKI_CAPABILITIES: dict[str, str] = {
    "swimlane_diagram": SWIMLANE,
    "sequence_diagram": SEQUENCE,
    "gantt_chart": GANTT,
    "bpmn_diagram": BPMN,
    "er_diagram": ERD,
}
# diagram kind -> Kroki diagram type (its URL path segment)
KROKI_TYPES: dict[str, str] = {SWIMLANE: "plantuml", SEQUENCE: "plantuml", GANTT: "plantuml", ERD: "plantuml", BPMN: "bpmn"}

_MAX_STAGES = 40
_MAX_EDGES = 80
_MAX_GANTT_DAYS = 3 * 366

# No ":", ";", "|", quotes, brackets, "<", ">" or newlines: each is syntax in
# PlantUML or XML, so keeping them out is what makes generated source safe.
_NAME = r"[A-Za-z][\w&/ .'-]{0,39}?"            # role, participant, entity, task
_TEXT = r"[A-Za-z0-9][\w&/ ,.'()-]{0,59}?"      # step or message text
_ARROW_SPLIT = re.compile(r"\s*(?:-->|->|→)\s*")
_STATEMENT_SPLIT = re.compile(r"\s*(?:;|\n)\s*")

_REQUESTS: dict[str, re.Pattern[str]] = {
    SWIMLANE: re.compile(r"\bswim[\s-]?lanes?\b", re.I),
    BPMN: re.compile(r"\bbpmn\b", re.I),
    SEQUENCE: re.compile(r"\bsequence\s+diagram\b", re.I),
    GANTT: re.compile(r"\bgantt\b", re.I),
    ERD: re.compile(r"\b(?:erd|er\s+diagram|entity[\s-]relationship)\b", re.I),
}

_LANE_LABEL = re.compile(rf"^\s*({_NAME})\s*:\s*({_TEXT})\s*$")
_PLAIN_STEP = re.compile(rf"^\s*({_TEXT})\s*$")
_MESSAGE_STATEMENT = re.compile(rf"^\s*({_NAME})\s*(-->|->|→)\s*({_NAME})\s*:\s*({_TEXT})\s*$")
_MESSAGE_LABEL = re.compile(rf"^(\d{{1,2}})\.\s+({_NAME})\s+(-->|->)\s+({_NAME}):\s+({_TEXT})$")
_DATE = r"\d{4}-\d{2}-\d{2}|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}"
_TASK_STATEMENT = re.compile(rf"^\s*({_NAME})\s*:\s*({_DATE})\s*(?:to|until|-|–)\s*({_DATE})\s*$", re.I)
_TASK_LABEL = re.compile(rf"^({_NAME}): (\d{{4}}-\d{{2}}-\d{{2}}) to (\d{{4}}-\d{{2}}-\d{{2}})$")
_ERD_STATEMENT = re.compile(rf"^\s*({_NAME})\s+(has many|has one|belongs to)\s+({_NAME})\s*$", re.I)
_ENTITY_NAME = re.compile(rf"^{_NAME}$")
_EDGE_TYPE = re.compile(r"^[a-z][a-z_]{0,29}$")


def _payload(query: str, kind: str) -> str | None:
    """Text after the first colon that follows the diagram's name."""
    request = _REQUESTS[kind].search(query or "")
    if not request:
        return None
    colon = query.find(":", request.end())
    if colon == -1:
        return None
    return query[colon + 1:].strip().rstrip(".!?")


def _parse_date(text: str) -> date | None:
    text = " ".join(text.split())
    for fmt in ("%Y-%m-%d", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def split_lane_label(label: str) -> tuple[str, str] | None:
    """``"Clerk: Raise PO"`` -> ``("Clerk", "Raise PO")``."""
    match = _LANE_LABEL.match(label or "")
    return (match.group(1).strip(), match.group(2).strip()) if match else None


def _bpmn_steps(labels: list[str]) -> list[tuple[str | None, str]] | None:
    """Roles on every step or on none — a mix would draw a lane-less step."""
    lanes = [split_lane_label(label) for label in labels]
    if all(lanes):
        return [(role, step) for role, step in lanes]
    plain = [_PLAIN_STEP.match(label) for label in labels]
    if all(plain) and not any(":" in label for label in labels):
        return [(None, match.group(1).strip()) for match in plain]
    return None


def _messages(labels: list[str]) -> list[tuple[str, str, str, str]] | None:
    parsed = [_MESSAGE_LABEL.match(label) for label in labels]
    if not all(parsed):
        return None
    return [(m.group(2).strip(), m.group(3), m.group(4).strip(), m.group(5).strip()) for m in parsed]


def _tasks(labels: list[str]) -> list[tuple[str, date, date]] | None:
    tasks = []
    for label in labels:
        match = _TASK_LABEL.match(label)
        if not match:
            return None
        start, end = _parse_date(match.group(2)), _parse_date(match.group(3))
        if start is None or end is None or end < start:
            return None
        tasks.append((match.group(1).strip(), start, end))
    if (max(t[2] for t in tasks) - min(t[1] for t in tasks)).days > _MAX_GANTT_DAYS:
        return None
    return tasks


# ── extraction from the user's query ────────────────────────────────────

def _linear(labels: list[str]) -> tuple[list[str], list[tuple[str, str, str]]] | None:
    if not 2 <= len(labels) <= _MAX_STAGES or len(set(labels)) != len(labels):
        return None
    return labels, [(labels[i], labels[i + 1], "next") for i in range(len(labels) - 1)]


def _extract_steps(query: str, kind: str) -> list[str] | None:
    payload = _payload(query, kind)
    if payload is None:
        return None
    parts = [part.strip() for part in _ARROW_SPLIT.split(payload) if part.strip()]
    if kind == SWIMLANE:
        lanes = [split_lane_label(part) for part in parts]
        return [f"{role}: {step}" for role, step in lanes] if parts and all(lanes) else None
    steps = _bpmn_steps(parts) if parts else None
    if steps is None:
        return None
    return [f"{role}: {step}" if role else step for role, step in steps]


def _extract_messages(query: str) -> list[str] | None:
    payload = _payload(query, SEQUENCE)
    if payload is None:
        return None
    labels = []
    for index, statement in enumerate(s for s in _STATEMENT_SPLIT.split(payload) if s):
        match = _MESSAGE_STATEMENT.match(statement)
        if not match:
            return None
        arrow = "-->" if match.group(2) == "-->" else "->"
        labels.append(f"{index + 1}. {match.group(1).strip()} {arrow} {match.group(3).strip()}: {match.group(4).strip()}")
    return labels


def _extract_tasks(query: str) -> list[str] | None:
    payload = _payload(query, GANTT)
    if payload is None:
        return None
    labels = []
    for statement in (s for s in _STATEMENT_SPLIT.split(payload) if s):
        match = _TASK_STATEMENT.match(statement)
        if not match:
            return None
        start, end = _parse_date(match.group(2)), _parse_date(match.group(3))
        if start is None or end is None:
            return None
        labels.append(f"{match.group(1).strip()}: {start.isoformat()} to {end.isoformat()}")
    return labels if _tasks(labels) else None


def _extract_erd(query: str) -> tuple[list[str], list[tuple[str, str, str]]] | None:
    payload = _payload(query, ERD)
    if payload is None:
        return None
    nodes: list[str] = []
    edges: list[tuple[str, str, str]] = []
    for statement in (s for s in _STATEMENT_SPLIT.split(payload) if s):
        match = _ERD_STATEMENT.match(statement)
        if not match:
            return None
        a, b = match.group(1).strip(), match.group(3).strip()
        for name in (a, b):
            if name not in nodes:
                nodes.append(name)
        edges.append((a, b, match.group(2).lower().replace(" ", "_")))
    if len(nodes) < 2 or not edges or len(nodes) > _MAX_STAGES or len(edges) > _MAX_EDGES:
        return None
    return nodes, edges


def extract_kroki_graph(query: str) -> tuple[list[str], list[tuple[str, str, str]]] | None:
    """Nodes and (source, target, type) edges for a named Kroki diagram whose
    whole payload parses — all or nothing, so no step is silently dropped."""
    for kind in (SWIMLANE, BPMN):
        steps = _extract_steps(query, kind)
        if steps:
            return _linear(steps)
    messages = _extract_messages(query)
    if messages:
        return _linear(messages)
    tasks = _extract_tasks(query)
    if tasks:
        return _linear(tasks)
    return _extract_erd(query)


# ── fallback when the stated structure does not fit the diagram ──────────

_DOWNGRADE_NOTES = {
    SWIMLANE: ("A swimlane needs a role for each step (for example "
               "\"Clerk: Raise PO -> Manager: Approve PO\"); showing a process flow instead."),
    BPMN: ("A BPMN diagram needs steps joined by arrows (for example \"Raise PO -> Approve PO\"), "
           "with a role on every step or on none; showing a process flow instead."),
    SEQUENCE: ("A sequence diagram needs each message written as "
               "\"Clerk -> Manager: Request approval\", separated by semicolons; showing a process flow instead."),
    GANTT: ("A Gantt chart needs each task with its dates, for example "
            "\"Planning: 2026-01-01 to 2026-01-05\", separated by semicolons; showing a process flow instead."),
    ERD: ("An ER diagram needs entity names without special characters; "
          "showing a relationship graph instead."),
}


def downgrade_if_unrenderable(spec) -> None:
    """The diagram was asked for, but the stated steps do not fit it (e.g.
    "as a swimlane: A -> B -> C"). Keep the ordinary flow or graph and say
    why, rather than asking Kroki for a diagram that cannot be built."""
    kind = KROKI_CAPABILITIES.get(spec.capability_id or "")
    if kind is None:
        return
    labels = [node.label for node in spec.nodes]
    by_id = {node.id: node.label for node in spec.nodes}
    edges = [(by_id.get(e.source, e.source), by_id.get(e.target, e.target), e.type) for e in spec.edges]
    if build_source(kind, labels, edges) is not None:
        return
    if kind == ERD:
        spec.capability_id, spec.variant = "evidence_graph", "EVIDENCE_GRAPH"
    else:
        spec.capability_id, spec.variant = "flowchart_basic", "BASIC_FLOWCHART"
    note = _DOWNGRADE_NOTES[kind]
    spec.summary = f"{note} {spec.summary}" if spec.summary else note


# ── diagram source ──────────────────────────────────────────────────────

_THEMES = {
    "light": {"ink": "#17211f", "box": "#f7faf8", "brand": "#16799a", "line": "#c7d0ce"},
    "dark": {"ink": "#e6ecea", "box": "#1f2a28", "brand": "#5fb3cf", "line": "#3a4745"},
}


def _plantuml_header(colors: dict[str, str]) -> list[str]:
    return [
        "skinparam shadowing false",
        "skinparam backgroundColor transparent",
        f"skinparam defaultFontColor {colors['ink']}",
        f"skinparam ArrowColor {colors['brand']}",
        f"skinparam ArrowFontColor {colors['ink']}",
    ]


def _swimlane_source(labels: list[str], colors: dict[str, str]) -> str | None:
    lanes = [split_lane_label(label) for label in labels]
    if not all(lanes):
        return None
    lines = ["@startuml", *_plantuml_header(colors),
             f"skinparam ActivityBackgroundColor {colors['box']}",
             f"skinparam ActivityBorderColor {colors['brand']}",
             f"skinparam SwimlaneBorderColor {colors['line']}",
             f"skinparam SwimlaneTitleFontColor {colors['ink']}",
             f"skinparam ActivityStartColor {colors['brand']}",
             f"skinparam ActivityEndColor {colors['brand']}"]
    current_role = None
    for index, (role, step) in enumerate(lanes):
        if role != current_role:
            lines.append(f"|{role}|")
            current_role = role
        if index == 0:
            lines.append("start")
        lines.append(f":{step};")
    return "\n".join([*lines, "stop", "@enduml"])


def _sequence_source(labels: list[str], colors: dict[str, str]) -> str | None:
    messages = _messages(labels)
    if messages is None:
        return None
    aliases: dict[str, str] = {}
    for sender, _arrow, receiver, _text in messages:
        for name in (sender, receiver):
            aliases.setdefault(name, f"P{len(aliases)}")
    lines = ["@startuml", *_plantuml_header(colors), "hide footbox", "autonumber",
             f"skinparam ParticipantBackgroundColor {colors['box']}",
             f"skinparam ParticipantBorderColor {colors['brand']}",
             f"skinparam ParticipantFontColor {colors['ink']}",
             f"skinparam SequenceLifeLineBorderColor {colors['line']}"]
    lines += [f'participant "{name}" as {alias}' for name, alias in aliases.items()]
    lines += [f"{aliases[s]} {arrow} {aliases[r]} : {text}" for s, arrow, r, text in messages]
    return "\n".join([*lines, "@enduml"])


def _gantt_source(labels: list[str], colors: dict[str, str]) -> str | None:
    tasks = _tasks(labels)
    if tasks is None:
        return None
    first = min(t[1] for t in tasks)
    span = (max(t[2] for t in tasks) - first).days
    lines = ["@startgantt",
             "<style>",
             "ganttDiagram {",
             f"  task {{ FontColor {colors['ink']}; BackGroundColor {colors['box']}; LineColor {colors['brand']} }}",
             f"  timeline {{ FontColor {colors['ink']}; BackgroundColor transparent; LineColor {colors['line']} }}",
             "}",
             "</style>",
             f"Project starts {first.isoformat()}"]
    if span > 366:
        lines.append("printscale monthly")
    elif span > 90:
        lines.append("printscale weekly")
    lines += [f"[{name}] starts {start.isoformat()} and ends {end.isoformat()}" for name, start, end in tasks]
    return "\n".join([*lines, "@endgantt"])


_ERD_LINKS = {"has_many": "||--o{", "has_one": "||--||", "belongs_to": "}o--||"}


def _erd_source(labels: list[str], edges: list[tuple[str, str, str]], colors: dict[str, str]) -> str | None:
    if not all(_ENTITY_NAME.match(label) for label in labels) or len(set(labels)) != len(labels):
        return None
    if not edges or len(edges) > _MAX_EDGES:
        return None
    aliases = {label: f"E{index}" for index, label in enumerate(labels)}
    # Generous spacing: with several links between the same two entities the
    # default gaps put the relationship labels on top of each other.
    lines = ["@startuml", *_plantuml_header(colors), "hide circle", "hide empty members",
             "skinparam nodesep 80", "skinparam ranksep 90",
             f"skinparam ClassBackgroundColor {colors['box']}",
             f"skinparam ClassBorderColor {colors['brand']}",
             f"skinparam ClassFontColor {colors['ink']}"]
    lines += [f'entity "{label}" as {alias}' for label, alias in aliases.items()]
    for source, target, edge_type in edges:
        if source not in aliases or target not in aliases or not _EDGE_TYPE.match(edge_type or ""):
            return None
        link = _ERD_LINKS.get(edge_type, "--")
        lines.append(f"{aliases[source]} {link} {aliases[target]} : {edge_type.replace('_', ' ')}")
    return "\n".join([*lines, "@enduml"])


def _bpmn_source(labels: list[str]) -> str | None:
    """BPMN 2.0 XML with its diagram layout (bpmn-js draws nothing without
    one): start event, one task per step, end event, left to right, with a
    lane per role when roles were given."""
    steps = _bpmn_steps(labels)
    if steps is None:
        return None
    roles: list[str] = []
    for role, _step in steps:
        if role is not None and role not in roles:
            roles.append(role)
    task_w, task_h, event, col, lane_h, x0, y0 = 120, 80, 36, 170, 140, 50, 50
    content_x = x0 + (60 if roles else 0)
    lane_of = [roles.index(role) if role else 0 for role, _step in steps]
    lane_of = [lane_of[0], *lane_of, lane_of[-1]]               # start, tasks, end

    def center(index: int) -> tuple[int, int]:
        return content_x + 60 + index * col, y0 + lane_of[index] * lane_h + lane_h // 2

    ids = ["Start", *[f"Task_{i}" for i in range(len(steps))], "End"]
    flows = [(f"Flow_{i}", ids[i], ids[i + 1]) for i in range(len(ids) - 1)]
    process = ['<bpmn:process id="Process_1" isExecutable="false">']
    if roles:
        process.append('<bpmn:laneSet id="LaneSet_1">')
        for lane_index, role in enumerate(roles):
            refs = "".join(f"<bpmn:flowNodeRef>{ids[i]}</bpmn:flowNodeRef>"
                           for i in range(len(ids)) if lane_of[i] == lane_index)
            process.append(f'<bpmn:lane id="Lane_{lane_index}" name={quoteattr(role)}>{refs}</bpmn:lane>')
        process.append("</bpmn:laneSet>")
    process.append('<bpmn:startEvent id="Start"/>')
    process += [f'<bpmn:task id="Task_{i}" name={quoteattr(step)}/>' for i, (_role, step) in enumerate(steps)]
    process.append('<bpmn:endEvent id="End"/>')
    process += [f'<bpmn:sequenceFlow id="{fid}" sourceRef="{src}" targetRef="{dst}"/>' for fid, src, dst in flows]
    process.append("</bpmn:process>")

    shapes = []
    width = (content_x - x0) + 60 + (len(ids) - 1) * col + 90
    if roles:
        shapes.append(f'<bpmndi:BPMNShape id="Pool_di" bpmnElement="Pool" isHorizontal="true">'
                      f'<dc:Bounds x="{x0}" y="{y0}" width="{width}" height="{len(roles) * lane_h}"/></bpmndi:BPMNShape>')
        shapes += [f'<bpmndi:BPMNShape id="Lane_{i}_di" bpmnElement="Lane_{i}" isHorizontal="true">'
                   f'<dc:Bounds x="{x0 + 30}" y="{y0 + i * lane_h}" width="{width - 30}" height="{lane_h}"/></bpmndi:BPMNShape>'
                   for i in range(len(roles))]
    for index, element in enumerate(ids):
        cx, cy = center(index)
        w, h = (event, event) if element in ("Start", "End") else (task_w, task_h)
        shapes.append(f'<bpmndi:BPMNShape id="{element}_di" bpmnElement="{element}">'
                      f'<dc:Bounds x="{cx - w // 2}" y="{cy - h // 2}" width="{w}" height="{h}"/></bpmndi:BPMNShape>')
    for index, (fid, src, _dst) in enumerate(flows):
        (sx, sy), (tx, ty) = center(index), center(index + 1)
        sx += (event if src == "Start" else task_w) // 2
        tx -= (event if index + 1 == len(ids) - 1 else task_w) // 2
        points = [(sx, sy), (tx, ty)] if sy == ty else [(sx, sy), ((sx + tx) // 2, sy), ((sx + tx) // 2, ty), (tx, ty)]
        waypoints = "".join(f'<di:waypoint x="{x}" y="{y}"/>' for x, y in points)
        shapes.append(f'<bpmndi:BPMNEdge id="{fid}_di" bpmnElement="{fid}">{waypoints}</bpmndi:BPMNEdge>')

    collaboration = ('<bpmn:collaboration id="Collaboration_1">'
                     '<bpmn:participant id="Pool" name="Process" processRef="Process_1"/></bpmn:collaboration>'
                     if roles else "")
    plane_element = "Collaboration_1" if roles else "Process_1"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" '
        'xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" '
        'xmlns:dc="http://www.omg.org/spec/DD/20100524/DC" '
        'xmlns:di="http://www.omg.org/spec/DD/20100524/DI" '
        'id="Definitions_1" targetNamespace="http://bpmn.io/schema/bpmn">'
        f'{collaboration}{"".join(process)}'
        f'<bpmndi:BPMNDiagram id="Diagram_1"><bpmndi:BPMNPlane id="Plane_1" bpmnElement="{plane_element}">'
        f'{"".join(shapes)}</bpmndi:BPMNPlane></bpmndi:BPMNDiagram></bpmn:definitions>'
    )


def build_source(
    kind: str, labels: list[str], edges: list[tuple[str, str, str]] | None = None, theme: str = "light",
) -> str | None:
    """Kroki source for a diagram, or None if anything fails validation —
    nothing unvalidated is ever emitted."""
    if kind not in KROKI_TYPES or not 2 <= len(labels) <= _MAX_STAGES:
        return None
    colors = _THEMES.get(theme, _THEMES["light"])
    if kind == SWIMLANE:
        return _swimlane_source(labels, colors)
    if kind == SEQUENCE:
        return _sequence_source(labels, colors)
    if kind == GANTT:
        return _gantt_source(labels, colors)
    if kind == BPMN:
        return _bpmn_source(labels)
    return _erd_source(labels, edges or [], colors)
