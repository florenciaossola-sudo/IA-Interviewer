from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

from services.agent.retrieval import GroundedRetrievalService
from services.agent.retrieval.types import CorpusDocument

MAX_DOCUMENT_BYTES = 15 * 1024 * 1024
SUPPORTED_SUFFIXES = {".docx", ".md", ".pdf"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class CorpusDocumentRecord:
    doc_id: str
    filename: str
    doc_type: str
    role: str
    status: str
    chunk_count: int
    created_at: str
    updated_at: str
    last_ingested_at: str | None
    error: str | None


class CorpusDocumentManager:
    def __init__(
        self,
        retrieval_service: GroundedRetrievalService,
        data_dir: Path,
    ) -> None:
        self._retrieval_service = retrieval_service
        self._data_dir = data_dir
        self._documents_dir = data_dir / "documents"
        self._catalog_path = data_dir / "catalog.json"
        self._lock = threading.RLock()
        self._documents_dir.mkdir(parents=True, exist_ok=True)
        self._records = self._read_catalog()
        self._restore_index()

    def list_documents(self) -> list[CorpusDocumentRecord]:
        with self._lock:
            return sorted(self._records.values(), key=lambda record: record.filename.lower())

    def upload(
        self,
        filename: str,
        content: bytes,
        doc_type: str,
        role: str,
    ) -> CorpusDocumentRecord:
        safe_name = Path(filename.replace("\\", "/")).name.strip()
        suffix = Path(safe_name).suffix.lower()
        if not safe_name or suffix not in SUPPORTED_SUFFIXES:
            raise ValueError("Supported document formats are .pdf, .docx, and .md")
        if not content:
            raise ValueError("The uploaded document is empty")
        if len(content) > MAX_DOCUMENT_BYTES:
            raise ValueError("The uploaded document exceeds the 15 MB limit")
        clean_doc_type = doc_type.strip()
        clean_role = role.strip()
        if not clean_doc_type or not clean_role:
            raise ValueError("Document type and role are required")

        doc_id = hashlib.sha256(
            f"{safe_name.lower()}\0{clean_doc_type}\0{clean_role}".encode("utf-8")
        ).hexdigest()[:20]
        with self._lock:
            previous = self._records.get(doc_id)
            now = _utc_now()
            record = CorpusDocumentRecord(
                doc_id=doc_id,
                filename=safe_name,
                doc_type=clean_doc_type,
                role=clean_role,
                status="ingesting",
                chunk_count=previous.chunk_count if previous else 0,
                created_at=previous.created_at if previous else now,
                updated_at=now,
                last_ingested_at=previous.last_ingested_at if previous else None,
                error=None,
            )
            path = self._document_path(record)
            path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = path.with_suffix(path.suffix + ".tmp")
            temp_path.write_bytes(content)
            temp_path.replace(path)
            self._records[doc_id] = record
            self._write_catalog()
            return self._ingest_locked(record, content)

    def ingest(self, doc_id: str) -> CorpusDocumentRecord:
        with self._lock:
            record = self._records.get(doc_id)
            if record is None:
                raise KeyError(doc_id)
            path = self._document_path(record)
            try:
                content = path.read_bytes()
            except OSError as exc:
                return self._set_failed(record, f"Stored source file is unavailable: {exc}")
            return self._ingest_locked(record, content)

    def delete(self, doc_id: str) -> bool:
        with self._lock:
            record = self._records.get(doc_id)
            if record is None:
                return False
            self._retrieval_service.delete_document(doc_id)
            path = self._document_path(record)
            path.unlink(missing_ok=True)
            try:
                path.parent.rmdir()
            except OSError:
                pass
            del self._records[doc_id]
            self._write_catalog()
            return True

    def _ingest_locked(self, record: CorpusDocumentRecord, content: bytes) -> CorpusDocumentRecord:
        try:
            text = _extract_text(record.filename, content)
            if not text.strip():
                raise ValueError("No readable text was found in the document")
            chunk_count = self._retrieval_service.ingest_document(
                CorpusDocument(
                    doc_id=record.doc_id,
                    doc_type=record.doc_type,
                    role=record.role,
                    content=text,
                )
            )
        except Exception as exc:
            self._retrieval_service.delete_document(record.doc_id)
            return self._set_failed(record, str(exc))

        updated = CorpusDocumentRecord(
            **{
                **asdict(record),
                "status": "ingested",
                "chunk_count": chunk_count,
                "updated_at": _utc_now(),
                "last_ingested_at": _utc_now(),
                "error": None,
            }
        )
        self._records[record.doc_id] = updated
        self._write_catalog()
        return updated

    def _set_failed(self, record: CorpusDocumentRecord, error: str) -> CorpusDocumentRecord:
        updated = CorpusDocumentRecord(
            **{
                **asdict(record),
                "status": "failed",
                "updated_at": _utc_now(),
                "error": error[:500],
            }
        )
        self._records[record.doc_id] = updated
        self._write_catalog()
        return updated

    def _restore_index(self) -> None:
        for record in list(self._records.values()):
            if record.status != "ingested":
                continue
            try:
                self._ingest_locked(record, self._document_path(record).read_bytes())
            except OSError as exc:
                self._set_failed(record, f"Stored source file is unavailable: {exc}")

    def _document_path(self, record: CorpusDocumentRecord) -> Path:
        return self._documents_dir / record.doc_id / record.filename

    def _read_catalog(self) -> dict[str, CorpusDocumentRecord]:
        if not self._catalog_path.exists():
            return {}
        raw: Any = json.loads(self._catalog_path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError("Corpus catalog must contain a list")
        return {
            item["doc_id"]: CorpusDocumentRecord(**item)
            for item in raw
            if isinstance(item, dict) and "doc_id" in item
        }

    def _write_catalog(self) -> None:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        temp_path = self._catalog_path.with_suffix(".json.tmp")
        records = [asdict(record) for record in self._records.values()]
        temp_path.write_text(json.dumps(records, indent=2), encoding="utf-8")
        temp_path.replace(self._catalog_path)


def _extract_text(filename: str, content: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".md":
        return content.decode("utf-8-sig")
    if suffix == ".docx":
        from docx import Document

        document = Document(BytesIO(content))
        paragraphs = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
        for table in document.tables:
            paragraphs.extend(
                " | ".join(cell.text.strip() for cell in row.cells)
                for row in table.rows
                if any(cell.text.strip() for cell in row.cells)
            )
        return "\n\n".join(paragraphs)
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(content))
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)
    raise ValueError("Supported document formats are .pdf, .docx, and .md")