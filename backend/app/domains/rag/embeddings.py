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

import os

# Profiled this session: constructing HuggingFaceEmbedding() cold took ~82s
# on this machine, even though the model is already cached locally
# (~/.cache/huggingface/hub) — almost entirely two avoidable costs:
#   1. huggingface_hub does a network round-trip to check for a newer model
#      revision before falling back to the local cache on every load,
#      regardless of whether the cached copy is already current.
#      HF_HUB_OFFLINE=1 skips that check outright, since a cached model
#      that's already working doesn't need re-validating on every cold
#      start. (~15-20s of the ~82s.)
#   2. transformers auto-probes every ML backend it finds installed
#      (PyTorch, TensorFlow, JAX) even though this model only ever uses
#      PyTorch — TensorFlow's own import/init is extremely heavy. USE_TF=0
#      skips that probe entirely. (~45s of the ~82s — the single biggest
#      piece.)
# setdefault(), not a plain assignment: never overrides an explicit value
# already set in the environment (e.g. a deploy config that deliberately
# wants online mode to pick up a model update). Must run before the first
# `import transformers`/`sentence_transformers` anywhere in the process —
# guaranteed here since this module is the sole entry point every caller
# uses to reach HuggingFaceEmbedding (see this module's docstring).
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("USE_TORCH", "1")

EMBED_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
EMBED_DIM = 384

_embed_model = None


from functools import lru_cache

def get_embed_model():
    global _embed_model
    if _embed_model is None:
        from llama_index.embeddings.huggingface import HuggingFaceEmbedding

        _embed_model = HuggingFaceEmbedding(model_name=EMBED_MODEL_NAME)
    return _embed_model


@lru_cache(maxsize=512)
def get_query_embedding_cached(query: str) -> tuple[float, ...]:
    """LRU cached vector embedding computation for queries.
    Returns a tuple of floats for hashability in lru_cache.
    """
    model = get_embed_model()
    return tuple(model.get_query_embedding(query))

