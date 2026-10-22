"""Hierarchical visualization routing.

The capability catalogue may grow to many variants, but selection stays a
small deterministic problem: family -> canonical visual -> implemented
variant.  This module deliberately routes only shapes Kriton's EvidenceModel
can prove today; unsupported requests fall back instead of fabricating data.
"""
from __future__ import annotations

from pydantic import BaseModel

from app.orchestration.response_planner import ResponsePlan
from app.orchestration.visualization.domain import DomainContext, domain_variant
from app.orchestration.visualization.capabilities import ROUTABLE_CAPABILITIES, VisualizationCapability


class VisualRoute(BaseModel):
    capability_id: str
    family: str
    canonical: str
    variant: str
    # The capability's own variant, before domain_variant() specialized it.
    # `variant` is renamed per domain (STANDARD_LINE becomes TAX_METRIC_TREND
    # for a tax question), so it cannot answer "did the user get the chart
    # they asked for" — comparing it against the request would report a
    # substitution on a request that was honoured perfectly.
    base_variant: str
    selected_type: str
    confidence: float


def choose_visual_route(
    *, data_shape: str, plan: ResponsePlan, observation_count: int,
    entity_count: int = 0, query: str = "",
) -> VisualRoute | None:
    """Choose only among canonical visuals supported by the proven shape."""
    context = DomainContext(domain=plan.domain, subdomain=plan.subdomain, intent=plan.intent)

    def specialized(variant: str) -> str:
        return domain_variant(variant, context, query)

    def matches(capability: VisualizationCapability) -> bool:
        interactive = plan.explicit_interactive_request or entity_count >= 6
        intent_matches = plan.intent in capability.supported_intents or (
            plan.explicit_visual_request and "__EXPLICIT_VISUAL__" in capability.supported_intents
        )
        return all((
            data_shape in capability.supported_data_shapes,
            plan.domain in capability.domains,
            intent_matches,
            observation_count >= capability.minimum_observations,
            entity_count >= capability.minimum_entities,
            not capability.requires_explicit_heatmap or plan.explicit_heatmap_request,
            not capability.excludes_explicit_heatmap or not plan.explicit_heatmap_request,
            not capability.requires_interactivity or interactive,
            # A flow the user named (swimlane) is drawn at any stage count;
            # only the unnamed flows split on interactivity.
            capability.requires_interactivity or not interactive or capability.canonical_type != "FLOW"
            or capability.requested_variant is not None,
            capability.requested_variant is None or capability.requested_variant == plan.requested_chart_variant,
        ))

    # A chart the user NAMED outranks a higher-priority default. Priority
    # alone is the right tie-break between capabilities nobody asked for, but
    # it cannot express "they said bar chart": on OHLC data the candlestick
    # default would beat an explicitly requested bar or line every time, since
    # those capabilities carry no priority advantage over it. Ordering by
    # (asked-for, priority) keeps every unrequested case exactly as it was.
    def rank(capability: VisualizationCapability) -> tuple[int, float]:
        asked_for = bool(
            plan.requested_chart_variant
            and capability.variant == plan.requested_chart_variant
        )
        return (1 if asked_for else 0, capability.priority)

    matches_in_priority_order = sorted(
        (capability for capability in ROUTABLE_CAPABILITIES if matches(capability)),
        key=rank,
        reverse=True,
    )
    if not matches_in_priority_order:
        return None
    selected = matches_in_priority_order[0]
    return VisualRoute(
        capability_id=selected.id,
        family=selected.family,
        canonical=selected.canonical_type,
        variant=specialized(selected.variant),
        base_variant=selected.variant,
        selected_type=selected.selected_type,
        confidence=selected.priority,
    )


class VisualizationIntent(BaseModel):
    """Selection contract describing the existing validated renderer payload."""
    output_type: str
    reason: str
    dataset: list[dict] = []
    x_field: str | None = None
    y_fields: list[str] = []
    title: str | None = None
    currency: str | None = None
    units: str | None = None
    period: list[str] = []
    legend: list[str] = []
    user_requested_type: str | None = None
    confidence: float
    fallback_reason: str | None = None
    renderer_payload: dict | None = None


def describe_visualization(query, spec, *, calculation=None, limitations=(), legacy_text=""):
    import re
    requested = re.search(r'\b(line|bar|column|pie|donut|waterfall|flowchart|table|text)\b', query, re.I)
    preference = requested[1].lower() if requested else None
    if spec is None:
        # Some established renderer families still use validated chart fences.
        # Describe their real payload rather than incorrectly calling them text.
        import json
        from app.domains.model_gateway.tools.chart_tool import build_chart_fence, ChartToolError
        fences = re.findall(r'```chart\s*\n(.*?)```', legacy_text, re.S)
        if fences:
            try:
                legacy = json.loads(fences[-1])
                build_chart_fence(json.dumps(legacy, allow_nan=False))
                rows = legacy.get('data') or legacy.get('series') or legacy.get('cells') or legacy.get('links') or []
                rows = [row if isinstance(row, dict) else {'value':row} for row in rows]
                kind = {'line':'line_chart','area':'line_chart','bar':'bar_chart','pie':'pie_chart'}.get(legacy['type'], legacy['type'])
                return VisualizationIntent(output_type=kind, reason='The existing validated renderer payload supplies this visual.',
                    dataset=rows, renderer_payload=legacy, title=legacy.get('title'), confidence=1.0, user_requested_type=preference)
            except (ValueError, KeyError, ChartToolError):
                pass
        rows = [{'metric':o.name, 'value':str(o.value), 'display_value':o.display_value, 'unit_kind':o.kind} for o in calculation.outputs] if calculation else []
        currencies = {i.currency for i in calculation.inputs if i.currency} if calculation else set()
        return VisualizationIntent(output_type='table' if len(rows)>1 else 'text', dataset=rows,
            x_field='metric' if rows else None, y_fields=['value'] if rows else [],
            currency=next(iter(currencies)) if len(currencies)==1 else None,
            reason='Working and labelled results are clearer than an unnecessary chart.' if calculation else 'Text is the available response format.',
            user_requested_type=preference, confidence=1.0,
            fallback_reason='; '.join(limitations) or None)
    from app.orchestration.visualization.validator import VisualizationValidator
    if not VisualizationValidator().validate(spec).passed:
        return VisualizationIntent(output_type='table', reason='The visual payload did not validate.',
                                    confidence=1.0, user_requested_type=preference, fallback_reason='Use the readable results instead.')
    kind = {'LINE':'line_chart','BAR':'bar_chart','DONUT':'pie_chart','GROUPED_BAR':'bar_chart',
            'TABLE':'table','PROCESS_FLOW':'flowchart','EVIDENCE_GRAPH':'graph'}.get(spec.type, spec.type.lower())
    if spec.variant == 'WATERFALL_CHART':
        kind = 'waterfall'
    data = [p.model_dump(mode='json') for p in spec.data]
    if spec.series:
        data = [{'series':s.name, **p.model_dump(mode='json')} for s in spec.series for p in s.data]
    if spec.donut:
        data = [p.model_dump(mode='json') for p in spec.donut]
    if spec.rows:
        data = spec.rows
    if spec.nodes:
        data = [{'kind':'node', **n.model_dump(mode='json')} for n in spec.nodes] + [{'kind':'edge', **e.model_dump(mode='json')} for e in spec.edges]
    if spec.scatter:
        data = [p.model_dump(mode='json') for p in spec.scatter]
    if spec.cells:
        data = [p.model_dump(mode='json') for p in spec.cells]
    return VisualizationIntent(output_type=kind, reason=spec.summary or 'The validated data supports this format.',
        dataset=data, x_field=spec.encoding.x.field if spec.encoding else None,
        y_fields=[spec.encoding.y.field] if spec.encoding else [], title=spec.title,
        currency=spec.unit if spec.unit in {'GBP','USD','EUR','INR','AED'} else None, units=spec.unit,
        period=[p.x for p in spec.data] if spec.encoding and spec.encoding.x.type == 'temporal' else [],
        legend=[s.name for s in spec.series], user_requested_type=preference, confidence=1.0)


def switch_visual_view(spec, query):
    """A presentation-only follow-up; never re-extract figures from prose."""
    import re
    from app.orchestration.visualization.validator import VisualizationValidator
    requested = re.fullmatch(r'\s*(?:now\s+)?(?:make|show|change|switch|turn|convert)\s+(?:it|this|that|the chart)(?:\s+(?:as|to|into))?\s+(?:a\s+)?(bars?|columns?|line)(?:\s+chart)?[.!?]?(?:\s+Keep every value, month label and currency unchanged\.)?\s*', query, re.I)
    if not requested or spec.type not in {'LINE','BAR'} or spec.variant == 'WATERFALL_CHART':
        return None
    desired = 'LINE' if requested[1].lower() == 'line' else 'BAR'
    if desired == 'LINE' and (spec.encoding is None or spec.encoding.x.type != 'temporal'):
        return None
    changed = spec.model_copy(deep=True, update={'type':desired, 'variant':None, 'renderer':'RECHARTS'})
    return changed if VisualizationValidator().validate(changed).passed else None
