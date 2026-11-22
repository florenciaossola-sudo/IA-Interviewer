import os
from pathlib import Path

from services.agent.evals.retrieval_eval import load_fixture_documents, run_retrieval_eval
from services.agent.retrieval.embedder import TokenFrequencyEmbedder
from services.agent.retrieval.ingestion import IngestionPipeline
from services.agent.retrieval.retriever import Retriever
from services.agent.retrieval.service import GroundedRetrievalService
from services.agent.retrieval.types import CorpusDocument, RetrievalQuery
from services.agent.retrieval.vector_store import InMemoryVectorStore, sparse_to_dense


def _fixture_path() -> Path:
    return Path(__file__).resolve().parents[1] / "fixtures" / "corpus.json"


def test_ingestion_is_idempotent_for_same_documents() -> None:
    docs = load_fixture_documents(_fixture_path())
    embedder = TokenFrequencyEmbedder()
    store = InMemoryVectorStore()
    pipeline = IngestionPipeline(embedder=embedder, vector_store=store)

    first = pipeline.ingest_documents(docs)
    second = pipeline.ingest_documents(docs)

    assert first.documents_processed == len(docs)
    assert second.documents_processed == len(docs)
    assert store.size() == first.chunks_upserted


def test_reingestion_removes_stale_chunks_when_document_shrinks() -> None:
    embedder = TokenFrequencyEmbedder()
    store = InMemoryVectorStore()
    pipeline = IngestionPipeline(embedder=embedder, vector_store=store)

    pipeline.ingest_documents(
        [CorpusDocument("manual", "guide", "all", "First paragraph.\n\nSecond paragraph.")]
    )
    pipeline.ingest_documents([CorpusDocument("manual", "guide", "all", "Updated paragraph.")])

    assert store.size() == 1
    results = Retriever(embedder=embedder, vector_store=store).retrieve_context(
        RetrievalQuery(query_text="Second paragraph", top_k=5)
    )
    assert all("Second paragraph" not in result.chunk.text for result in results)


def test_retrieval_respects_role_filter() -> None:
    docs = load_fixture_documents(_fixture_path())
    embedder = TokenFrequencyEmbedder()
    store = InMemoryVectorStore()
    pipeline = IngestionPipeline(embedder=embedder, vector_store=store)
    retriever = Retriever(embedder=embedder, vector_store=store)

    pipeline.ingest_documents(docs)

    results = retriever.retrieve_context(
        RetrievalQuery(
            query_text="How to improve responsive design and component consistency?",
            filters={"role": "frontend_engineer"},
            top_k=1,
        )
    )

    assert results
    assert results[0].chunk.role == "frontend_engineer"


def test_retrieval_eval_meets_threshold() -> None:
    result = run_retrieval_eval()

    assert result.total_queries == 16
    assert result.top1_accuracy >= 0.80


def test_sparse_to_dense_is_stable_and_normalized() -> None:
    embedding = {"alpha": 0.7, "beta": 0.3}
    dense_left = sparse_to_dense(embedding, dimensions=32)
    dense_right = sparse_to_dense(embedding, dimensions=32)

    assert len(dense_left) == 32
    assert dense_left == dense_right
    assert max(abs(value) for value in dense_left) <= 1.0


def test_retrieval_service_environment_defaults_to_fixture() -> None:
    fixture = _fixture_path()
    original = os.environ.pop("AI_INTERVIEWER_RETRIEVAL_BACKEND", None)
    try:
        service = GroundedRetrievalService.from_environment(fixture)
    finally:
        if original is not None:
            os.environ["AI_INTERVIEWER_RETRIEVAL_BACKEND"] = original

    results = service.retrieve(
        query_text="How do you keep API versions backward compatible?",
        role="backend_engineer",
        doc_type="role_description",
        top_k=1,
    )
    assert results


def test_competency_retrieval_stays_with_matching_markdown_section() -> None:
    embedder = TokenFrequencyEmbedder()
    store = InMemoryVectorStore()
    pipeline = IngestionPipeline(embedder=embedder, vector_store=store)
    document = CorpusDocument(
        "frontend-role",
        "role_description",
        "sr_frontend_engineer",
        "## Debugging\n\nUse browser profiling and heap snapshots.\n\n"
        "## API Design\n\nUse optimistic updates and versioned API contracts.\n\n"
        "## Test Reliability\n\nReplace fixed sleeps with deterministic Playwright assertions.",
    )
    pipeline.ingest_documents([document])
    service = GroundedRetrievalService(
        Retriever(embedder=embedder, vector_store=store), embedder, store
    )

    results = service.retrieve(
        query_text="test reliability flaky asynchronous rendering",
        role="sr_frontend_engineer",
        doc_type="role_description",
        top_k=2,
        competency="test_reliability",
    )

    assert results
    assert all(result.chunk.metadata["competency"] == "test_reliability" for result in results)
    assert any("Playwright" in result.chunk.text for result in results)
    assert all("browser profiling" not in result.chunk.text for result in results)
    assert all("optimistic updates" not in result.chunk.text for result in results)
