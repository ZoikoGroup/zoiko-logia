"""Unit tests for the strict relationship-graph validator in
app/orchestration/presentation_graph.py — the schema-enforcement boundary
that decides whether a candidate node/edge set becomes a renderable
PresentationGraph.
"""
from app.orchestration import presentation_graph


def _node(node_id, entity_type="invoice", **extra):
    return {"id": node_id, "entity_type": entity_type, "label": node_id, **extra}


def _edge(edge_id, source, target, relationship_type="references", **extra):
    return {"id": edge_id, "source": source, "target": target, "relationship_type": relationship_type, **extra}


def _build(nodes, edges, layout="cose"):
    return presentation_graph.build_graph(
        graph_id="g1", title="Test graph", summary="Test summary",
        raw_nodes=nodes, raw_edges=edges, layout=layout,
    )


def test_valid_chain_is_accepted():
    nodes = [_node("INV-1", "invoice"), _node("SUP-1", "supplier")]
    edges = [_edge("e1", "INV-1", "SUP-1", "issued_by")]
    graph, result = _build(nodes, edges)
    assert result == "accepted"
    assert graph is not None
    assert [n.id for n in graph.nodes] == ["INV-1", "SUP-1"]
    assert graph.edges[0].relationship_type == "issued_by"


def test_missing_referenced_node_rejects_graph():
    nodes = [_node("INV-1", "invoice")]
    edges = [_edge("e1", "INV-1", "SUP-DOES-NOT-EXIST", "issued_by")]
    graph, result = _build(nodes, edges)
    assert graph is None
    assert result == "rejected:missing_node_reference"


def test_duplicate_node_ids_reject_graph():
    nodes = [_node("INV-1", "invoice"), _node("INV-1", "invoice")]
    edges = [_edge("e1", "INV-1", "INV-1", "references")]
    graph, result = _build(nodes, edges)
    assert graph is None
    assert result == "rejected:duplicate_node_id"


def test_duplicate_edge_ids_reject_graph():
    nodes = [_node("INV-1"), _node("SUP-1", "supplier"), _node("PO-1", "purchase_order")]
    edges = [
        _edge("e1", "INV-1", "SUP-1", "issued_by"),
        _edge("e1", "INV-1", "PO-1", "references"),
    ]
    graph, result = _build(nodes, edges)
    assert graph is None
    assert result == "rejected:duplicate_edge_id"


def test_unsupported_relationship_type_is_rejected():
    nodes = [_node("INV-1"), _node("SUP-1", "supplier")]
    edges = [_edge("e1", "INV-1", "SUP-1", "hacked_by")]
    graph, result = _build(nodes, edges)
    assert graph is None
    assert result == "rejected:unsupported_relationship_type"


def test_unsupported_entity_type_is_rejected():
    nodes = [_node("INV-1", "spreadsheet")]
    edges = [_edge("e1", "INV-1", "INV-1")]
    graph, result = _build(nodes, edges)
    assert graph is None
    assert result == "rejected:unsupported_entity_type"


def test_self_link_is_rejected_unless_explicitly_allowed():
    nodes = [_node("INV-1")]
    edges = [_edge("e1", "INV-1", "INV-1", "references")]
    graph, result = _build(nodes, edges)
    assert graph is None
    assert result == "rejected:self_link_not_allowed"

    graph, result = presentation_graph.build_graph(
        graph_id="g1", title="t", summary="s",
        raw_nodes=nodes, raw_edges=edges, layout="cose", allow_self_links=True,
    )
    assert result == "accepted"
    assert graph is not None


def test_empty_graph_is_rejected():
    graph, result = _build([], [])
    assert graph is None
    assert result == "rejected:empty_graph"

    graph, result = _build([_node("INV-1")], [])
    assert graph is None
    assert result == "rejected:empty_graph"


def test_excessive_node_count_is_limited_safely():
    nodes = [_node(f"INV-{i}") for i in range(presentation_graph.MAX_NODES + 1)]
    edges = [_edge(f"e{i}", nodes[i]["id"], nodes[i + 1]["id"]) for i in range(len(nodes) - 1)]
    graph, result = _build(nodes, edges)
    assert graph is None
    assert result == "rejected:graph_too_large"


def test_excessive_edge_count_is_limited_safely():
    nodes = [_node(f"INV-{i}") for i in range(3)]
    edges = [
        _edge(f"e{i}", nodes[i % 3]["id"], nodes[(i + 1) % 3]["id"])
        for i in range(presentation_graph.MAX_EDGES + 1)
    ]
    graph, result = _build(nodes, edges)
    assert graph is None
    assert result == "rejected:graph_too_large"


def test_unsupported_layout_is_rejected():
    nodes = [_node("INV-1"), _node("SUP-1", "supplier")]
    edges = [_edge("e1", "INV-1", "SUP-1", "issued_by")]
    graph, result = _build(nodes, edges, layout="force-directed-3d")
    assert graph is None
    assert result == "rejected:unsupported_layout"


def test_malicious_label_is_stored_as_plain_truncated_text():
    nodes = [
        _node("INV-1", label='<img src=x onerror=alert(1)>'),
        _node("SUP-1", "supplier"),
    ]
    edges = [_edge("e1", "INV-1", "SUP-1", "issued_by", label="<script>alert(1)</script>")]
    graph, result = _build(nodes, edges)
    assert result == "accepted"
    # Stored verbatim as inert string data (Pydantic str fields, no HTML
    # parsing anywhere in this module) — the frontend is responsible for
    # rendering it as text; this layer's job is only to never drop it into
    # anything executable itself, which a plain str field guarantees.
    assert graph.nodes[0].label == '<img src=x onerror=alert(1)>'
    assert graph.edges[0].label == "<script>alert(1)</script>"
    assert isinstance(graph.nodes[0].label, str)
