import os
import asyncio
from typing import Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from llama_index.core import VectorStoreIndex, Document, StorageContext
from llama_index.core.node_parser import SentenceSplitter
from app.core.config import get_settings

settings = get_settings()

_embed_model = None


def get_embed_model():
    global _embed_model
    if _embed_model is None:
        from llama_index.embeddings.huggingface import HuggingFaceEmbedding

        _embed_model = HuggingFaceEmbedding(model_name="BAAI/bge-m3")
    return _embed_model

async def ingest_document_content(
    file_path: str,
    markdown_content: str,
    metadata: Dict[str, Any],
    db: AsyncSession
) -> str:
    """
    Ingests parsed markdown document content into LlamaIndex.
    Splits text into chunks, generates BAAI bge-m3 embeddings,
    and stores vectors in Supabase pgvector (or fallback local memory vector store).
    """
    embed_model = get_embed_model()

    # Create LlamaIndex document object
    doc = Document(
        text=markdown_content,
        metadata={
            "file_path": file_path,
            "title": metadata["title"],
            "category": metadata["category"],
            "jurisdiction": metadata["jurisdiction_scope"],
            "version": metadata["version_label"],
            "tenant_id": metadata["tenant_id"],
        }
    )
    
    # Sentence splitter setup
    parser = SentenceSplitter(chunk_size=512, chunk_overlap=50)
    nodes = parser.get_nodes_from_documents([doc])
    
    # Store options
    if settings.DATABASE_URL.startswith("postgresql"):
        # Supabase/PostgreSQL pgvector store
        from llama_index.vector_stores.postgres import PGVectorStore
        from sqlalchemy.engine import make_url
        
        # Convert asyncpg to standard prefix for pgvector client
        sync_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
        url_obj = make_url(sync_url)
        
        vector_store = PGVectorStore.from_params(
            host=url_obj.host,
            port=url_obj.port or 5432,
            database=url_obj.database,
            user=url_obj.username,
            password=url_obj.password,
            table_name="kriton_vector_nodes",
            embed_dim=1024, # BAAI/bge-m3 is 1024 dims
        )
        
        storage_context = StorageContext.from_defaults(vector_store=vector_store)
        
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: VectorStoreIndex(
                nodes,
                storage_context=storage_context,
                embed_model=embed_model
            )
        )
    else:
        # Fallback local SimpleVectorStore for zero-friction local SQLite testing
        persist_dir = "./vector_store"
        os.makedirs(persist_dir, exist_ok=True)
        
        storage_context = StorageContext.from_defaults()
        index = VectorStoreIndex(
            nodes,
            storage_context=storage_context,
            embed_model=embed_model
        )
        # Persist index locally
        index.storage_context.persist(persist_dir=persist_dir)
        
    return f"Ingested {len(nodes)} chunks successfully."
