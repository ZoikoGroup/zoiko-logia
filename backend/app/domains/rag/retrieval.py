import os
from typing import List, Dict, Any
from llama_index.core import VectorStoreIndex, StorageContext
from llama_index.core.vector_stores.types import MetadataFilters, ExactMatchFilter
from app.core.config import get_settings

settings = get_settings()

_embed_model = None


def get_embed_model():
    global _embed_model
    if _embed_model is None:
        from llama_index.embeddings.huggingface import HuggingFaceEmbedding

        _embed_model = HuggingFaceEmbedding(model_name="BAAI/bge-m3")
    return _embed_model

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

    # 1. Setup metadata filters
    filters_list = [ExactMatchFilter(key="tenant_id", value=tenant_id)]
    if jurisdiction:
        filters_list.append(ExactMatchFilter(key="jurisdiction", value=jurisdiction))
        
    filters = MetadataFilters(filters=filters_list)
    
    if settings.DATABASE_URL.startswith("postgresql"):
        # Real Hybrid PGVector + Full text search using raw SQL or LlamaIndex pgvector extension
        # Let's perform standard LlamaIndex Postgres hybrid search setup
        from llama_index.vector_stores.postgres import PGVectorStore
        from sqlalchemy.engine import make_url
        
        sync_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
        url_obj = make_url(sync_url)
        
        vector_store = PGVectorStore.from_params(
            host=url_obj.host,
            port=url_obj.port or 5432,
            database=url_obj.database,
            user=url_obj.username,
            password=url_obj.password,
            table_name="kriton_vector_nodes",
            embed_dim=1024,
            hybrid_search=True, # enables BM25 (tsvector) + pgvector hybrid retrieval
        )
        
        storage_context = StorageContext.from_defaults(vector_store=vector_store)
        index = VectorStoreIndex.from_vector_store(vector_store, embed_model=embed_model)
        
        retriever = index.as_retriever(similarity_top_k=top_k, filters=filters)
        nodes = retriever.retrieve(query)
        
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
