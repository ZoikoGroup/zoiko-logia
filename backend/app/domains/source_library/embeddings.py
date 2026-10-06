"""Text embeddings for the semantic half of governed-passage retrieval.

One interface, swappable provider. The default is a small local model
(BAAI/bge-small-en-v1.5, 384 dimensions) run with the transformers/torch
already installed for the risk classifier: no API key, no per-call cost, and
neither user questions nor licensed source text leave the service. Groq, the
answer model's provider, offers no embedding models.

EMBEDDING_PROVIDER=none (or a model that cannot load) disables the semantic
half; retrieval then runs on keyword matching alone, as it did before.
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
from functools import lru_cache
from typing import Protocol

logger = logging.getLogger(__name__)

EMBEDDING_DIMENSIONS = 384
_DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
# bge models retrieve best when a QUESTION carries this instruction; passages
# are embedded as they are.
_QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "


class Embedder(Protocol):
    model_name: str

    def embed_passages(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class LocalBgeEmbedder:
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self._lock = threading.Lock()
        self._model = None
        self._tokenizer = None

    def _load(self):
        with self._lock:
            if self._model is None:
                from transformers import AutoModel, AutoTokenizer

                self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
                self._model = AutoModel.from_pretrained(self.model_name).eval()
        return self._tokenizer, self._model

    def _embed(self, texts: list[str]) -> list[list[float]]:
        import torch

        tokenizer, model = self._load()
        vectors: list[list[float]] = []
        for start in range(0, len(texts), 32):
            batch = tokenizer(
                texts[start:start + 32], padding=True, truncation=True, max_length=512, return_tensors="pt",
            )
            with torch.no_grad():
                cls = model(**batch).last_hidden_state[:, 0]
            vectors.extend(torch.nn.functional.normalize(cls, dim=-1).tolist())
        return vectors

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._embed([_QUERY_INSTRUCTION + text])[0]


@lru_cache(maxsize=1)
def get_embedder() -> Embedder | None:
    provider = os.getenv("EMBEDDING_PROVIDER", "local").strip().lower()
    if provider in ("", "none", "off", "disabled"):
        return None
    if provider != "local":
        logger.warning("Unknown EMBEDDING_PROVIDER %r; semantic retrieval disabled", provider)
        return None
    return LocalBgeEmbedder(os.getenv("EMBEDDING_MODEL", _DEFAULT_MODEL).strip() or _DEFAULT_MODEL)


async def embed_query(text: str) -> list[float] | None:
    """The question's vector, or None when embeddings are unavailable — a
    missing model must degrade retrieval to keyword-only, never fail it."""
    embedder = get_embedder()
    if embedder is None:
        return None
    try:
        return await asyncio.to_thread(embedder.embed_query, text)
    except Exception as exc:  # noqa: BLE001 — fail soft to keyword retrieval
        logger.warning("Query embedding failed (%s); keyword retrieval only", type(exc).__name__)
        return None


def vector_literal(vector: list[float]) -> str:
    """pgvector's text input format, bound as a parameter and cast ::vector."""
    return "[" + ",".join(f"{value:.6f}" for value in vector) + "]"
