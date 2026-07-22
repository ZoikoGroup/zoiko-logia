"""
Regression tests for a reported latency bug: orchestration/retrieve.py's
infer_category() was rewritten to do real semantic (embedding-based)
category matching, but each request ended up embedding the SAME query
text twice — once inside rag/retrieval.py's retrieve_documents() (for the
actual vector search, via LlamaIndex's internal embedding call) and again,
independently, inside infer_category() (via get_query_embedding_cached()).
The second call was also unwrapped in an executor, blocking the event loop
for its duration.

Fixed by computing the embedding once in orchestration/service.py's
_fetch_raw_chunks() (still inside loop.run_in_executor, so no new blocking
cost) and threading that single value through to both retrieve_documents()
(via a QueryBundle with .embedding pre-set, which LlamaIndex's
VectorIndexRetriever._retrieve() confirmed skips its own embedding call
for) and infer_category() (which now just reuses the value directly
instead of calling get_query_embedding_cached() again).

Requires a live DB + embeddings enabled — run inside the backend container:
    docker compose exec backend python3 tests/test_semantic_retrieval_embedding_reuse.py
"""
import asyncio
import os
import sys
from unittest.mock import patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.domains.rag.embeddings import get_embed_model, get_query_embedding_cached
from app.domains.rag.retrieval import retrieve_documents
from app.orchestration.retrieve import infer_category


def test_infer_category_reuses_provided_embedding_without_recomputing():
    """When a precomputed embedding is passed in, infer_category() must
    return the correct category without ever calling
    get_query_embedding_cached() again for the same text."""
    query = "What is the corporate tax rate?"
    real_embedding = get_query_embedding_cached(query)

    def exploding(*args, **kwargs):
        raise AssertionError("infer_category() re-embedded despite a precomputed embedding being provided")

    with patch("app.orchestration.retrieve.get_query_embedding_cached", exploding):
        category = infer_category(query, query_embedding=real_embedding)
        assert category == "tax"
    print("test_infer_category_reuses_provided_embedding_without_recomputing: PASSED")


def test_infer_category_still_works_without_a_precomputed_embedding():
    """Backward compatibility: standalone/test callers with no embedding
    on hand must still get a correct category (computed inline)."""
    category = infer_category("What is the corporate tax rate?")
    assert category == "tax"
    print("test_infer_category_still_works_without_a_precomputed_embedding: PASSED")


async def test_retrieve_documents_skips_reembedding_when_given_one():
    """Live integration test — the actual mechanism the fix relies on:
    LlamaIndex's VectorIndexRetriever only embeds a QueryBundle when its
    .embedding is None. Patches the embed model's aggregation method (the
    one the retriever calls internally) to explode if invoked, proving
    retrieve_documents() truly skips it when query_embedding is supplied."""
    query = "What is the standard deduction for 2026?"
    embedding = get_query_embedding_cached(query)
    model_cls = type(get_embed_model())

    def exploding(self, *args, **kwargs):
        raise AssertionError("retrieve_documents() re-embedded despite a precomputed embedding being provided")

    with patch.object(model_cls, "get_agg_embedding_from_queries", exploding):
        results = await retrieve_documents(
            query=query, tenant_id="GLOBAL_CONTROL", jurisdiction=None, top_k=3,
            query_embedding=embedding,
        )
        assert isinstance(results, list)
    print("test_retrieve_documents_skips_reembedding_when_given_one: PASSED")


async def test_retrieve_documents_still_embeds_when_none_provided():
    """Sanity check that the test above is meaningful, not vacuous: without
    a precomputed embedding, the same patched method IS still invoked (the
    original, backward-compatible behavior)."""
    query = "What is the standard deduction for 2026?"
    model_cls = type(get_embed_model())

    def exploding(self, *args, **kwargs):
        raise AssertionError("expected re-embed")

    with patch.object(model_cls, "get_agg_embedding_from_queries", exploding):
        try:
            await retrieve_documents(query=query, tenant_id="GLOBAL_CONTROL", jurisdiction=None, top_k=3)
            raise AssertionError("expected retrieve_documents() to re-embed and raise, but it didn't")
        except AssertionError as e:
            assert "expected re-embed" in str(e)
    print("test_retrieve_documents_still_embeds_when_none_provided: PASSED")


async def main():
    test_infer_category_reuses_provided_embedding_without_recomputing()
    test_infer_category_still_works_without_a_precomputed_embedding()
    await test_retrieve_documents_skips_reembedding_when_given_one()
    await test_retrieve_documents_still_embeds_when_none_provided()
    print("All tests passed successfully!")


if __name__ == "__main__":
    asyncio.run(main())
