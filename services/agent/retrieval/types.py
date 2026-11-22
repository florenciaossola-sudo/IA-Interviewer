from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CorpusDocument:
    doc_id: str
    doc_type: str
    role: str
    content: str


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc_id: str
    doc_type: str
    role: str
    text: str
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievalResult:
    chunk: Chunk
    score: float


@dataclass(frozen=True)
class RetrievalQuery:
    query_text: str
    top_k: int = 3
    filters: dict[str, str] = field(default_factory=dict)
    include_unmatched: bool = False
