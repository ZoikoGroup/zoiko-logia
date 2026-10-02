"""
Diagrams rendered by a self-hosted Kroki service: swimlane, BPMN, sequence,
Gantt and ER diagrams, plus the UML activity, state, timing, class, object,
use case, component, deployment and package diagrams.

Each is requested by name and stated by the user in their own words — the
same data-honesty rule as extraction.py, nothing is taken from the model:

    swimlane    "...as a swimlane: Clerk: Raise PO -> Manager: Approve PO"
    bpmn        "...as a BPMN diagram: Clerk: Raise PO -> Manager: Approve PO"
    activity    "...as an activity diagram: Receive invoice -> Approve invoice"
                (bpmn and activity: roles optional, on every step or on none)
    sequence    "...as a sequence diagram: Clerk -> Manager: Request approval;
                 Manager -> Finance: Approve payment"
    gantt       "...as a Gantt chart: Planning: 2026-01-01 to 2026-01-05;
                 Fieldwork: 2026-01-06 to 2026-01-20"
    timing      "...as a timing diagram: Invoice: Draft at 0, Approved at 2;
                 Payment: Pending at 2, Cleared at 5"
    erd         "...as an ERD: Customer has many Invoice; Invoice has many Line"
    class       "...as a class diagram: Invoice (number, date); Customer has
                 many Invoice; Credit Note is a Invoice"
    object      "...as an object diagram: Invoice 1001 (amount = 500);
                 Invoice 1001 belongs to Customer Acme"
    state       "...as a state diagram: Draft -> Approved: approve;
                 Approved -> Paid: pay"
    usecase     "...as a use case diagram: Clerk: Enter invoice, Record
                 payment; Manager: Approve payment"
    component   "...as a component diagram: ERP sends to Bank Feed"
    deployment  "...as a deployment diagram: App Server hosts Ledger App;
                 App Server connects to Database Server"
    package     "...as a package diagram: General Ledger contains Journal,
                 Account; Accounts Payable depends on General Ledger"

Step-shaped diagrams are carried as PROCESS_FLOW nodes (one readable label
per step) and the rest as EVIDENCE_GRAPH nodes and typed edges, so the
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
ACTIVITY, STATE, TIMING, CLASS, OBJECT = "activity", "state", "timing", "class", "object"
USECASE, COMPONENT, DEPLOYMENT, PACKAGE = "usecase", "component", "deployment", "package"

# capability_id (capabilities.py) -> diagram kind. Timing, object, deployment
# and package diagrams have no entry of their own in image_taxonomy.py, so
# their capabilities use the nearest existing one.
KROKI_CAPABILITIES: dict[str, str] = {
    "swimlane_diagram": SWIMLANE,
    "sequence_diagram": SEQUENCE,
    "gantt_chart": GANTT,
    "bpmn_diagram": BPMN,
    "er_diagram": ERD,
    "activity_diagram": ACTIVITY,
    "state_diagram": STATE,
    "event_timeline": TIMING,
    "class_diagram": CLASS,
    "node_link_diagram": OBJECT,
    "use_case_diagram": USECASE,
    "component_diagram": COMPONENT,
    "system_architecture": DEPLOYMENT,
    "dependency_diagram": PACKAGE,
}
# diagram kind -> Kroki diagram type (its URL path segment)
KROKI_TYPES: dict[str, str] = {kind: "plantuml" for kind in KROKI_CAPABILITIES.values()} | {BPMN: "bpmn"}
# Kinds carried as EVIDENCE_GRAPH; the others are PROCESS_FLOW.
GRAPH_KINDS = frozenset({ERD, STATE, CLASS, OBJECT, USECASE, COMPONENT, DEPLOYMENT, PACKAGE})

_MAX_STAGES = 40
_MAX_EDGES = 80
_MAX_FIELDS = 15
_MAX_GANTT_DAYS = 3 * 366

# No ":", ";", "|", quotes, brackets, braces, "<", ">", "=" or newlines: each
# is syntax in PlantUML or XML, so keeping them out is what makes generated
# source safe.
_NAME = r"[A-Za-z][\w&/ .'-]{0,39}?"            # role, participant, entity, task
_TEXT = r"[A-Za-z0-9][\w&/ ,.'()-]{0,59}?"      # step or message text
_ITEM = r"[A-Za-z0-9][\w&/ .'()-]{0,59}?"       # like _TEXT, but no commas (comma-separated lists)
_FIELD = r"[A-Za-z][\w ]{0,29}?"                # class field or object attribute name
_VALUE = r"[\w.'/-][\w .'/-]{0,29}?"            # object attribute value
_ARROW_SPLIT = re.compile(r"\s*(?:-->|->|→)\s*")
_STATEMENT_SPLIT = re.compile(r"\s*(?:;|\n)\s*")

_REQUESTS: dict[str, re.Pattern[str]] = {
    SWIMLANE: re.compile(r"\bswim[\s-]?lanes?\b", re.I),
    BPMN: re.compile(r"\bbpmn\b", re.I),
    ACTIVITY: re.compile(r"\bactivity\s+diagram\b", re.I),
    SEQUENCE: re.compile(r"\bsequence\s+diagram\b", re.I),
    GANTT: re.compile(r"\bgantt\b", re.I),
    TIMING: re.compile(r"\btiming\s+diagram\b", re.I),
    ERD: re.compile(r"\b(?:erd|er\s+diagram|entity[\s-]relationship)\b", re.I),
    CLASS: re.compile(r"\bclass\s+diagram\b", re.I),
    OBJECT: re.compile(r"\bobject\s+diagram\b", re.I),
    STATE: re.compile(r"\bstate(?:\s+machine)?\s+diagram\b|\bstate\s+machine\b", re.I),
    USECASE: re.compile(r"\buse[\s-]?case\s+diagram\b", re.I),
    COMPONENT: re.compile(r"\bcomponent\s+diagram\b", re.I),
    DEPLOYMENT: re.compile(r"\bdeployment\s+diagram\b", re.I),
    PACKAGE: re.compile(r"\bpackage\s+diagram\b", re.I),
}

_LANE_LABEL = re.compile(rf"^\s*({_NAME})\s*:\s*({_TEXT})\s*$")
_PLAIN_STEP = re.compile(rf"^\s*({_TEXT})\s*$")
_MESSAGE_STATEMENT = re.compile(rf"^\s*({_NAME})\s*(-->|->|→)\s*({_NAME})\s*:\s*({_TEXT})\s*$")
_MESSAGE_LABEL = re.compile(rf"^(\d{{1,2}})\.\s+({_NAME})\s+(-->|->)\s+({_NAME}):\s+({_TEXT})$")
_DATE = r"\d{4}-\d{2}-\d{2}|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}"
_TASK_STATEMENT = re.compile(rf"^\s*({_NAME})\s*:\s*({_DATE})\s*(?:to|until|-|–)\s*({_DATE})\s*$", re.I)
_TASK_LABEL = re.compile(rf"^({_NAME}): (\d{{4}}-\d{{2}}-\d{{2}}) to (\d{{4}}-\d{{2}}-\d{{2}})$")
_TIMING_STATEMENT = re.compile(rf"^\s*({_NAME})\s*:\s*(.+?)\s*$")
_TIMING_ITEM = re.compile(rf"^\s*({_NAME})\s+at\s+(?:day\s+|time\s+|t\s*=?\s*)?(\d{{1,4}})\s*$", re.I)
_TIMING_LABEL = re.compile(rf"^({_NAME}): ({_NAME}) at (\d{{1,4}})$")
_ENTITY_NAME = re.compile(rf"^{_NAME}$")
_EDGE_TYPE = re.compile(r"^[a-z][a-z_]{0,29}$")
_EVENT = re.compile(rf"^{_TEXT}$")
_DECLARATION = re.compile(rf"^\s*({_NAME})\s*\(\s*([^()]*?)\s*\)\s*$")
_FIELD_ITEM = re.compile(rf"^\s*({_FIELD})\s*$")
_ATTRIBUTE_ITEM = re.compile(rf"^\s*({_FIELD})\s*=\s*({_VALUE})\s*$")
_CLASS_LABEL = re.compile(rf"^({_NAME})(?: \(({_FIELD}(?:, {_FIELD})*)\))?$")
_OBJECT_LABEL = re.compile(rf"^({_NAME})(?: \(({_FIELD} = {_VALUE}(?:, {_FIELD} = {_VALUE})*)\))?$")
_USECASE_STATEMENT = re.compile(rf"^\s*({_NAME})\s*:\s*(.+?)\s*$")
_USECASE_ITEM = re.compile(rf"^\s*({_ITEM})\s*$")
_STATE_TRANSITION = re.compile(rf"^\s*({_NAME})\s*(?:-->|->|→)\s*({_NAME})\s*(?::\s*({_TEXT}))?\s*$")

_VERBS: dict[str, str] = {
    ERD: "has many|has one|belongs to",
    CLASS: "has many|has one|belongs to|is an?|uses|depends on",
    OBJECT: "belongs to|links to|references|contains|pays|owns|has",
    COMPONENT: "connects to|sends to|receives from|reads from|writes to|syncs with|depends on|uses|calls|feeds",
    DEPLOYMENT: "hosts|runs on|connects to|backs up to|replicates to|sends to",
    PACKAGE: "depends on|uses|imports",
}


def _relation(kind: str) -> re.Pattern[str]:
    return re.compile(rf"^\s*({_NAME})\s+({_VERBS[kind]})\s+({_NAME})\s*$", re.I)


def _edge_type(verb: str) -> str:
    verb = verb.lower()
    return "is_a" if verb in ("is a", "is an") else verb.replace(" ", "_")


def _payload(query: str, kind: str) -> str | None:
    """Text after the first colon that follows the diagram's name."""
    request = _REQUESTS[kind].search(query or "")
    if not request:
        return None
    colon = query.find(":", request.end())
    if colon == -1:
        return None
    return query[colon + 1:].strip().rstrip(".!?")


def _statements(query: str, kind: str) -> list[str] | None:
    payload = _payload(query, kind)
    if payload is None:
        return None
    parts = [s for s in _STATEMENT_SPLIT.split(payload) if s]
    return parts or None


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


def _steps(labels: list[str]) -> list[tuple[str | None, str]] | None:
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


def _timings(labels: list[str]) -> list[tuple[str, str, int]] | None:
    parsed = [_TIMING_LABEL.match(label) for label in labels]
    if not all(parsed):
        return None
    return [(m.group(1).strip(), m.group(2).strip(), int(m.group(3))) for m in parsed]


# ── extraction from the user's query ────────────────────────────────────

Graph = tuple[list[str], list[tuple[str, str, str]]]


def _linear(labels: list[str]) -> Graph | None:
    if not 2 <= len(labels) <= _MAX_STAGES or len(set(labels)) != len(labels):
        return None
    return labels, [(labels[i], labels[i + 1], "next") for i in range(len(labels) - 1)]


def _checked(nodes: list[str], edges: list[tuple[str, str, str]]) -> Graph | None:
    if not 2 <= len(nodes) <= _MAX_STAGES or not edges or len(edges) > _MAX_EDGES:
        return None
    return nodes, edges


def _add(nodes: list[str], *names: str) -> None:
    for name in names:
        if name not in nodes:
            nodes.append(name)


def _extract_steps(query: str, kind: str) -> list[str] | None:
    payload = _payload(query, kind)
    if payload is None:
        return None
    parts = [part.strip() for part in _ARROW_SPLIT.split(payload) if part.strip()]
    if kind == SWIMLANE:
        lanes = [split_lane_label(part) for part in parts]
        return [f"{role}: {step}" for role, step in lanes] if parts and all(lanes) else None
    steps = _steps(parts) if parts else None
    if steps is None:
        return None
    return [f"{role}: {step}" if role else step for role, step in steps]


def _extract_messages(query: str) -> list[str] | None:
    statements = _statements(query, SEQUENCE)
    if statements is None:
        return None
    labels = []
    for index, statement in enumerate(statements):
        match = _MESSAGE_STATEMENT.match(statement)
        if not match:
            return None
        arrow = "-->" if match.group(2) == "-->" else "->"
        labels.append(f"{index + 1}. {match.group(1).strip()} {arrow} {match.group(3).strip()}: {match.group(4).strip()}")
    return labels


def _extract_tasks(query: str) -> list[str] | None:
    statements = _statements(query, GANTT)
    if statements is None:
        return None
    labels = []
    for statement in statements:
        match = _TASK_STATEMENT.match(statement)
        if not match:
            return None
        start, end = _parse_date(match.group(2)), _parse_date(match.group(3))
        if start is None or end is None:
            return None
        labels.append(f"{match.group(1).strip()}: {start.isoformat()} to {end.isoformat()}")
    return labels if _tasks(labels) else None


def _extract_timings(query: str) -> list[str] | None:
    statements = _statements(query, TIMING)
    if statements is None:
        return None
    labels = []
    for statement in statements:
        match = _TIMING_STATEMENT.match(statement)
        if not match:
            return None
        for item in match.group(2).split(","):
            state = _TIMING_ITEM.match(item)
            if not state:
                return None
            labels.append(f"{match.group(1).strip()}: {state.group(1).strip()} at {int(state.group(2))}")
    return labels


def _extract_relations(query: str, kind: str) -> Graph | None:
    """ERD, component and deployment: one "A <verb> B" relation per statement."""
    statements = _statements(query, kind)
    if statements is None:
        return None
    relation = _relation(kind)
    nodes: list[str] = []
    edges: list[tuple[str, str, str]] = []
    for statement in statements:
        match = relation.match(statement)
        if not match:
            return None
        a, b = match.group(1).strip(), match.group(3).strip()
        _add(nodes, a, b)
        edges.append((a, b, _edge_type(match.group(2))))
    return _checked(nodes, edges)


def _extract_declared(query: str, kind: str) -> Graph | None:
    """Class and object diagrams: optional "Name (fields)" declarations, plus
    relations. A declared element's label carries its fields, so the graph
    fallback still shows them."""
    statements = _statements(query, kind)
    if statements is None:
        return None
    relation = _relation(kind)
    item = _FIELD_ITEM if kind == CLASS else _ATTRIBUTE_ITEM
    labels: dict[str, str] = {}
    relations: list[tuple[str, str, str]] = []
    order: list[str] = []
    for statement in statements:
        declared = _DECLARATION.match(statement)
        if declared:
            name = declared.group(1).strip()
            fields = [item.match(f) for f in declared.group(2).split(",")] if declared.group(2) else []
            if name in labels or not all(fields) or len(fields) > _MAX_FIELDS:
                return None
            if kind == CLASS:
                body = ", ".join(f.group(1).strip() for f in fields)
            else:
                body = ", ".join(f"{f.group(1).strip()} = {f.group(2).strip()}" for f in fields)
            labels[name] = f"{name} ({body})" if body else name
            _add(order, name)
            continue
        match = relation.match(statement)
        if not match:
            return None
        a, b = match.group(1).strip(), match.group(3).strip()
        _add(order, a, b)
        relations.append((a, b, _edge_type(match.group(2))))
    label = lambda name: labels.get(name, name)  # noqa: E731
    return _checked([label(n) for n in order], [(label(a), label(b), t) for a, b, t in relations])


def _extract_states(query: str) -> Graph | None:
    """"A -> B: event" transitions, or plain chains "A -> B -> C"."""
    statements = _statements(query, STATE)
    if statements is None:
        return None
    nodes: list[str] = []
    edges: list[tuple[str, str, str]] = []
    for statement in statements:
        transition = _STATE_TRANSITION.match(statement)
        if transition:
            a, b = transition.group(1).strip(), transition.group(2).strip()
            _add(nodes, a, b)
            edges.append((a, b, (transition.group(3) or "next").strip()))
            continue
        chain = [part.strip() for part in _ARROW_SPLIT.split(statement)]
        if len(chain) < 2 or not all(_ENTITY_NAME.match(part) for part in chain):
            return None
        _add(nodes, *chain)
        edges += [(chain[i], chain[i + 1], "next") for i in range(len(chain) - 1)]
    return _checked(nodes, edges)


def _extract_usecases(query: str) -> Graph | None:
    """"Actor: use case, use case" per statement."""
    statements = _statements(query, USECASE)
    if statements is None:
        return None
    actors: list[str] = []
    cases: list[str] = []
    edges: list[tuple[str, str, str]] = []
    for statement in statements:
        match = _USECASE_STATEMENT.match(statement)
        if not match:
            return None
        actor = match.group(1).strip()
        items = [_USECASE_ITEM.match(item) for item in match.group(2).split(",")]
        if not all(items):
            return None
        _add(actors, actor)
        for item in items:
            case = item.group(1).strip()
            _add(cases, case)
            edges.append((actor, case, "uses"))
    if set(actors) & set(cases):
        return None
    return _checked(actors + cases, edges)


def _extract_packages(query: str) -> Graph | None:
    """"Package contains A, B" and "Package depends on Other"."""
    statements = _statements(query, PACKAGE)
    if statements is None:
        return None
    contains = re.compile(rf"^\s*({_NAME})\s+contains\s+(.+?)\s*$", re.I)
    relation = _relation(PACKAGE)
    nodes: list[str] = []
    edges: list[tuple[str, str, str]] = []
    for statement in statements:
        match = relation.match(statement)
        if match:
            a, b = match.group(1).strip(), match.group(3).strip()
            _add(nodes, a, b)
            edges.append((a, b, _edge_type(match.group(2))))
            continue
        match = contains.match(statement)
        if not match:
            return None
        package = match.group(1).strip()
        members = [m.strip() for m in match.group(2).split(",")]
        if not all(_ENTITY_NAME.match(m) for m in members):
            return None
        _add(nodes, package, *members)
        edges += [(package, member, "contains") for member in members]
    return _checked(nodes, edges)


def extract_kroki_graph(query: str) -> Graph | None:
    """Nodes and (source, target, type) edges for a named Kroki diagram whose
    whole payload parses — all or nothing, so no step is silently dropped."""
    for kind in (SWIMLANE, BPMN, ACTIVITY):
        steps = _extract_steps(query, kind)
        if steps:
            return _linear(steps)
    for extract in (_extract_messages, _extract_tasks, _extract_timings):
        labels = extract(query)
        if labels:
            return _linear(labels)
    return (
        _extract_relations(query, ERD)
        or _extract_declared(query, CLASS)
        or _extract_declared(query, OBJECT)
        or _extract_states(query)
        or _extract_usecases(query)
        or _extract_relations(query, COMPONENT)
        or _extract_relations(query, DEPLOYMENT)
        or _extract_packages(query)
    )


# ── fallback when the stated structure does not fit the diagram ──────────

_FLOW_NOTE = "showing a process flow instead."
_GRAPH_NOTE = "showing a relationship graph instead."
_DOWNGRADE_NOTES = {
    SWIMLANE: f"A swimlane needs a role for each step (for example \"Clerk: Raise PO -> Manager: Approve PO\"); {_FLOW_NOTE}",
    BPMN: ("A BPMN diagram needs steps joined by arrows (for example \"Raise PO -> Approve PO\"), "
           f"with a role on every step or on none; {_FLOW_NOTE}"),
    ACTIVITY: ("An activity diagram needs steps joined by arrows (for example \"Receive invoice -> Approve invoice\"), "
               f"with a role on every step or on none; {_FLOW_NOTE}"),
    SEQUENCE: ("A sequence diagram needs each message written as \"Clerk -> Manager: Request approval\", "
               f"separated by semicolons; {_FLOW_NOTE}"),
    GANTT: ("A Gantt chart needs each task with its dates, for example \"Planning: 2026-01-01 to 2026-01-05\", "
            f"separated by semicolons; {_FLOW_NOTE}"),
    TIMING: ("A timing diagram needs each line written as \"Invoice: Draft at 0, Approved at 2\", "
             f"separated by semicolons; {_FLOW_NOTE}"),
    ERD: f"An ER diagram needs entity names without special characters; {_GRAPH_NOTE}",
    CLASS: f"A class diagram needs class names without special characters; {_GRAPH_NOTE}",
    OBJECT: f"An object diagram needs object names without special characters; {_GRAPH_NOTE}",
    STATE: f"A state diagram needs state names without special characters; {_GRAPH_NOTE}",
    USECASE: ("A use case diagram needs each line written as \"Clerk: Enter invoice, Record payment\"; "
              f"{_GRAPH_NOTE}"),
    COMPONENT: f"A component diagram needs component names without special characters; {_GRAPH_NOTE}",
    DEPLOYMENT: f"A deployment diagram needs node names without special characters; {_GRAPH_NOTE}",
    PACKAGE: f"A package diagram needs package names without special characters; {_GRAPH_NOTE}",
}


def downgrade_if_unrenderable(spec) -> None:
    """The diagram was asked for, but the stated structure does not fit it
    (e.g. "as a swimlane: A -> B -> C"). Keep the ordinary flow or graph and
    say why, rather than asking Kroki for a diagram that cannot be built."""
    kind = KROKI_CAPABILITIES.get(spec.capability_id or "")
    if kind is None:
        return
    labels = [node.label for node in spec.nodes]
    by_id = {node.id: node.label for node in spec.nodes}
    edges = [(by_id.get(e.source, e.source), by_id.get(e.target, e.target), e.type) for e in spec.edges]
    if build_source(kind, labels, edges) is not None:
        return
    if kind in GRAPH_KINDS:
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


def _element_colors(colors: dict[str, str], *elements: str) -> list[str]:
    lines = []
    for element in elements:
        lines += [f"skinparam {element}BackgroundColor {colors['box']}",
                  f"skinparam {element}BorderColor {colors['brand']}",
                  f"skinparam {element}FontColor {colors['ink']}"]
    return lines


def _graph_parts(labels: list[str], edges: list[tuple[str, str, str]], typed: bool = True):
    """Aliases for unique labels, and edges whose ends are known labels and
    whose type is a plain relation word. None if anything does not check out."""
    if len(set(labels)) != len(labels) or not edges or len(edges) > _MAX_EDGES:
        return None
    aliases = {label: f"E{index}" for index, label in enumerate(labels)}
    for source, target, edge_type in edges:
        if source not in aliases or target not in aliases:
            return None
        if typed and not _EDGE_TYPE.match(edge_type or ""):
            return None
    return aliases


def _activity_source(labels: list[str], colors: dict[str, str], lanes_required: bool) -> str | None:
    steps = _steps(labels)
    if steps is None or (lanes_required and steps[0][0] is None):
        return None
    lines = ["@startuml", *_plantuml_header(colors), *_element_colors(colors, "Activity"),
             f"skinparam SwimlaneBorderColor {colors['line']}",
             f"skinparam SwimlaneTitleFontColor {colors['ink']}",
             f"skinparam ActivityStartColor {colors['brand']}",
             f"skinparam ActivityEndColor {colors['brand']}"]
    current_role = None
    for index, (role, step) in enumerate(steps):
        if role is not None and role != current_role:
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
             *_element_colors(colors, "Participant"),
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


def _timing_source(labels: list[str], colors: dict[str, str]) -> str | None:
    timings = _timings(labels)
    if timings is None:
        return None
    aliases: dict[str, str] = {}
    for participant, _state, _time in timings:
        aliases.setdefault(participant, f"T{len(aliases)}")
    lines = ["@startuml", *_plantuml_header(colors)]
    lines += [f'concise "{name}" as {alias}' for name, alias in aliases.items()]
    for time in sorted({t for _p, _s, t in timings}):
        lines.append(f"@{time}")
        lines += [f'{aliases[p]} is "{s}"' for p, s, t in timings if t == time]
    return "\n".join([*lines, "@enduml"])


_ERD_LINKS = {"has_many": "||--o{", "has_one": "||--||", "belongs_to": "}o--||"}
_CLASS_LINKS = {"has_many": '"1" --> "*"', "has_one": '"1" --> "1"', "belongs_to": '"*" --> "1"',
                "uses": "..>", "depends_on": "..>"}


def _erd_source(labels: list[str], edges: list[tuple[str, str, str]], colors: dict[str, str]) -> str | None:
    aliases = _graph_parts(labels, edges)
    if aliases is None or not all(_ENTITY_NAME.match(label) for label in labels):
        return None
    # Generous spacing: with several links between the same two entities the
    # default gaps put the relationship labels on top of each other.
    lines = ["@startuml", *_plantuml_header(colors), "hide circle", "hide empty members",
             "skinparam nodesep 80", "skinparam ranksep 90", *_element_colors(colors, "Class")]
    lines += [f'entity "{label}" as {alias}' for label, alias in aliases.items()]
    for source, target, edge_type in edges:
        link = _ERD_LINKS.get(edge_type, "--")
        lines.append(f"{aliases[source]} {link} {aliases[target]} : {edge_type.replace('_', ' ')}")
    return "\n".join([*lines, "@enduml"])


def _class_source(labels: list[str], edges: list[tuple[str, str, str]], colors: dict[str, str]) -> str | None:
    aliases = _graph_parts(labels, edges)
    parsed = [_CLASS_LABEL.match(label) for label in labels]
    if aliases is None or not all(parsed):
        return None
    lines = ["@startuml", *_plantuml_header(colors), "hide empty members",
             "skinparam nodesep 60", "skinparam ranksep 70", *_element_colors(colors, "Class")]
    for label, match in zip(labels, parsed):
        fields = match.group(2).split(", ") if match.group(2) else []
        lines.append(f'class "{match.group(1)}" as {aliases[label]} {{')
        lines += [f"  {field}" for field in fields]
        lines.append("}")
    for source, target, edge_type in edges:
        a, b = aliases[source], aliases[target]
        if edge_type == "is_a":
            lines.append(f"{b} <|-- {a}")
        else:
            lines.append(f"{a} {_CLASS_LINKS.get(edge_type, '-->')} {b} : {edge_type.replace('_', ' ')}")
    return "\n".join([*lines, "@enduml"])


def _object_source(labels: list[str], edges: list[tuple[str, str, str]], colors: dict[str, str]) -> str | None:
    aliases = _graph_parts(labels, edges)
    parsed = [_OBJECT_LABEL.match(label) for label in labels]
    if aliases is None or not all(parsed):
        return None
    lines = ["@startuml", *_plantuml_header(colors), "skinparam nodesep 60", "skinparam ranksep 70",
             *_element_colors(colors, "Object")]
    for label, match in zip(labels, parsed):
        attributes = match.group(2).split(", ") if match.group(2) else []
        lines.append(f'object "{match.group(1)}" as {aliases[label]} {{')
        lines += [f"  {attribute}" for attribute in attributes]
        lines.append("}")
    lines += [f"{aliases[s]} --> {aliases[t]} : {k.replace('_', ' ')}" for s, t, k in edges]
    return "\n".join([*lines, "@enduml"])


def _state_source(labels: list[str], edges: list[tuple[str, str, str]], colors: dict[str, str]) -> str | None:
    aliases = _graph_parts(labels, edges, typed=False)
    if aliases is None or not all(_ENTITY_NAME.match(label) for label in labels):
        return None
    if not all(k == "next" or _EVENT.match(k or "") for _s, _t, k in edges):
        return None
    lines = ["@startuml", *_plantuml_header(colors), "hide empty description", *_element_colors(colors, "State")]
    lines += [f'state "{label}" as {alias}' for label, alias in aliases.items()]
    lines.append(f"[*] --> {aliases[labels[0]]}")
    for source, target, event in edges:
        suffix = "" if event == "next" else f" : {event}"
        lines.append(f"{aliases[source]} --> {aliases[target]}{suffix}")
    # A state with transitions in but none out is where the lifecycle ends.
    sources = {s for s, _t, _k in edges}
    targets = {t for _s, t, _k in edges}
    lines += [f"{aliases[label]} --> [*]" for label in labels if label in targets and label not in sources]
    return "\n".join([*lines, "@enduml"])


def _usecase_source(labels: list[str], edges: list[tuple[str, str, str]], colors: dict[str, str]) -> str | None:
    aliases = _graph_parts(labels, edges)
    if aliases is None:
        return None
    actors = {s for s, _t, _k in edges}
    cases = {t for _s, t, _k in edges}
    if actors & cases or set(labels) != actors | cases:
        return None
    if not all(_ENTITY_NAME.match(a) for a in actors) or not all(re.match(rf"^{_ITEM}$", c) for c in cases):
        return None
    lines = ["@startuml", *_plantuml_header(colors), "left to right direction",
             *_element_colors(colors, "Actor", "Usecase")]
    lines += [f'actor "{label}" as {aliases[label]}' for label in labels if label in actors]
    lines += [f'usecase "{label}" as {aliases[label]}' for label in labels if label in cases]
    lines += [f"{aliases[s]} --> {aliases[t]}" for s, t, _k in edges]
    return "\n".join([*lines, "@enduml"])


def _component_source(labels: list[str], edges: list[tuple[str, str, str]], colors: dict[str, str]) -> str | None:
    aliases = _graph_parts(labels, edges)
    if aliases is None or not all(_ENTITY_NAME.match(label) for label in labels):
        return None
    lines = ["@startuml", *_plantuml_header(colors), *_element_colors(colors, "Component")]
    lines += [f'component "{label}" as {alias}' for label, alias in aliases.items()]
    lines += [f"{aliases[s]} --> {aliases[t]} : {k.replace('_', ' ')}" for s, t, k in edges]
    return "\n".join([*lines, "@enduml"])


def _deployment_source(labels: list[str], edges: list[tuple[str, str, str]], colors: dict[str, str]) -> str | None:
    aliases = _graph_parts(labels, edges)
    if aliases is None or not all(_ENTITY_NAME.match(label) for label in labels):
        return None
    # What is hosted, or runs on something, is software; everything else is
    # a machine or environment.
    artifacts = {t for _s, t, k in edges if k == "hosts"} | {s for s, _t, k in edges if k == "runs_on"}
    lines = ["@startuml", *_plantuml_header(colors), *_element_colors(colors, "Node", "Artifact")]
    lines += [f'{"artifact" if label in artifacts else "node"} "{label}" as {alias}' for label, alias in aliases.items()]
    lines += [f"{aliases[s]} --> {aliases[t]} : {k.replace('_', ' ')}" for s, t, k in edges]
    return "\n".join([*lines, "@enduml"])


def _package_source(labels: list[str], edges: list[tuple[str, str, str]], colors: dict[str, str]) -> str | None:
    aliases = _graph_parts(labels, edges)
    if aliases is None or not all(_ENTITY_NAME.match(label) for label in labels):
        return None
    owner: dict[str, str] = {}
    for source, target, edge_type in edges:
        if edge_type == "contains":
            if target in owner or target == source:
                return None
            owner[target] = source
    if set(owner) & set(owner.values()):
        return None                       # nested packages are not supported
    lines = ["@startuml", *_plantuml_header(colors), *_element_colors(colors, "Package", "Rectangle")]
    for label in labels:
        if label in owner:
            continue
        members = [m for m in labels if owner.get(m) == label]
        lines.append(f'package "{label}" as {aliases[label]} {{')
        lines += [f'  rectangle "{member}" as {aliases[member]}' for member in members]
        lines.append("}")
    lines += [f"{aliases[s]} ..> {aliases[t]} : {k.replace('_', ' ')}" for s, t, k in edges if k != "contains"]
    return "\n".join([*lines, "@enduml"])


def _bpmn_source(labels: list[str]) -> str | None:
    """BPMN 2.0 XML with its diagram layout (bpmn-js draws nothing without
    one): start event, one task per step, end event, left to right, with a
    lane per role when roles were given."""
    steps = _steps(labels)
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
    edges = edges or []
    if kind == SWIMLANE:
        return _activity_source(labels, colors, lanes_required=True)
    if kind == ACTIVITY:
        return _activity_source(labels, colors, lanes_required=False)
    if kind == SEQUENCE:
        return _sequence_source(labels, colors)
    if kind == GANTT:
        return _gantt_source(labels, colors)
    if kind == TIMING:
        return _timing_source(labels, colors)
    if kind == BPMN:
        return _bpmn_source(labels)
    builders = {
        ERD: _erd_source, CLASS: _class_source, OBJECT: _object_source, STATE: _state_source,
        USECASE: _usecase_source, COMPONENT: _component_source, DEPLOYMENT: _deployment_source,
        PACKAGE: _package_source,
    }
    return builders[kind](labels, edges, colors)
