from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from services.agent.retrieval.embedder import TokenFrequencyEmbedder
from services.agent.retrieval.ingestion import IngestionPipeline
from services.agent.retrieval.retriever import Retriever
from services.agent.retrieval.types import CorpusDocument, RetrievalQuery
from services.agent.retrieval.vector_store import InMemoryVectorStore


@dataclass(frozen=True)
class LabeledQuery:
    query_text: str
    expected_doc_id: str
    filters: dict[str, str]


@dataclass(frozen=True)
class RetrievalEvalResult:
    total_queries: int
    top1_hits: int
    recall_at_6_hits: int
    retrieved_at_6: int

    @property
    def top1_accuracy(self) -> float:
        if self.total_queries == 0:
            return 0.0
        return self.top1_hits / self.total_queries

    @property
    def recall_at_6(self) -> float:
        return self.recall_at_6_hits / self.total_queries if self.total_queries else 0.0

    @property
    def precision_at_6(self) -> float:
        return self.recall_at_6_hits / self.retrieved_at_6 if self.retrieved_at_6 else 0.0


def load_fixture_documents(fixture_path: Path) -> list[CorpusDocument]:
    raw = json.loads(fixture_path.read_text(encoding="utf-8"))
    return [CorpusDocument(**item) for item in raw]


def run_retrieval_eval() -> RetrievalEvalResult:
    project_root = Path(__file__).resolve().parents[3]
    fixture_path = project_root / "services" / "agent" / "fixtures" / "corpus.json"

    embedder = TokenFrequencyEmbedder()
    vector_store = InMemoryVectorStore()
    pipeline = IngestionPipeline(embedder=embedder, vector_store=vector_store)
    retriever = Retriever(embedder=embedder, vector_store=vector_store)

    pipeline.ingest_documents(load_fixture_documents(fixture_path))

    labeled_queries = [
        LabeledQuery(
            query_text="How can we keep APIs backward compatible when deprecating endpoints?",
            expected_doc_id="backend-role",
            filters={"role": "backend_engineer"},
        ),
        LabeledQuery("How should backend engineers design reliable APIs?", "backend-role", {"role": "backend_engineer"}),
        LabeledQuery("What versioning policies avoid breaking clients?", "backend-role", {"role": "backend_engineer"}),
        LabeledQuery("How should we plan deprecation paths?", "backend-role", {"role": "backend_engineer"}),
        LabeledQuery("How do deterministic CI tests detect flaky tests?", "testing-standards", {"doc_type": "engineering_standard"}),
        LabeledQuery("When should retries include diagnostics?", "testing-standards", {"doc_type": "engineering_standard"}),
        LabeledQuery("How do we track failure rates over time?", "testing-standards", {"doc_type": "engineering_standard"}),
        LabeledQuery("How should CI pipelines detect flaky tests?", "testing-standards", {"doc_type": "engineering_standard"}),
        LabeledQuery("What makes a test deterministic?", "testing-standards", {"doc_type": "engineering_standard"}),
        LabeledQuery("How do frontend engineers support usability?", "frontend-role", {"role": "frontend_engineer"}),
        LabeledQuery("How do we keep accessibility high?", "frontend-role", {"role": "frontend_engineer"}),
        LabeledQuery("How do we build responsive layouts?", "frontend-role", {"role": "frontend_engineer"}),
        LabeledQuery("How do components stay consistent?", "frontend-role", {"role": "frontend_engineer"}),
        LabeledQuery("How should design-system alignment work?", "frontend-role", {"role": "frontend_engineer"}),
        LabeledQuery(
            query_text="What should we do to reduce flaky tests in CI?",
            expected_doc_id="testing-standards",
            filters={"doc_type": "engineering_standard"},
        ),
        LabeledQuery(
            query_text="How do we keep responsive layout and accessibility quality high?",
            expected_doc_id="frontend-role",
            filters={"role": "frontend_engineer"},
        ),
    ]

    hits = 0
    recall_hits = 0
    retrieved_at_6 = 0
    for item in labeled_queries:
        result = retriever.retrieve_context(
            RetrievalQuery(query_text=item.query_text, filters=item.filters, top_k=6)
        )
        if result and result[0].chunk.doc_id == item.expected_doc_id:
            hits += 1
        retrieved_at_6 += len(result)
        if any(hit.chunk.doc_id == item.expected_doc_id for hit in result):
            recall_hits += 1

    return RetrievalEvalResult(
        total_queries=len(labeled_queries),
        top1_hits=hits,
        recall_at_6_hits=recall_hits,
        retrieved_at_6=retrieved_at_6,
    )


def main() -> int:
    result = run_retrieval_eval()
    print(f"Top-1 accuracy: {result.top1_accuracy:.2%} ({result.top1_hits}/{result.total_queries})")
    print(f"Recall@6: {result.recall_at_6:.2%}; Precision@6: {result.precision_at_6:.2%}")

    minimum_recall = 0.80
    minimum_precision = 0.15
    if result.recall_at_6 < minimum_recall or result.precision_at_6 < minimum_precision:
        print(f"FAIL: retrieval quality below thresholds (recall {minimum_recall:.0%}, precision {minimum_precision:.0%})")
        return 1

    print("PASS: retrieval quality is above threshold")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
