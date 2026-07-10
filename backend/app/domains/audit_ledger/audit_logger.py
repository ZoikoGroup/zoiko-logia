from sqlalchemy.ext.asyncio import AsyncSession
from app.domains.audit_ledger.event_envelope import record_event_async

async def log_rag_query_event(
    db: AsyncSession,
    query_id: str,
    actor_id: str,
    tenant_id: str,
    query: str,
    safety_decision: dict,
    retrieved_chunks: list,
    model_id: str,
    latency_ms: float,
    response_text: str,
    validation_result: dict,
) -> None:
    """
    Logs the complete RAG query execution pipeline event into the compliance audit ledger,
    mapping directly to Section 15 compliance formatting.
    """
    payload = {
        "query": query,
        "safety_decision": safety_decision,
        "retrieved_chunks_count": len(retrieved_chunks),
        "retrieved_chunk_ids": [c["node_id"] for c in retrieved_chunks],
        "model_id": model_id,
        "latency_ms": latency_ms,
        "response_text": response_text,
        "validation": validation_result,
    }
    
    await record_event_async(
        db,
        event_name="rag_query_executed",
        emitting_service="rag",
        subject_type="query",
        subject_id=query_id,
        actor_id=actor_id,
        tenant_id=tenant_id,
        correlation_id=query_id,
        classification="INTERNAL",
        replay_relevance="REQUIRED",
        payload=payload
    )
