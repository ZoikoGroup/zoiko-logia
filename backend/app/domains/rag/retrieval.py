import contextvars
import os
from typing import List, Dict, Any
from llama_index.core import VectorStoreIndex, StorageContext
from llama_index.core.vector_stores.types import (
    MetadataFilters, MetadataFilter, ExactMatchFilter, FilterOperator, FilterCondition,
)
from app.core.config import get_settings
from app.domains.rag.embeddings import get_embed_model, EMBED_DIM

settings = get_settings()


# Set immediately before every retrieve_documents() call so the pool
# "checkout" listener below can stamp app.tenant_id onto whichever
# connection PGVectorStore ends up using for that call. PGVectorStore
# manages its own connection pool internally rather than reusing
# app.core.database's request-scoped session, so this is the only hook
# point available to make massarius/tenant_scope.py's RLS policy on
# kriton_vector_nodes (current_setting('app.tenant_id')) see per-call
# tenant context at all.
_current_tenant_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "rag_retrieval_tenant_id", default=""
)

_pg_engine_cache: dict[str, tuple] = {}


def _tenant_scoped_pg_engines(sync_url: str, async_url: str) -> tuple:
    """Builds (or returns cached, keyed by connection string) a sync+async
    engine pair for kriton_vector_nodes access where every connection
    checked out of the pool carries this call's tenant context.

    Closes the RLS-bypass gap massarius/tenant_scope.py's module docstring
    flags: this module previously built PGVectorStore straight from
    settings.DATABASE_URL (the superuser role, which Postgres always
    exempts from RLS) with no tenant context set at all. Callers should
    pass settings.APP_DATABASE_URL (the non-superuser, RLS-subject role)
    here — see retrieve_documents below.
    """
    cached = _pg_engine_cache.get(sync_url)
    if cached is not None:
        return cached

    from sqlalchemy import create_engine, event
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_engine(sync_url, pool_pre_ping=True)
    async_engine = create_async_engine(async_url)

    def _set_tenant_on_checkout(dbapi_conn, connection_record, connection_proxy):
        # Session-scoped (not SET LOCAL): mirrors app/core/database.py's
        # get_db(), which sets this on every checkout — even to "" — so a
        # connection reused from the pool never carries over a previous
        # call's tenant_id into a call that has none.
        cursor = dbapi_conn.cursor()
        try:
            cursor.execute("SELECT set_config('app.tenant_id', %s, false)", (_current_tenant_id.get(),))
        finally:
            cursor.close()

    event.listens_for(engine, "checkout")(_set_tenant_on_checkout)
    event.listens_for(async_engine.sync_engine, "checkout")(_set_tenant_on_checkout)

    _pg_engine_cache[sync_url] = (engine, async_engine)
    return engine, async_engine

async def retrieve_documents(
    query: str,
    tenant_id: str,
    jurisdiction: str | None = None,
    top_k: int = 30
) -> List[Dict[str, Any]]:
    """
    Retrieves matching document chunks using hybrid search (vector search + keyword search).
    Applies strict tenant isolation and optional jurisdiction metadata filters.
    """
    embed_model = get_embed_model()

    # 1. Setup metadata filters — a chunk is retrievable if it's shared
    # (is_tenant_private == "false", e.g. a regulatory standard ingested
    # once but meant for every tenant) OR it belongs to this tenant. A flat
    # ExactMatchFilter(tenant_id=...) would hide every shared reference
    # source from any tenant that didn't happen to run ingestion itself —
    # this mirrors the same shared-or-mine condition source_library/
    # service.py already applies to the governed `sources` table.
    # is_tenant_private is stored as the string "true"/"false" (see
    # ingestion_service.py) rather than a JSON boolean, so this compares
    # against a string value too.
    shared_or_mine = MetadataFilters(
        filters=[
            MetadataFilter(key="is_tenant_private", value="false", operator=FilterOperator.EQ),
            MetadataFilter(key="tenant_id", value=tenant_id, operator=FilterOperator.EQ),
        ],
        condition=FilterCondition.OR,
    )
    filters_list = [shared_or_mine]
    if jurisdiction:
        filters_list.append(ExactMatchFilter(key="jurisdiction", value=jurisdiction))

    filters = MetadataFilters(filters=filters_list, condition=FilterCondition.AND)
    
    if not settings.is_sqlite:
        # Real Hybrid PGVector + Full text search using raw SQL or LlamaIndex pgvector extension
        # Let's perform standard LlamaIndex Postgres hybrid search setup
        from llama_index.vector_stores.postgres import PGVectorStore
        from app.core.database import to_async_url, to_sync_url

        # Non-superuser role (RG-02): connecting as the DATABASE_URL owner
        # role would make Postgres exempt every query here from RLS
        # regardless of policy — see _tenant_scoped_pg_engines' docstring.
        # to_sync_url/to_async_url (not a plain .startswith("postgresql")
        # check, which misses the legacy postgres:// scheme Supabase's
        # pooler connection strings use) normalize whichever scheme variant
        # was pasted into .env into the driver each engine actually needs.
        conn_url = settings.APP_DATABASE_URL or settings.DATABASE_URL
        sync_url = to_sync_url(conn_url)
        async_url = to_async_url(conn_url)

        engine, async_engine = _tenant_scoped_pg_engines(sync_url, async_url)

        vector_store = PGVectorStore(
            connection_string=sync_url,
            async_connection_string=async_url,
            table_name="kriton_vector_nodes",
            schema_name="public",
            embed_dim=EMBED_DIM,
            hybrid_search=True,  # enables BM25 (tsvector) + pgvector hybrid retrieval
            engine=engine,
            async_engine=async_engine,
        )

        storage_context = StorageContext.from_defaults(vector_store=vector_store)
        index = VectorStoreIndex.from_vector_store(vector_store, embed_model=embed_model)

        retriever = index.as_retriever(similarity_top_k=top_k, filters=filters)
        token = _current_tenant_id.set(tenant_id)
        try:
            nodes = retriever.retrieve(query)
        finally:
            _current_tenant_id.reset(token)
        
        results = []
        for n in nodes:
            results.append({
                "text": n.node.get_content(),
                "metadata": n.node.metadata,
                "score": n.score,
                "node_id": n.node.node_id
            })
        return results
    else:
        # Fallback local SimpleVectorStore retrieval for SQLite
        persist_dir = "./vector_store"
        if not os.path.exists(persist_dir) or not os.path.exists(os.path.join(persist_dir, "default__vector_store.json")):
            return []
            
        storage_context = StorageContext.from_defaults(persist_dir=persist_dir)
        from llama_index.core import load_index_from_storage
        index = load_index_from_storage(storage_context, embed_model=embed_model)
        
        retriever = index.as_retriever(similarity_top_k=top_k, filters=filters)
        nodes = retriever.retrieve(query)
        
        results = []
        for n in nodes:
            results.append({
                "text": n.node.get_content(),
                "metadata": n.node.metadata,
                "score": n.score or 0.0,
                "node_id": n.node.node_id
            })
        return results
