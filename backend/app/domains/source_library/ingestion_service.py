import os
import asyncio
from typing import Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from llama_index.core import VectorStoreIndex, Document, StorageContext
from llama_index.core.node_parser import SentenceSplitter
from app.core.config import get_settings
from app.domains.rag.embeddings import get_embed_model, EMBED_DIM

settings = get_settings()

async def ingest_document_content(
    file_path: str,
    markdown_content: str,
    metadata: Dict[str, Any],
    db: AsyncSession
) -> str:
    """
    Ingests parsed markdown document content into LlamaIndex.
    Splits text into chunks, generates embeddings (see rag/embeddings.py for
    the active model), and stores vectors in Supabase pgvector (or fallback
    local memory vector store).
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
            # Real sources.id this chunk was embedded from — orchestration/
            # retrieve.py looks this up against the governance record (status,
            # jurisdiction, tenant visibility) rather than trusting this
            # chunk's own metadata as a stand-in for an ACTIVE/approved
            # source. Chunks ingested without a real source_id are excluded
            # there, not silently treated as eligible.
            "source_id": metadata.get("source_id", ""),
        }
    )
    
    # Sentence splitter setup
    parser = SentenceSplitter(chunk_size=512, chunk_overlap=50)
    nodes = parser.get_nodes_from_documents([doc])
    
    # Store options — not a plain .startswith("postgresql") check, which
    # misses the legacy postgres:// scheme (e.g. Supabase pooler URLs);
    # matches the is_sqlite convention used everywhere else in the app.
    if not settings.is_sqlite:
        # Supabase/PostgreSQL pgvector store
        from llama_index.vector_stores.postgres import PGVectorStore
        from app.core.database import to_async_url, to_sync_url

        # Pass whole connection strings, not host=/user=/password= components.
        # PGVectorStore.from_params only re-encodes user/password into an
        # f-string URL when you give it components — url_obj.password from
        # make_url() comes back URL-*decoded*, so a password containing "@"
        # (e.g. Supabase-issued passwords like "Zoikologia@123@") gets
        # re-interpolated as a literal "@" and corrupts the host on the
        # rebuilt string's next parse. Passing connection_string= directly
        # (already correctly encoded) skips that rebuild entirely.
        sync_url = to_sync_url(settings.DATABASE_URL)
        async_url = to_async_url(settings.DATABASE_URL)

        vector_store = PGVectorStore.from_params(
            connection_string=sync_url,
            async_connection_string=async_url,
            table_name="kriton_vector_nodes",
            embed_dim=EMBED_DIM,
            hybrid_search=True,  # must match retrieval.py's flag: the BM25/tsvector column
                                  # this creates on the table is what retrieval-side hybrid
                                  # search reads from — omitting it here left ingestion and
                                  # retrieval configuring the table inconsistently.
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
