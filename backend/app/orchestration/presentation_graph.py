"""Strict construction and validation for relationship/knowledge-graph
presentations (Cytoscape.js-rendered evidence chains and connected-record
graphs).

Nodes and edges are built exclusively from data already extracted
deterministically from validated, Checkpoint-C-passed answer text (see
presentation.py's module docstring) — this module never invents an entity or
relationship. entity_type, relationship_type, and layout are closed enums
enforced by both a plain-set check here and the Pydantic Literal fields on
GraphNode/GraphEdge/PresentationGraph, so nothing outside the approved lists
can reach the frontend, and no field carries anything the LLM could use to
inject markup or executable content — every value is plain data (short
strings, an enum, a flat metadata dict), never HTML/JS.
"""
from __future__ import annotations

from app.orchestration.schemas import GraphEdge, GraphNode, PresentationGraph

MAX_NODES = 40
MAX_EDGES = 60

ENTITY_TYPES = {
    "invoice", "supplier", "purchase_order", "receipt", "payment",
    "bank_transaction", "ledger_entry", "contract", "approval", "user",
    "source_document", "audit_evidence",
}
RELATIONSHIP_TYPES = {
    "issued_by", "belongs_to", "references", "approved_by", "paid_by",
    "matched_to", "recorded_as", "supported_by", "derived_from", "reconciled_with",
}
LAYOUTS = {"breadthfirst", "cose", "concentric"}


def build_graph(
    *,
    graph_id: str,
    title: str,
    summary: str,
    raw_nodes: list[dict],
    raw_edges: list[dict],
    layout: str,
    confidence: float = 1.0,
    allow_self_links: bool = False,
) -> tuple[PresentationGraph | None, str]:
    """Validate raw node/edge dicts into a strict PresentationGraph.

    Returns (graph_or_none, validation_result). validation_result is a short
    machine-readable reason for the caller to log — "accepted" or
    "rejected:<reason>" — never raises on bad input, so a malformed or
    oversized candidate degrades to no graph (text-only) rather than an
    exception reaching the request handler.
    """
    if not raw_nodes or not raw_edges:
        return None, "rejected:empty_graph"
    if len(raw_nodes) > MAX_NODES or len(raw_edges) > MAX_EDGES:
        return None, "rejected:graph_too_large"
    if layout not in LAYOUTS:
        return None, "rejected:unsupported_layout"

    seen_node_ids: set[str] = set()
    nodes: list[GraphNode] = []
    for raw in raw_nodes:
        node_id = str(raw.get("id", "")).strip()
        entity_type = str(raw.get("entity_type", "")).strip().lower()
        if not node_id or entity_type not in ENTITY_TYPES:
            return None, "rejected:unsupported_entity_type"
        if node_id in seen_node_ids:
            return None, "rejected:duplicate_node_id"
        seen_node_ids.add(node_id)
        nodes.append(GraphNode(
            id=node_id,
            label=str(raw.get("label") or node_id)[:80],
            entity_type=entity_type,
            status=str(raw.get("status", ""))[:40],
            source_reference=str(raw.get("source_reference", ""))[:40],
            metadata={
                str(key)[:40]: str(value)[:120]
                for key, value in dict(raw.get("metadata") or {}).items()
            },
        ))

    seen_edge_ids: set[str] = set()
    edges: list[GraphEdge] = []
    for raw in raw_edges:
        edge_id = str(raw.get("id", "")).strip()
        source = str(raw.get("source", "")).strip()
        target = str(raw.get("target", "")).strip()
        relationship_type = str(raw.get("relationship_type", "")).strip().lower()
        if not edge_id or edge_id in seen_edge_ids:
            return None, "rejected:duplicate_edge_id"
        if relationship_type not in RELATIONSHIP_TYPES:
            return None, "rejected:unsupported_relationship_type"
        if source not in seen_node_ids or target not in seen_node_ids:
            return None, "rejected:missing_node_reference"
        if source == target and not allow_self_links:
            return None, "rejected:self_link_not_allowed"
        seen_edge_ids.add(edge_id)
        direction = str(raw.get("direction") or "directed").strip().lower()
        if direction not in {"directed", "bidirectional"}:
            direction = "directed"
        edges.append(GraphEdge(
            id=edge_id,
            source=source,
            target=target,
            relationship_type=relationship_type,
            label=str(raw.get("label") or relationship_type.replace("_", " "))[:60],
            direction=direction,
        ))

    graph = PresentationGraph(
        graph_id=graph_id,
        title=title[:120],
        summary=summary[:400],
        nodes=nodes,
        edges=edges,
        layout=layout,
        confidence=confidence if 0 <= confidence <= 1 else 1.0,
    )
    return graph, "accepted"
