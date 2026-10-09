"""A diagram of already released accounting statements, never new claims.

Only the ordinary credit-sale lifecycle is recognised. Missing statements
withhold the diagram; no model text is executed as diagram syntax.
"""
import re

from app.orchestration.visualization.spec import GraphEdge, GraphNode, VisualizationSpec
from app.orchestration.visualization.validator import VisualizationValidator


def credit_sale_diagram(query: str, released_answer: str, *, spec_id: str, sources: list[str]) -> VisualizationSpec | None:
    if not re.search(r"\bcredit sale\b", query, re.I) or not re.search(r"\bdiagram\b", query, re.I):
        return None
    if re.search(r"\b(?:interest|financing|accreted)\b", released_answer, re.I):
        return None  # A financing arrangement needs a different lifecycle.
    released_answer = released_answer.replace("’", "'")
    sentences = [s.strip(" -*\n") for s in re.split(r"(?<=[.!?])\s+|\n+", released_answer)]
    patterns = [
        r"\brevenue\b.*\b(?:record|recognis|recogniz)",
        r"\breceivable\b.*\b(?:creat|record|recognis|recogniz)",
        r"(?:\bno cash\b|\bcash\b.*\bunchanged\b)",
        r"^(?:the )?cash\b.*\b(?:increas)",
        r"\breceivable\b.*\b(?:reduc|decreas)",
    ]
    # Prefix matches accommodate recognises/recognised, increases/increased.
    negation = re.compile(r"\b(?:no|not|never|cannot|neither|without|unable|fails?|failed)\b|n't\b", re.I)

    def negated(sentence: str) -> bool:
        # The absence of cash at sale is the one expected negative assertion.
        remaining = re.sub(r"\bno cash (?:is |was )?(?:received|collected)\b", "", sentence, flags=re.I)
        return bool(negation.search(remaining))
    found = [next((sentence for sentence in sentences
                   if re.search(pattern, sentence, re.I) and not negated(sentence)), None)
             for pattern in patterns]
    # Withhold contradictory lifecycles even if an affirmative duplicate also appears.
    if any(negated(sentence) and any(re.search(pattern, sentence, re.I) for pattern in patterns)
           for sentence in sentences):
        return None
    if any(sentence is None or len(sentence) > 220 for sentence in found):
        return None
    sale = "At sale: " + " ".join(found[:3])
    payment = "On payment: " + " ".join(found[3:])
    spec = VisualizationSpec(
        id=spec_id, type="PROCESS_FLOW", family="PROCESS", renderer="FLOW_ADAPTER",
        title="Credit sale and later payment", summary="Statements from the verified answer, shown in time order.",
        nodes=[GraphNode(id="sale", label=sale, type="stage"), GraphNode(id="payment", label=payment, type="stage")],
        edges=[GraphEdge(source="sale", target="payment", type="later payment")],
        sources=sources, flow_engine="mermaid",
    )
    return spec if VisualizationValidator().validate(spec).passed else None
