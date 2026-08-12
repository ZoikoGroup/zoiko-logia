from app.orchestration.data_shape import DIRECTED_STAGES, NODES_EDGES, SCALAR, TIME_SERIES
from app.orchestration.response_planner import ResponsePlan
from app.orchestration.visualization.router import choose_visual_route
from app.orchestration.visualization.domain import classify_domain_context, domain_variant
from app.orchestration.visualization.domain_catalog import DOMAIN_VARIANTS
from app.orchestration.visualization.capabilities import ROUTABLE_CAPABILITIES
from app.orchestration.visualization.image_taxonomy import IMAGE_TAXONOMY, IMAGE_TAXONOMY_BY_ID


def _plan(intent: str, **overrides) -> ResponsePlan:
    values = dict(
        intent=intent, response_mode="TEXT_CHART", visual_required=True,
        visual_family="STATISTICAL", confidence=0.9,
    )
    values.update(overrides)
    return ResponsePlan(**values)


def test_trend_routes_family_then_canonical_then_variant():
    route = choose_visual_route(data_shape=TIME_SERIES, plan=_plan("TREND"), observation_count=12)
    assert (route.family, route.canonical, route.variant, route.selected_type) == (
        "TREND", "LINE", "STANDARD_LINE", "LINE",
    )


def test_distribution_routes_to_histogram_variant():
    route = choose_visual_route(data_shape=TIME_SERIES, plan=_plan("DISTRIBUTION"), observation_count=12)
    assert (route.family, route.canonical, route.variant) == (
        "DISTRIBUTION", "HISTOGRAM", "STANDARD_HISTOGRAM",
    )


def test_exact_series_routes_to_table_not_chart():
    route = choose_visual_route(data_shape=TIME_SERIES, plan=_plan("PRECISE_DATA"), observation_count=12)
    assert (route.canonical, route.variant, route.selected_type) == (
        "TABLE", "EXACT_VALUES_TABLE", "TABLE",
    )


def test_graph_and_explicit_heatmap_are_distinct_routes():
    graph = choose_visual_route(
        data_shape=NODES_EDGES, plan=_plan("EVIDENCE_ANALYSIS"), observation_count=0, entity_count=2,
    )
    heatmap = choose_visual_route(
        data_shape=NODES_EDGES,
        plan=_plan("RELATIONSHIP", explicit_heatmap_request=True),
        observation_count=0, entity_count=2,
    )
    assert (graph.family, graph.canonical, graph.variant) == (
        "GRAPH_NETWORK", "GRAPH", "EVIDENCE_GRAPH",
    )
    assert (heatmap.family, heatmap.canonical, heatmap.variant) == (
        "RELATIONSHIP", "HEATMAP", "ADJACENCY_HEATMAP",
    )


def test_flow_variant_uses_explicit_interactivity():
    simple = choose_visual_route(
        data_shape=DIRECTED_STAGES, plan=_plan("PROCESS"), observation_count=0, entity_count=2,
    )
    interactive = choose_visual_route(
        data_shape=DIRECTED_STAGES,
        plan=_plan("PROCESS", explicit_interactive_request=True),
        observation_count=0, entity_count=2,
    )
    assert simple.variant == "BASIC_FLOWCHART"
    assert interactive.variant == "INTERACTIVE_WORKFLOW"


def test_scalar_routes_to_kpi_card():
    route = choose_visual_route(data_shape=SCALAR, plan=_plan("CURRENT_METRIC"), observation_count=1)
    assert (route.family, route.canonical, route.variant) == (
        "KPI", "KPI", "KPI_CARD",
    )


def test_audit_evidence_gets_domain_graph_variant():
    query = "Show which audit evidence supports this assertion and conclusion."
    context = classify_domain_context(query, "EVIDENCE_ANALYSIS")
    plan = _plan(
        "EVIDENCE_ANALYSIS", domain=context.domain, subdomain=context.subdomain,
    )
    route = choose_visual_route(
        data_shape=NODES_EDGES, plan=plan, observation_count=0, entity_count=2, query=query,
    )
    assert (context.domain, context.subdomain) == ("AUDIT", "AUDIT_EVIDENCE")
    assert route.variant == "ASSERTION_EVIDENCE_GRAPH"


def test_domain_semantics_do_not_change_canonical_shape():
    context = classify_domain_context("Show the distribution of audit sample values.", "DISTRIBUTION")
    assert domain_variant("STANDARD_HISTOGRAM", context) == "AUDIT_SAMPLING_DISTRIBUTION"


def test_large_flow_routes_to_interactive_variant():
    route = choose_visual_route(
        data_shape=DIRECTED_STAGES, plan=_plan("PROCESS"),
        observation_count=0, entity_count=6,
    )
    assert route.variant == "INTERACTIVE_WORKFLOW"


def test_domain_catalog_is_a_variant_library_not_a_flat_classifier():
    assert 30 <= len(DOMAIN_VARIANTS) <= 60
    assert DOMAIN_VARIANTS["BOOK_TO_TAX_BRIDGE"].canonical == "WATERFALL"
    assert DOMAIN_VARIANTS["ASSERTION_EVIDENCE_GRAPH"].required_shape == "NODES_EDGES"


def test_routable_capabilities_are_complete_metadata_records():
    assert all(cap.family and cap.canonical_type and cap.variant for cap in ROUTABLE_CAPABILITIES)
    assert all(cap.supported_intents and cap.supported_data_shapes for cap in ROUTABLE_CAPABILITIES)
    assert all(cap.renderer and cap.fallbacks for cap in ROUTABLE_CAPABILITIES)
    assert all(cap.id in IMAGE_TAXONOMY_BY_ID for cap in ROUTABLE_CAPABILITIES)


def test_supplied_image_taxonomy_is_fully_normalized():
    assert len(IMAGE_TAXONOMY) == 290
    assert {entry.source_number for entry in IMAGE_TAXONOMY} == set(range(1, 291))
    assert all(entry.family and entry.canonical_type for entry in IMAGE_TAXONOMY)
    assert all(entry.supported_intents and entry.supported_data_shapes for entry in IMAGE_TAXONOMY)


def test_domain_classifier_distinguishes_ar_from_general_finance():
    context = classify_domain_context("Show accounts receivable collections over time.", "TREND")
    assert context.domain == "ACCOUNTS_RECEIVABLE"
    plan = _plan("TREND", domain=context.domain, subdomain=context.subdomain)
    route = choose_visual_route(
        data_shape=TIME_SERIES, plan=plan, observation_count=12,
        query="Show accounts receivable collections over time.",
    )
    assert route.variant == "AR_COLLECTION_TREND"


def test_explicit_chart_variants_route_to_distinct_capabilities():
    cases = {
        "Show CPI as a bar chart over time.": ("bar_chart", "BAR", "BAR_CHART"),
        "Show CPI as a step line chart over time.": ("step_line_chart", "LINE", "STEP_LINE_CHART"),
        "Show CPI as an area chart over time.": ("area_chart", "AREA", "AREA_CHART"),
        "Show CPI as a line with markers over time.": ("line_with_markers", "LINE", "LINE_WITH_MARKERS"),
    }
    from app.orchestration.response_planner import plan_response
    for query, expected in cases.items():
        plan = plan_response(query, "TREND", TIME_SERIES)
        route = choose_visual_route(data_shape=TIME_SERIES, plan=plan, observation_count=12, query=query)
        assert (route.capability_id, route.canonical, route.variant) == expected
