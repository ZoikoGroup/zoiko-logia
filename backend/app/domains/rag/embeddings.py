"""
Shared embedding model singleton.

ingestion_service.py (write path) and retrieval.py (read path) both need the
same embedding model — previously each module kept its own module-level
_embed_model global and its own get_embed_model(), so any process that
imports both (the FastAPI app itself, which serves both /kriton/upload and
Ask Kriton in the same worker) loaded two independent copies of the model
into memory at once. One shared singleton here, imported by both, halves
that footprint.

Using sentence-transformers/all-MiniLM-L6-v2 (384-dim, ~80MB) rather than
BAAI/bge-m3 (1024-dim, ~2.2GB) — bge-m3 reliably segfaulted on first
inference on a dev machine with <1GB free RAM (PyTorch's native allocator
doesn't raise a catchable Python exception on allocation failure, it
crashes the process). MiniLM trades multilingual support and top-end
retrieval quality for something that actually runs under real memory
constraints; revisit if hosted on a machine with more headroom, or switch
to an API-based embedding provider (e.g. OpenAI) to remove local memory use
entirely — EMBED_DIM below must change to match whichever model is used
(also update ingestion_service.py's and retrieval.py's PGVectorStore
embed_dim=, and the data_kriton_vector_nodes table must be recreated since
pgvector columns are fixed-width).
"""
from __future__ import annotations

EMBED_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
EMBED_DIM = 384

_embed_model = None


def get_embed_model():
    global _embed_model
    if _embed_model is None:
        from llama_index.embeddings.huggingface import HuggingFaceEmbedding

        _embed_model = HuggingFaceEmbedding(model_name=EMBED_MODEL_NAME)
    return _embed_model
