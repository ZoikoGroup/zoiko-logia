"""
Refusal & limitation template registry (ZL-T0-04 §9).

Provides in-memory default templates for every RESTRICTED sub-class and
common limitation patterns. In production these are loaded from the
refusal_templates database table; the in-memory defaults ensure the
system is functional without a database seed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.domains.risk_safety.models import RestrictedSubClass


@dataclass(frozen=True)
class RefusalTemplate:
    template_id: str
    title: str
    body: str
    safe_alternative: str = ""
    restricted_sub_class: Optional[str] = None


# ─── Default Template Registry ─────────────────────────────────────────────

_TEMPLATES: dict[str, RefusalTemplate] = {
    # Academic integrity — hard block, no clarification
    RestrictedSubClass.ACADEMIC_INTEGRITY.value: RefusalTemplate(
        template_id="tpl-academic-001",
        title="Academic Integrity",
        body=(
            "Kriton™ cannot complete exam questions, provide assessment answers, "
            "or assist with academic dishonesty. This restriction is absolute and "
            "cannot be overridden."
        ),
        safe_alternative=(
            "Kriton™ can explain the underlying concept, provide study guidance, "
            "or walk through a similar worked example that is not part of a live "
            "assessment."
        ),
        restricted_sub_class=RestrictedSubClass.ACADEMIC_INTEGRITY.value,
    ),

    # Advice with insufficient context — clarification path
    RestrictedSubClass.ADVICE_INSUFFICIENT_CONTEXT.value: RefusalTemplate(
        template_id="tpl-advice-context-001",
        title="Additional Context Required",
        body=(
            "This question relates to a regulated area that requires specific "
            "context before Kriton™ can provide guidance. The following information "
            "is needed to proceed safely."
        ),
        safe_alternative=(
            "Please specify: (1) your jurisdiction, (2) the entity type, "
            "(3) the applicable accounting framework, and (4) the specific "
            "transaction or scenario you are asking about."
        ),
        restricted_sub_class=RestrictedSubClass.ADVICE_INSUFFICIENT_CONTEXT.value,
    ),

    # Source prohibited — license path
    RestrictedSubClass.SOURCE_PROHIBITED.value: RefusalTemplate(
        template_id="tpl-source-prohibited-001",
        title="Source Not Available",
        body=(
            "The relevant authoritative source cannot be used in this context "
            "due to licensing restrictions, content withdrawal, or policy controls."
        ),
        safe_alternative=(
            "Kriton™ can provide a general educational explanation of the concept "
            "without referencing the restricted source, or route your request to "
            "a human reviewer who may have access."
        ),
        restricted_sub_class=RestrictedSubClass.SOURCE_PROHIBITED.value,
    ),

    # Control bypass — security incident, no details
    RestrictedSubClass.CONTROL_BYPASS.value: RefusalTemplate(
        template_id="tpl-control-bypass-001",
        title="Unable to Process",
        body=(
            "This request cannot be processed. If you believe this is an error, "
            "please contact your system administrator."
        ),
        safe_alternative="",
        restricted_sub_class=RestrictedSubClass.CONTROL_BYPASS.value,
    ),

    # Generic HIGH-risk limitation notice
    "HIGH_RISK_LIMITATION": RefusalTemplate(
        template_id="tpl-high-risk-limit-001",
        title="Important Limitations",
        body=(
            "This response is based on the available source material and the "
            "facts as understood. It represents workflow guidance — not a "
            "substitute for professional judgment."
        ),
        safe_alternative=(
            "Consider consulting a qualified professional for your specific "
            "circumstances. You may also escalate this to a human reviewer."
        ),
    ),

    # Professional boundary notice
    "PROFESSIONAL_BOUNDARY": RefusalTemplate(
        template_id="tpl-boundary-001",
        title="Professional Boundary Notice",
        body=(
            "Kriton™ provides source-governed guidance to support your professional "
            "judgment. It does not act as a licensed accountant, auditor, tax "
            "advisor, or legal counsel."
        ),
        safe_alternative="",
    ),

    # Privacy / Security refusal
    "PRIVACY_SECURITY": RefusalTemplate(
        template_id="tpl-privacy-001",
        title="Privacy or Security Constraint",
        body=(
            "The requested data handling is not permitted under current privacy or security policies. "
            "Internal security details, PII, and confidential tenant data are protected."
        ),
        safe_alternative="Please redact sensitive information or use the administrative path for this request.",
    ),

    # Ontology Unresolved
    "ONTOLOGY_UNRESOLVED": RefusalTemplate(
        template_id="tpl-ontology-001",
        title="Concept Unresolved",
        body=(
            "Kriton™ cannot proceed because the core concept or applicable jurisdiction "
            "for this request cannot be resolved in the accounting ontology."
        ),
        safe_alternative="Please clarify the applicable accounting framework and concept.",
    ),

    # Classification Uncertain
    "CLASSIFICATION_UNCERTAIN": RefusalTemplate(
        template_id="tpl-uncertain-001",
        title="Clarification Required",
        body=(
            "Kriton™ needs to understand the nature of your question better before proceeding. "
            "The safety classifier could not confidently assign a risk route for this query."
        ),
        safe_alternative="Please rephrase your question with more specific details.",
    ),

    # No-source state
    "NO_SOURCE": RefusalTemplate(
        template_id="tpl-no-source-001",
        title="No Approved Source Available",
        body=(
            "Kriton™ does not have an approved source basis to answer this question "
            "definitively. The response has been limited to general educational "
            "information."
        ),
        safe_alternative=(
            "You may request that your administrator add the relevant source "
            "material, or escalate to a subject matter expert."
        ),
    ),

    # Safety degraded state
    "SAFETY_DEGRADED": RefusalTemplate(
        template_id="tpl-degraded-001",
        title="Service Temporarily Limited",
        body=(
            "This request cannot be completed safely at the moment. The safety "
            "classification service is operating in degraded mode."
        ),
        safe_alternative="Please try again shortly or contact your administrator.",
    ),
}


def get_template(key: str) -> RefusalTemplate:
    """Return the refusal template for a given key, with a generic fallback."""
    return _TEMPLATES.get(
        key,
        RefusalTemplate(
            template_id="tpl-fallback",
            title="Request Cannot Be Processed",
            body="Kriton™ is unable to process this request at this time.",
            safe_alternative="Please rephrase your question or contact support.",
        ),
    )


def get_all_templates() -> list[dict]:
    """Return all templates as serializable dicts for the admin UI."""
    return [
        {
            "template_id": t.template_id,
            "title": t.title,
            "body": t.body,
            "safe_alternative": t.safe_alternative,
            "restricted_sub_class": t.restricted_sub_class,
        }
        for t in _TEMPLATES.values()
    ]
