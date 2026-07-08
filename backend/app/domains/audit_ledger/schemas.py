# Pydantic schemas for the append-only audit/evidence ledger
from datetime import datetime

from pydantic import BaseModel


class AuditEventPublic(BaseModel):
    id: str
    event_name: str
    payload_schema_version: str
    event_time: datetime | None
    ingested_at: datetime | None
    emitting_service: str
    tenant_id: str
    actor_type: str
    actor_id: str | None
    subject_type: str
    subject_id: str
    correlation_id: str | None
    causation_id: str | None
    payload: dict
    payload_hash: str | None
    previous_chain_hash: str | None
    chain_hash: str | None
    classification: str
    replay_relevance: str
    validation_status: str
    legal_hold_id: str | None
    archived: bool
    source: str

    model_config = {"from_attributes": True}


class CompensatingEventCreate(BaseModel):
    correction_type: str
    correction_reason: str
    approver_id: str
    corrected_fields_summary: list[str] = []
    is_material: bool = False
    effective_for_replay: bool = True


class CompensatingEventPublic(BaseModel):
    id: str
    corrects_event_id: str
    correction_type: str
    is_material: bool
    correction_reason: str
    corrected_fields_summary: list[str]
    issued_by: str
    approver_id: str
    effective_for_replay: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ChainVerifyResult(BaseModel):
    tenant_id: str
    passed: bool
    events_checked: int
    first_broken_event_id: str | None


class KnownGap(BaseModel):
    event_class: str
    expected_event_name: str
    gap_reason: str
    impact_on_replay: str


class ReplayTimelineEvent(BaseModel):
    event_id: str
    event_name: str
    event_time: str | None
    emitting_service: str
    payload: dict
    chain_hash: str | None
    replay_relevance: str
    source: str


class ReplayManifest(BaseModel):
    correlation_id: str
    completeness_status: str
    known_gaps: list[KnownGap]
    manifest_trustworthiness: str
    chain_verification_result: str
    generated_by: str
    generated_at: str
    events: list[ReplayTimelineEvent]
    manifest_hash: str
