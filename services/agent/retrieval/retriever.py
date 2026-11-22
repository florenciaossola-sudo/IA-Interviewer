from __future__ import annotations

from services.agent.retrieval.embedder import Embedder
from services.agent.retrieval.types import RetrievalQuery, RetrievalResult
from services.agent.retrieval.vector_store import VectorStore


class Retriever:
    def __init__(self, embedder: Embedder, vector_store: VectorStore) -> None:
        self._embedder = embedder
        self._vector_store = vector_store

    def retrieve_context(self, query: RetrievalQuery) -> list[RetrievalResult]:
        embedding = self._embedder.embed(query.query_text)
        return self._vector_store.search(embedding, query)
