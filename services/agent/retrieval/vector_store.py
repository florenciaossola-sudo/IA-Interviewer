from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from types import ModuleType
from typing import Protocol

from services.agent.retrieval.types import Chunk, RetrievalQuery, RetrievalResult

psycopg: ModuleType | None
try:
    psycopg = import_module("psycopg")
except ImportError:  # pragma: no cover - optional dependency for pgvector backend
    psycopg = None

class VectorStore(Protocol):
    def upsert(self, chunk: Chunk, embedding: dict[str, float]) -> None:
        """Insert or update a chunk embedding."""

    def replace_document(
        self, doc_id: str, indexed_chunks: list[tuple[Chunk, dict[str, float]]]
    ) -> None:
        """Replace all indexed chunks belonging to a document."""

    def delete_document(self, doc_id: str) -> None:
        """Delete all indexed chunks belonging to a document."""

    def get_chunk(self, chunk_id: str) -> Chunk | None:
        """Return a chunk by its stable identifier."""

    def search(
        self, query_embedding: dict[str, float], query: RetrievalQuery
    ) -> list[RetrievalResult]:
        """Search by vector similarity with optional metadata filters."""

    def size(self) -> int:
        """Return total indexed chunks."""


@dataclass
class _StoredVector:
    chunk: Chunk
    embedding: dict[str, float]


class InMemoryVectorStore:
    def __init__(self) -> None:
        self._vectors: dict[str, _StoredVector] = {}

    def upsert(self, chunk: Chunk, embedding: dict[str, float]) -> None:
        self._vectors[chunk.chunk_id] = _StoredVector(chunk=chunk, embedding=embedding)

    def replace_document(
        self, doc_id: str, indexed_chunks: list[tuple[Chunk, dict[str, float]]]
    ) -> None:
        self.delete_document(doc_id)
        for chunk, embedding in indexed_chunks:
            self.upsert(chunk, embedding)

    def delete_document(self, doc_id: str) -> None:
        stale_ids = [
            chunk_id for chunk_id, stored in self._vectors.items()
            if stored.chunk.doc_id == doc_id
        ]
        for chunk_id in stale_ids:
            del self._vectors[chunk_id]

    def get_chunk(self, chunk_id: str) -> Chunk | None:
        stored = self._vectors.get(chunk_id)
        return stored.chunk if stored else None

    def search(
        self, query_embedding: dict[str, float], query: RetrievalQuery
    ) -> list[RetrievalResult]:
        scored: list[RetrievalResult] = []

        for stored in self._vectors.values():
            if not _matches_filters(stored.chunk, query.filters):
                continue

            similarity = _cosine_similarity(query_embedding, stored.embedding)
            if similarity <= 0 and not query.include_unmatched:
                continue
            similarity = max(similarity, 0.0)

            scored.append(RetrievalResult(chunk=stored.chunk, score=similarity))

        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[: query.top_k]

    def size(self) -> int:
        return len(self._vectors)


class PgVectorStore:
    def __init__(self, dsn: str, dimensions: int = 256) -> None:
        if psycopg is None:
            raise RuntimeError(
                "pgvector backend requires psycopg. Install with: "
                "py -3 -m pip install psycopg[binary]"
            )

        self._dsn = dsn
        self._dimensions = dimensions
        self._ensure_schema()

    def upsert(self, chunk: Chunk, embedding: dict[str, float]) -> None:
        dense = sparse_to_dense(embedding, self._dimensions)
        vector_literal = _to_pgvector_literal(dense)
        metadata_json = dict(chunk.metadata)
        metadata_json.setdefault("doc_id", chunk.doc_id)
        metadata_json.setdefault("doc_type", chunk.doc_type)
        metadata_json.setdefault("role", chunk.role)

        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO retrieval_chunks (
                        chunk_id,
                        doc_id,
                        doc_type,
                        role,
                        text,
                        metadata_json,
                        embedding
                    ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::vector)
                    ON CONFLICT (chunk_id) DO UPDATE SET
                        doc_id = EXCLUDED.doc_id,
                        doc_type = EXCLUDED.doc_type,
                        role = EXCLUDED.role,
                        text = EXCLUDED.text,
                        metadata_json = EXCLUDED.metadata_json,
                        embedding = EXCLUDED.embedding
                    """,
                    (
                        chunk.chunk_id,
                        chunk.doc_id,
                        chunk.doc_type,
                        chunk.role,
                        chunk.text,
                        _json_dumps(metadata_json),
                        vector_literal,
                    ),
                )
            connection.commit()

    def replace_document(
        self, doc_id: str, indexed_chunks: list[tuple[Chunk, dict[str, float]]]
    ) -> None:
        prepared = []
        for chunk, embedding in indexed_chunks:
            dense = sparse_to_dense(embedding, self._dimensions)
            metadata_json = dict(chunk.metadata)
            metadata_json.setdefault("doc_id", chunk.doc_id)
            metadata_json.setdefault("doc_type", chunk.doc_type)
            metadata_json.setdefault("role", chunk.role)
            prepared.append(
                (
                    chunk.chunk_id,
                    chunk.doc_id,
                    chunk.doc_type,
                    chunk.role,
                    chunk.text,
                    _json_dumps(metadata_json),
                    _to_pgvector_literal(dense),
                )
            )

        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM retrieval_chunks WHERE doc_id = %s", (doc_id,))
                if prepared:
                    cursor.executemany(
                        """
                        INSERT INTO retrieval_chunks (
                            chunk_id, doc_id, doc_type, role, text, metadata_json, embedding
                        ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::vector)
                        """,
                        prepared,
                    )
            connection.commit()

    def delete_document(self, doc_id: str) -> None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM retrieval_chunks WHERE doc_id = %s", (doc_id,))
            connection.commit()

    def get_chunk(self, chunk_id: str) -> Chunk | None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT chunk_id,doc_id,doc_type,role,text,metadata_json "
                    "FROM retrieval_chunks WHERE chunk_id=%s",
                    (chunk_id,),
                )
                row = cursor.fetchone()
        if row is None:
            return None
        metadata = row[5] if isinstance(row[5], dict) else {}
        return Chunk(
            chunk_id=row[0], doc_id=row[1], doc_type=row[2], role=row[3],
            text=row[4], metadata=metadata,
        )

    def search(
        self, query_embedding: dict[str, float], query: RetrievalQuery
    ) -> list[RetrievalResult]:
        dense = sparse_to_dense(query_embedding, self._dimensions)
        vector_literal = _to_pgvector_literal(dense)
        where_parts: list[str] = []
        params: list[object] = [vector_literal]

        doc_id = query.filters.get("doc_id")
        doc_type = query.filters.get("doc_type")
        role = query.filters.get("role")

        if doc_id is not None:
            where_parts.append("doc_id = %s")
            params.append(doc_id)
        if doc_type is not None:
            where_parts.append("doc_type = %s")
            params.append(doc_type)
        if role is not None:
            where_parts.append("role = %s")
            params.append(role)

        for key, value in query.filters.items():
            if key in {"doc_id", "doc_type", "role"}:
                continue
            where_parts.append("metadata_json ->> %s = %s")
            params.extend([key, value])

        where_sql = ""
        if where_parts:
            where_sql = "WHERE " + " AND ".join(where_parts)

        params.append(max(1, query.top_k))

        sql = (
            "SELECT chunk_id, doc_id, doc_type, role, text, metadata_json, "
            "(1 - (embedding <=> %s::vector)) AS score "
            "FROM retrieval_chunks "
            f"{where_sql} "
            "ORDER BY embedding <=> %s::vector ASC "
            "LIMIT %s"
        )

        # vector literal is used in SELECT score and ORDER BY distance.
        params.insert(-1, vector_literal)

        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                rows = cursor.fetchall()

        results: list[RetrievalResult] = []
        for row in rows:
            metadata = row[5] if isinstance(row[5], dict) else {}
            score = max(float(row[6] or 0.0), 0.0)
            if score <= 0 and not query.include_unmatched:
                continue
            results.append(
                RetrievalResult(
                    chunk=Chunk(
                        chunk_id=row[0],
                        doc_id=row[1],
                        doc_type=row[2],
                        role=row[3],
                        text=row[4],
                        metadata=metadata,
                    ),
                    score=score,
                )
            )

        return results

    def size(self) -> int:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM retrieval_chunks")
                row = cursor.fetchone()

        return int(row[0] if row else 0)

    def _ensure_schema(self) -> None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
                cursor.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS retrieval_chunks (
                        chunk_id TEXT PRIMARY KEY,
                        doc_id TEXT NOT NULL,
                        doc_type TEXT NOT NULL,
                        role TEXT NOT NULL,
                        text TEXT NOT NULL,
                        metadata_json JSONB NOT NULL,
                        embedding VECTOR({self._dimensions}) NOT NULL
                    )
                    """
                )
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_retrieval_chunks_doc_type "
                    "ON retrieval_chunks(doc_type)"
                )
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_retrieval_chunks_role "
                    "ON retrieval_chunks(role)"
                )
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_retrieval_chunks_embedding "
                    "ON retrieval_chunks USING ivfflat (embedding vector_cosine_ops)"
                )
            connection.commit()

    def _connect(self):
        assert psycopg is not None
        return psycopg.connect(self._dsn)


def _matches_filters(chunk: Chunk, filters: dict[str, str]) -> bool:
    if not filters:
        return True

    for key, expected in filters.items():
        if key == "doc_id" and chunk.doc_id != expected:
            return False
        if key == "doc_type" and chunk.doc_type != expected:
            return False
        if key == "role" and chunk.role != expected:
            return False
        if key not in {"doc_id", "doc_type", "role"}:
            actual = chunk.metadata.get(key)
            if actual != expected:
                return False

    return True


def _cosine_similarity(left: dict[str, float], right: dict[str, float]) -> float:
    if not left or not right:
        return 0.0

    if len(left) > len(right):
        left, right = right, left

    return sum(value * right.get(token, 0.0) for token, value in left.items())


def sparse_to_dense(embedding: dict[str, float], dimensions: int) -> list[float]:
    if dimensions <= 0:
        raise ValueError("dimensions must be positive")

    dense = [0.0] * dimensions
    if not embedding:
        return dense

    for token, value in embedding.items():
        index = hash(token) % dimensions
        dense[index] += float(value)

    norm = sum(item * item for item in dense) ** 0.5
    if norm == 0:
        return dense

    return [item / norm for item in dense]


def _to_pgvector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{item:.10f}" for item in values) + "]"


def _json_dumps(value: dict[str, str]) -> str:
    import json

    return json.dumps(value, sort_keys=True)
