"""Service-layer tests for saved visualizations (save-to-conversation).
Exercises app.domains.kriton_workspace.service directly against the sqlite
test schema — SQLite doesn't enforce the tenant_id/user_id foreign keys by
default in this project's test config, so arbitrary id strings are fine here.
"""
import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.core.database import AsyncSessionLocal
from app.domains.kriton_workspace import service
from app.domains.kriton_workspace.schemas import SavedVisualizationCreateRequest

PRESENTATION_CHART_PAYLOAD = {
    "chart_id": "answer-table-1",
    "type": "grouped_bar",
    "title": "Department comparison",
    "categories": ["Payroll", "Technology"],
    "series": [
        {"name": "Budget", "values": ["150000", "60000"], "unit": "$"},
        {"name": "Actual", "values": ["158000", "72000"], "unit": "$"},
    ],
    "unit": "$",
    "domain": "accounting",
    "summary_mode": "total",
}

GRAPH_PAYLOAD = {
    "graph_id": "g1",
    "title": "Evidence chain",
    "summary": "2 records connected by 1 relationship.",
    "layout": "breadthfirst",
    "confidence": 1.0,
    "nodes": [
        {"id": "INV-1", "label": "INV-1", "entity_type": "invoice", "status": "", "source_reference": "", "metadata": {}},
        {"id": "SUP-1", "label": "SUP-1", "entity_type": "supplier", "status": "", "source_reference": "", "metadata": {}},
    ],
    "edges": [
        {"id": "e1", "source": "INV-1", "target": "SUP-1", "relationship_type": "issued_by", "label": "issued by", "direction": "directed"},
    ],
}


@pytest_asyncio.fixture
async def db():
    async with AsyncSessionLocal() as session:
        yield session


@pytest.mark.asyncio
async def test_create_saved_visualization_persists_clean_payload(db):
    row = await service.create_saved_visualization(
        db, "tenant-1", "user-1",
        SavedVisualizationCreateRequest(
            query_id="q1", visualization_type="graph", title="Evidence chain",
            summary="An evidence chain.", payload=GRAPH_PAYLOAD, source_references=["REF-1"],
        ),
    )
    assert row.visualization_type == "graph"
    assert row.payload["graph_id"] == "g1"
    assert len(row.payload["nodes"]) == 2


@pytest.mark.asyncio
async def test_diagnostic_and_reasoning_fields_are_never_stored(db):
    payload_with_leak = {
        **GRAPH_PAYLOAD,
        "reasoning_summary": "the LLM's internal classification reasoning",
        "classification_source": "llm",
    }
    row = await service.create_saved_visualization(
        db, "tenant-1", "user-1",
        SavedVisualizationCreateRequest(
            query_id="q1", visualization_type="graph", title="t", payload=payload_with_leak,
        ),
    )
    # PresentationGraph has no reasoning_summary/classification_source field —
    # model_validate() silently drops anything it doesn't define.
    assert "reasoning_summary" not in row.payload
    assert "classification_source" not in row.payload


@pytest.mark.asyncio
async def test_editable_workflow_state_is_validated_and_persisted(db):
    payload = {
        "guide_id": "workflow-1", "type": "process", "title": "Approval workflow",
        "items": ["Review invoice", "Approve payment"], "renderer": "react_flow", "editable": True,
        "flow_nodes": [
            {"id": "a", "position": {"x": 0, "y": 0}, "label": "Review invoice"},
            {"id": "b", "position": {"x": 250, "y": 0}, "label": "Approve payment"},
        ],
        "flow_edges": [{"id": "e", "source": "a", "target": "b"}],
    }
    row = await service.create_saved_visualization(
        db, "tenant-1", "user-1",
        SavedVisualizationCreateRequest(
            query_id="q1", visualization_type="diagram", title="Approval workflow", payload=payload,
        ),
    )
    assert row.payload["flow_nodes"][1]["position"] == {"x": 250.0, "y": 0.0}
    assert row.payload["flow_edges"] == [{"id": "e", "source": "a", "target": "b"}]


@pytest.mark.asyncio
async def test_unsupported_visualization_type_is_rejected(db):
    with pytest.raises(HTTPException) as excinfo:
        await service.create_saved_visualization(
            db, "tenant-1", "user-1",
            SavedVisualizationCreateRequest(
                query_id="q1", visualization_type="chart", title="t",
                payload={"not": "a valid calculation widget"},
            ),
        )
    assert excinfo.value.status_code == 422


@pytest.mark.asyncio
async def test_malformed_graph_payload_is_rejected(db):
    with pytest.raises(HTTPException) as excinfo:
        await service.create_saved_visualization(
            db, "tenant-1", "user-1",
            SavedVisualizationCreateRequest(
                query_id="q1", visualization_type="graph", title="t",
                payload={"graph_id": "g1"},  # missing required fields
            ),
        )
    assert excinfo.value.status_code == 422


@pytest.mark.asyncio
async def test_oversized_graph_is_rejected_even_though_client_json_is_well_formed(db):
    # A client posting straight to this endpoint isn't bound by whatever the
    # original rendered answer actually contained — the same MAX_NODES/
    # MAX_EDGES limits presentation_graph.py enforces during extraction have
    # to be re-checked here too.
    oversized = {
        **GRAPH_PAYLOAD,
        "nodes": [
            {"id": f"N{i}", "label": f"N{i}", "entity_type": "invoice", "status": "", "source_reference": "", "metadata": {}}
            for i in range(100)
        ],
        "edges": [],
    }
    with pytest.raises(HTTPException) as excinfo:
        await service.create_saved_visualization(
            db, "tenant-1", "user-1",
            SavedVisualizationCreateRequest(query_id="q1", visualization_type="graph", title="t", payload=oversized),
        )
    assert excinfo.value.status_code == 422


@pytest.mark.asyncio
async def test_unsupported_fields_are_logged_by_name_only_never_by_value(db, caplog):
    import logging
    payload_with_leak = {**GRAPH_PAYLOAD, "reasoning_summary": "the secret internal reasoning text"}
    with caplog.at_level(logging.INFO, logger="app.domains.kriton_workspace.service"):
        await service.create_saved_visualization(
            db, "tenant-1", "user-1",
            SavedVisualizationCreateRequest(query_id="q1", visualization_type="graph", title="t", payload=payload_with_leak),
        )
    messages = [record.getMessage() for record in caplog.records]
    stripped_field_lists = [getattr(r, "stripped_fields", None) for r in caplog.records]
    assert any("reasoning_summary" in (fields or []) for fields in stripped_field_lists), messages
    assert not any("secret internal reasoning text" in message for message in messages)


@pytest.mark.asyncio
async def test_presentation_chart_save_persists_clean_payload(db):
    row = await service.create_saved_visualization(
        db, "tenant-1", "user-1",
        SavedVisualizationCreateRequest(
            query_id="q1", visualization_type="presentation_chart", title="Department comparison",
            payload=PRESENTATION_CHART_PAYLOAD,
        ),
    )
    assert row.visualization_type == "presentation_chart"
    assert row.payload["type"] == "grouped_bar"
    assert len(row.payload["series"]) == 2


@pytest.mark.asyncio
async def test_presentation_chart_rejects_unsupported_type_literal(db):
    with pytest.raises(HTTPException) as excinfo:
        await service.create_saved_visualization(
            db, "tenant-1", "user-1",
            SavedVisualizationCreateRequest(
                query_id="q1", visualization_type="presentation_chart", title="t",
                payload={**PRESENTATION_CHART_PAYLOAD, "type": "not_a_real_chart_type"},
            ),
        )
    assert excinfo.value.status_code == 422


@pytest.mark.asyncio
async def test_oversized_presentation_chart_categories_are_rejected(db):
    oversized = {
        **PRESENTATION_CHART_PAYLOAD,
        "categories": [f"Category {i}" for i in range(100)],
        "series": [{"name": "Amount", "values": [str(i) for i in range(100)], "unit": "$"}],
    }
    with pytest.raises(HTTPException) as excinfo:
        await service.create_saved_visualization(
            db, "tenant-1", "user-1",
            SavedVisualizationCreateRequest(query_id="q1", visualization_type="presentation_chart", title="t", payload=oversized),
        )
    assert excinfo.value.status_code == 422


@pytest.mark.asyncio
async def test_oversized_presentation_chart_series_are_rejected(db):
    oversized = {
        **PRESENTATION_CHART_PAYLOAD,
        "series": [{"name": f"Series {i}", "values": ["1", "2"], "unit": "$"} for i in range(30)],
    }
    with pytest.raises(HTTPException) as excinfo:
        await service.create_saved_visualization(
            db, "tenant-1", "user-1",
            SavedVisualizationCreateRequest(query_id="q1", visualization_type="presentation_chart", title="t", payload=oversized),
        )
    assert excinfo.value.status_code == 422


@pytest.mark.asyncio
async def test_list_and_delete_are_scoped_to_the_owning_user(db):
    row = await service.create_saved_visualization(
        db, "tenant-1", "user-a",
        SavedVisualizationCreateRequest(query_id="q1", visualization_type="graph", title="t", payload=GRAPH_PAYLOAD),
    )
    assert await service.list_saved_visualizations(db, "user-b") == []
    assert len(await service.list_saved_visualizations(db, "user-a")) >= 1

    assert await service.delete_saved_visualization(db, "user-b", row.id) is False
    assert await service.delete_saved_visualization(db, "user-a", row.id) is True
