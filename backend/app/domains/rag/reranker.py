import asyncio
from typing import List, Dict, Any

RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


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
        self._reranker = None

    def _get_reranker(self):
        if self._reranker is None:
            from llama_index.core.postprocessor import SentenceTransformerRerank
            # Load cross-encoder reranker
            self._reranker = SentenceTransformerRerank(
                model=RERANKER_MODEL,
                top_n=self.top_n
            )
        return self._reranker

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
