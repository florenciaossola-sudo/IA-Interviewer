from __future__ import annotations

import json
import os
from pathlib import Path

from services.agent.retrieval.embedder import Embedder, TokenFrequencyEmbedder
from services.agent.retrieval.ingestion import IngestionPipeline
from services.agent.retrieval.retriever import Retriever
from services.agent.retrieval.types import Chunk, CorpusDocument, RetrievalQuery, RetrievalResult
from services.agent.retrieval.vector_store import InMemoryVectorStore, PgVectorStore, VectorStore


class GroundedRetrievalService:
    def __init__(self, retriever: Retriever, embedder: Embedder, vector_store: VectorStore) -> None:
        self._retriever = retriever
        self._embedder = embedder
        self._vector_store = vector_store

    @classmethod
    def from_fixture(cls, fixture_path: Path) -> GroundedRetrievalService:
        raw = json.loads(fixture_path.read_text(encoding="utf-8"))
        documents = [CorpusDocument(**item) for item in raw]

        embedder = TokenFrequencyEmbedder()
        vector_store = InMemoryVectorStore()
        pipeline = IngestionPipeline(embedder=embedder, vector_store=vector_store)
        pipeline.ingest_documents(documents)

        retriever = Retriever(embedder=embedder, vector_store=vector_store)
        return cls(retriever=retriever, embedder=embedder, vector_store=vector_store)

    @classmethod
    def from_postgres(
        cls,
        dsn: str,
        fixture_path: Path | None = None,
        bootstrap: bool = True,
        dimensions: int = 256,
    ) -> GroundedRetrievalService:
        embedder = TokenFrequencyEmbedder()
        vector_store = PgVectorStore(dsn=dsn, dimensions=dimensions)

        if bootstrap and fixture_path is not None:
            raw = json.loads(fixture_path.read_text(encoding="utf-8"))
            documents = [CorpusDocument(**item) for item in raw]
            pipeline = IngestionPipeline(embedder=embedder, vector_store=vector_store)
            pipeline.ingest_documents(documents)

        retriever = Retriever(embedder=embedder, vector_store=vector_store)
        return cls(retriever=retriever, embedder=embedder, vector_store=vector_store)

    @classmethod
    def from_environment(
        cls,
        fixture_path: Path,
    ) -> GroundedRetrievalService:
        backend = os.getenv("AI_INTERVIEWER_RETRIEVAL_BACKEND", "fixture").strip().lower()
        if backend == "pgvector":
            dsn = os.getenv("AI_INTERVIEWER_POSTGRES_DSN", "").strip()
            if not dsn:
                raise RuntimeError(
                    "AI_INTERVIEWER_POSTGRES_DSN is required when "
                    "AI_INTERVIEWER_RETRIEVAL_BACKEND=pgvector"
                )

            bootstrap = os.getenv("AI_INTERVIEWER_RETRIEVAL_BOOTSTRAP_FIXTURE", "1") not in {
                "0",
                "false",
                "False",
            }
            dimensions_raw = os.getenv("AI_INTERVIEWER_RETRIEVAL_VECTOR_DIMENSIONS", "256")
            try:
                dimensions = max(8, int(dimensions_raw))
            except ValueError as exc:
                raise RuntimeError(
                    "AI_INTERVIEWER_RETRIEVAL_VECTOR_DIMENSIONS must be an integer"
                ) from exc

            return cls.from_postgres(
                dsn=dsn,
                fixture_path=fixture_path,
                bootstrap=bootstrap,
                dimensions=dimensions,
            )

        return cls.from_fixture(fixture_path)

    def retrieve(
        self,
        query_text: str,
        role: str,
        doc_type: str,
        top_k: int = 2,
        competency: str | None = None,
    ) -> list[RetrievalResult]:
        filters = {"role": role, "doc_type": doc_type}
        if competency:
            competency_filters = {**filters, "competency": competency}
            results = self._retriever.retrieve_context(
                RetrievalQuery(
                    query_text=query_text,
                    filters=competency_filters,
                    top_k=top_k,
                    include_unmatched=True,
                )
            )
            if results:
                return results

        results = self._retriever.retrieve_context(
            RetrievalQuery(query_text=query_text, filters=filters, top_k=top_k)
        )
        if results:
            return results
        # Short answers can share no tokens with the corpus; fall back to the role's own documents.
        return self._retriever.retrieve_context(
            RetrievalQuery(
                query_text=query_text, filters=filters, top_k=top_k, include_unmatched=True
            )
        )

    def ingest_document(self, document: CorpusDocument) -> int:
        pipeline = IngestionPipeline(self._embedder, self._vector_store)
        return pipeline.ingest_documents([document]).chunks_upserted

    def delete_document(self, doc_id: str) -> None:
        self._vector_store.delete_document(doc_id)

    def get_chunk(self, chunk_id: str) -> Chunk | None:
        return self._vector_store.get_chunk(chunk_id)
