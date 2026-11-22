from __future__ import annotations

import re
from dataclasses import dataclass

from services.agent.retrieval.embedder import Embedder
from services.agent.retrieval.types import Chunk, CorpusDocument
from services.agent.retrieval.vector_store import VectorStore


@dataclass
class IngestionStats:
    documents_processed: int
    chunks_upserted: int


class IngestionPipeline:
    def __init__(self, embedder: Embedder, vector_store: VectorStore) -> None:
        self._embedder = embedder
        self._vector_store = vector_store

    def ingest_documents(self, documents: list[CorpusDocument]) -> IngestionStats:
        chunk_count = 0

        for document in documents:
            chunks = _chunk_document(document)
            indexed_chunks = []
            for chunk in chunks:
                embedding = self._embedder.embed(chunk.text)
                indexed_chunks.append((chunk, embedding))
                chunk_count += 1
            self._vector_store.replace_document(document.doc_id, indexed_chunks)

        return IngestionStats(documents_processed=len(documents), chunks_upserted=chunk_count)


def _chunk_document(document: CorpusDocument) -> list[Chunk]:
    raw_blocks = [block.strip() for block in re.split(r"\n\s*\n", document.content) if block.strip()]
    if not raw_blocks:
        raw_blocks = [document.content.strip()] if document.content.strip() else []

    chunks: list[Chunk] = []
    previous_tail = ""
    current_section = ""
    for index, block in enumerate(raw_blocks):
        heading = re.match(r"^(#{1,6})\s+(.+)$", block.splitlines()[0])
        if heading:
            current_section = heading.group(2).strip()
            previous_tail = ""
        text = block
        if previous_tail and previous_tail not in text:
            text = f"{previous_tail}\n{text}"
        chunk_id = f"{document.doc_id}::chunk-{index}"
        chunks.append(
            Chunk(
                chunk_id=chunk_id,
                doc_id=document.doc_id,
                doc_type=document.doc_type,
                role=document.role,
                text=text,
                metadata={
                    "chunk_index": str(index),
                    "section": current_section,
                    "competency": re.sub(r"[^a-z0-9]+", "_", current_section.lower()).strip("_"),
                },
            )
        )
        words = block.split()
        previous_tail = " ".join(words[-18:]) if len(words) > 18 else ""

    return chunks
