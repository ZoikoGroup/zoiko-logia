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
