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
            capability.requires_interactivity or not interactive or capability.canonical_type != "FLOW",
            capability.requested_variant is None or capability.requested_variant == plan.requested_chart_variant,
        ))

    matches_in_priority_order = sorted(
        (capability for capability in ROUTABLE_CAPABILITIES if matches(capability)),
        key=lambda capability: capability.priority,
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
        selected_type=selected.selected_type,
        confidence=selected.priority,
    )
