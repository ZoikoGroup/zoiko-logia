"""Deterministic deployment eligibility for the F7 model gateway."""
from __future__ import annotations

import os
from dataclasses import dataclass

from app.domains.model_gateway.models import ModelDefinition
from app.domains.model_gateway.schemas import GatewayContext


@dataclass(frozen=True)
class EligibilityDecision:
    allowed: bool
    reason_code: str


def provider_is_configured(provider: str) -> bool:
    key = provider.casefold()
    if key in {"google", "gemini"}:
        return bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
    if key == "groq":
        return bool(os.getenv("GROQ_API_KEY"))
    if key == "openai":
        return bool(os.getenv("OPENAI_API_KEY"))
    if key == "mock":
        return True
    return False


def deployment_eligibility(
    deployment: ModelDefinition, context: GatewayContext,
) -> EligibilityDecision:
    if not context.model_transmission_allowed:
        return EligibilityDecision(False, "MODEL_TRANSMISSION_DENIED")
    if not deployment.enabled or deployment.status.casefold() != "approved":
        return EligibilityDecision(False, "DEPLOYMENT_NOT_APPROVED")
    if not deployment.evaluation_manifest_id:
        return EligibilityDecision(False, "EVALUATION_MANIFEST_MISSING")
    if not deployment.training_opt_out:
        return EligibilityDecision(False, "TRAINING_OPT_OUT_NOT_VERIFIED")
    if deployment.retention_policy.casefold() in {"", "unreviewed"}:
        return EligibilityDecision(False, "RETENTION_POLICY_UNREVIEWED")
    classes = set(deployment.permitted_data_classes or [])
    if context.data_classification not in classes and "*" not in classes:
        return EligibilityDecision(False, "DATA_CLASS_NOT_PERMITTED")
    tasks = set(deployment.supported_task_types or [])
    if context.task_type not in tasks and "*" not in tasks:
        return EligibilityDecision(False, "TASK_NOT_SUPPORTED")
    permitted_tools = set(deployment.allowed_tools or [])
    missing_tools = set(context.requested_tools) - permitted_tools
    if missing_tools:
        return EligibilityDecision(False, "TOOLS_NOT_PERMITTED")
    if (
        context.processing_region
        and deployment.deployment_region
        and context.processing_region.casefold() != deployment.deployment_region.casefold()
    ):
        return EligibilityDecision(False, "REGION_NOT_PERMITTED")
    if not provider_is_configured(deployment.provider):
        return EligibilityDecision(False, "PROVIDER_NOT_CONFIGURED")
    return EligibilityDecision(True, "ELIGIBLE")


def eligible_deployments(
    deployments: list[ModelDefinition], context: GatewayContext,
) -> tuple[list[ModelDefinition], dict[str, str]]:
    decisions = {row.id: deployment_eligibility(row, context) for row in deployments}
    eligible = [row for row in deployments if decisions[row.id].allowed]
    eligible.sort(key=lambda row: (row.priority, row.provider, row.name, row.id))
    return eligible, {key: value.reason_code for key, value in decisions.items()}
