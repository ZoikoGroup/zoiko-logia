import asyncio
import os
from typing import List, Dict, Any

# Same fix as rag/embeddings.py, same reasoning — this is also a
# HuggingFace/sentence-transformers model, cached locally, PyTorch-only.
# setdefault() so an explicit env value elsewhere always wins; harmless if
# rag/embeddings.py already set these first (process-global either way).
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("USE_TORCH", "1")

RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

# Module-level singleton, same pattern as rag/embeddings.py's get_embed_model()
# and risk_safety/risk_classifier.py's _get_classifier_pipeline() — both of
# those cache correctly; this one previously didn't, and it was a real,
# measured bug: Reranker._get_reranker() cached on `self`, an *instance*
# attribute, while two separate `Reranker(top_n=5)` module-level instances
# exist (orchestration/service.py and app/domains/rag/service.py). Startup
# warmup (app/main.py's _warm_up_ml_models) constructed a third, throwaway
# SentenceTransformerRerank that populated neither instance's cache — so
# the first real request still reloaded the model from scratch regardless
# of warmup having "already run" (visible in production logs as a second
# "Loading weights" progress bar during the first POST /ask, after startup
# had already logged one). A true module-level singleton means any
# Reranker instance — and the warmup step — share the exact same loaded
# pipeline; top_n only affects how many results postprocess_nodes()
# returns, not the model itself, so sharing across every known top_n=5
# caller is safe.
_shared_reranker_pipeline = None


def get_reranker_pipeline(top_n: int = 5):
    global _shared_reranker_pipeline
    if _shared_reranker_pipeline is None:
        from llama_index.core.postprocessor import SentenceTransformerRerank

        _shared_reranker_pipeline = SentenceTransformerRerank(model=RERANKER_MODEL, top_n=top_n)
    return _shared_reranker_pipeline


class Reranker:
    """Reranker service wrapper using a lightweight cross-encoder.

    Was BAAI/bge-reranker-large (~2.2GB) — same problem class as
    rag/embeddings.py's model choice: too large to reliably download/load on
    a memory- and disk-constrained dev machine (hit "not enough free disk
    space" downloading it, separately from the embedding model's own
    footprint). ms-marco-MiniLM-L-6-v2 (~90MB) is a standard, well-regarded
    lightweight reranker; revisit if hosted somewhere with more headroom.
    """
    def __init__(self, top_n: int = 5):
        self.top_n = top_n

    def _get_reranker(self):
        return get_reranker_pipeline(self.top_n)

    async def rerank(self, query: str, chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Reranks the top candidate chunks using the cross-encoder above.
        Shrinks target selection (e.g. top-30 candidates down to top-5 most relevant).
        """
        if not chunks:
            return []

        # Convert back to LlamaIndex NodeWithScore format for postprocessor compatibility
        from llama_index.core.schema import NodeWithScore, TextNode
        
        nodes_with_score = []
        for c in chunks:
            node = TextNode(text=c["text"], metadata=c["metadata"], id_=c["node_id"])
            nodes_with_score.append(NodeWithScore(node=node, score=c["score"]))

        # Execute reranker in thread pool since sentence_transformers loading and inference is synchronous
        loop = asyncio.get_event_loop()
        reranked_nodes = await loop.run_in_executor(
            None,
            lambda: self._get_reranker().postprocess_nodes(nodes_with_score, query_str=query)
        )

        results = []
        for rn in reranked_nodes:
            results.append({
                "text": rn.node.get_content(),
                "metadata": rn.node.metadata,
                "score": rn.score,
                "node_id": rn.node.node_id
            })
        return results
