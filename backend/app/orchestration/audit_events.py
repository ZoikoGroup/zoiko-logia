"""
Canonical audit event emitters — ZL-ENG-02 §13.1.

Emits all 19 required named audit events for the Ask Kriton™ query lifecycle.
All writes use record_event_async (durable ordered, chain-hashed) per §13 RG-04.

Audit MUST be written before response is returned. If the audit write path is
unavailable, no answer is returned (fail-safe).

Events emitted (§13.1):
  query_received, request_validated, request_rejected, pre_safety_screen_completed,
  retrieval_started, retrieval_completed, retrieval_failed, risk_classified,
  route_selected, composition_started, composition_completed, composition_failed,
  composition_rejected, human_review_created, refusal_returned, clarification_returned,
  security_incident_recorded, response_finalised, response_returned
"""
from __future__ import annotations

from typing import Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.audit_ledger.event_envelope import record_event_async
from app.orchestration.routing_matrix import CLASSIFIER_VERSION, POLICY_VERSION


async def _emit(
    db: AsyncSession,
    event_name: str,
    query_id: str,
    correlation_id: str,
    tenant_id: str,
    audit_chain_id: str,
    actor_id: str,
    payload: dict[str, Any],
    classification: str = "INTERNAL",
    replay_relevance: str = "SUPPORTING",
) -> None:
    """Internal helper — wraps record_event_async with canonical envelope fields."""
    await record_event_async(
        db,
        event_name=event_name,
        emitting_service="orchestration",
        subject_type="query",
        subject_id=query_id,
        actor_id=actor_id,
        tenant_id=tenant_id,
        correlation_id=correlation_id,
        classification=classification,
        replay_relevance=replay_relevance,
        payload={
            "audit_chain_id": audit_chain_id,
            "classifier_version": CLASSIFIER_VERSION,
            "policy_version": POLICY_VERSION,
            **payload,
        },
    )


async def audit_query_received(db, *, query_id, correlation_id, tenant_id, audit_chain_id, actor_id, query_hash: str):
    await _emit(db, "query_received", query_id, correlation_id, tenant_id, audit_chain_id, actor_id,
                {"query_hash": query_hash}, replay_relevance="REQUIRED")

async def audit_request_validated(db, *, query_id, correlation_id, tenant_id, audit_chain_id, actor_id):
    await _emit(db, "request_validated", query_id, correlation_id, tenant_id, audit_chain_id, actor_id, {})

async def audit_request_rejected(db, *, query_id, correlation_id, tenant_id, audit_chain_id, actor_id, reason: str):
    await _emit(db, "request_rejected", query_id, correlation_id, tenant_id, audit_chain_id, actor_id,
                {"reason": reason}, replay_relevance="REQUIRED")

async def audit_prescreen_completed(db, *, query_id, correlation_id, tenant_id, audit_chain_id, actor_id, passed: bool, trigger: Optional[str] = None):
    await _emit(db, "pre_safety_screen_completed", query_id, correlation_id, tenant_id, audit_chain_id, actor_id,
                {"passed": passed, "trigger": trigger}, replay_relevance="REQUIRED" if not passed else "SUPPORTING")

async def audit_retrieval_started(db, *, query_id, correlation_id, tenant_id, audit_chain_id, actor_id):
    await _emit(db, "retrieval_started", query_id, correlation_id, tenant_id, audit_chain_id, actor_id, {})

async def audit_retrieval_completed(db, *, query_id, correlation_id, tenant_id, audit_chain_id, actor_id,
                                    source_bundle_id: str, confidence_state: str, eligible_count: int):
    await _emit(db, "retrieval_completed", query_id, correlation_id, tenant_id, audit_chain_id, actor_id,
                {"source_bundle_id": source_bundle_id, "confidence_state": confidence_state,
                 "eligible_source_count": eligible_count})

async def audit_retrieval_failed(db, *, query_id, correlation_id, tenant_id, audit_chain_id, actor_id, error: str):
    await _emit(db, "retrieval_failed", query_id, correlation_id, tenant_id, audit_chain_id, actor_id,
                {"error": error}, replay_relevance="REQUIRED")

async def audit_risk_classified(db, *, query_id, correlation_id, tenant_id, audit_chain_id, actor_id,
                                 risk_level: str, confidence_state: str):
    await _emit(db, "risk_classified", query_id, correlation_id, tenant_id, audit_chain_id, actor_id,
                {"risk_level": risk_level, "confidence_state": confidence_state},
                replay_relevance="REQUIRED")

async def audit_route_selected(db, *, query_id, correlation_id, tenant_id, audit_chain_id, actor_id,
                                route: str, risk_level: str, confidence_state: str):
    await _emit(db, "route_selected", query_id, correlation_id, tenant_id, audit_chain_id, actor_id,
                {"route": route, "risk_level": risk_level, "confidence_state": confidence_state,
                 "classifier_version": CLASSIFIER_VERSION, "policy_version": POLICY_VERSION},
                replay_relevance="REQUIRED")

async def audit_composition_started(db, *, query_id, correlation_id, tenant_id, audit_chain_id, actor_id):
    await _emit(db, "composition_started", query_id, correlation_id, tenant_id, audit_chain_id, actor_id, {})

async def audit_composition_completed(db, *, query_id, correlation_id, tenant_id, audit_chain_id, actor_id,
                                       prompt_id: str, output_hash: str):
    await _emit(db, "composition_completed", query_id, correlation_id, tenant_id, audit_chain_id, actor_id,
                {"prompt_id": prompt_id, "output_hash": output_hash})

async def audit_composition_failed(db, *, query_id, correlation_id, tenant_id, audit_chain_id, actor_id, error: str):
    await _emit(db, "composition_failed", query_id, correlation_id, tenant_id, audit_chain_id, actor_id,
                {"error": error}, replay_relevance="REQUIRED")

async def audit_composition_rejected(db, *, query_id, correlation_id, tenant_id, audit_chain_id, actor_id,
                                      failures: list[str], degraded_route: str):
    await _emit(db, "composition_rejected", query_id, correlation_id, tenant_id, audit_chain_id, actor_id,
                {"failures": failures, "degraded_route": degraded_route}, replay_relevance="REQUIRED")

async def audit_human_review_created(db, *, query_id, correlation_id, tenant_id, audit_chain_id, actor_id,
                                      review_case_id: str):
    await _emit(db, "human_review_created", query_id, correlation_id, tenant_id, audit_chain_id, actor_id,
                {"review_case_id": review_case_id}, replay_relevance="REQUIRED")

async def audit_refusal_returned(db, *, query_id, correlation_id, tenant_id, audit_chain_id, actor_id, reason: str):
    await _emit(db, "refusal_returned", query_id, correlation_id, tenant_id, audit_chain_id, actor_id,
                {"reason": reason}, replay_relevance="REQUIRED")

async def audit_clarification_returned(db, *, query_id, correlation_id, tenant_id, audit_chain_id, actor_id,
                                        clarification_cycle: int):
    await _emit(db, "clarification_returned", query_id, correlation_id, tenant_id, audit_chain_id, actor_id,
                {"clarification_cycle": clarification_cycle})

async def audit_security_incident_recorded(db, *, query_id, correlation_id, tenant_id, audit_chain_id, actor_id,
                                            incident_id: str, trigger: str, evidence_reference: str):
    await _emit(db, "security_incident_recorded", query_id, correlation_id, tenant_id, audit_chain_id, actor_id,
                {"incident_id": incident_id, "trigger": trigger, "evidence_reference": evidence_reference},
                classification="SECURITY", replay_relevance="REQUIRED")

async def audit_response_finalised(db, *, query_id, correlation_id, tenant_id, audit_chain_id, actor_id,
                                    outcome: str, route: str):
    await _emit(db, "response_finalised", query_id, correlation_id, tenant_id, audit_chain_id, actor_id,
                {"outcome": outcome, "route": route})

async def audit_response_returned(db, *, query_id, correlation_id, tenant_id, audit_chain_id, actor_id,
                                   latency_ms: float):
    await _emit(db, "response_returned", query_id, correlation_id, tenant_id, audit_chain_id, actor_id,
                {"latency_ms": round(latency_ms, 2)})
