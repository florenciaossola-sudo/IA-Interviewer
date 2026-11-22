from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from services.agent.retrieval.service import GroundedRetrievalService
from services.api import main as api_main
from services.api.corpus import CorpusDocumentManager


def test_admin_role_crud_round_trip(tmp_path: Path, monkeypatch) -> None:
    api_main.RUN_STATE.clear()
    monkeypatch.setattr(
        api_main.PERSISTENCE,
        "_db_path",
        tmp_path / "ai_interviewer.sqlite3",
    )
    api_main.PERSISTENCE.ensure_schema()

    client = TestClient(api_main.app)
    payload = {
        "role_id": "sr_software_engineer",
        "title": "SR Software Engineer (Data)",
        "location": "Rochester, New York (Remote)",
        "description": "Design AI agent systems and data pipelines.",
    }

    response = client.post("/admin/roles", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["role_id"] == "sr_software_engineer"
    assert body["title"] == "SR Software Engineer (Data)"

    chunks = api_main.RETRIEVAL_SERVICE.retrieve(
        query_text="Design AI agent systems and data pipelines.",
        role="sr_software_engineer",
        doc_type="role_description",
        top_k=5,
    )
    assert chunks
    role_chunk = next(
        item.chunk for item in chunks if item.chunk.doc_id.startswith("admin-role-description-")
    )
    assert api_main.RETRIEVAL_SERVICE.get_chunk(role_chunk.chunk_id) == role_chunk

    response = client.get("/admin/roles")
    assert response.status_code == 200, response.text
    roles = response.json()
    assert any(item["role_id"] == "sr_software_engineer" for item in roles)

    detail = client.get("/admin/roles/sr_software_engineer")
    assert detail.status_code == 200, detail.text
    assert detail.json()["location"] == "Rochester, New York (Remote)"


def test_admin_corpus_upload_status_retry_and_delete(tmp_path: Path, monkeypatch) -> None:
    fixture_path = Path(__file__).resolve().parents[2] / "agent" / "fixtures" / "corpus.json"
    retrieval_service = GroundedRetrievalService.from_fixture(fixture_path)
    manager = CorpusDocumentManager(retrieval_service, tmp_path / "corpus")
    monkeypatch.setattr(api_main, "CORPUS_MANAGER", manager)
    client = TestClient(api_main.app)

    failed = client.post(
        "/admin/corpus/documents",
        params={
            "filename": "guide.md",
            "doc_type": "engineering_standard",
            "role": "backend_engineer",
        },
        content=b"\xff",
        headers={"Content-Type": "application/octet-stream"},
    )
    assert failed.status_code == 200, failed.text
    failed_record = failed.json()
    assert failed_record["status"] == "failed"
    assert failed_record["error"]

    uploaded = client.post(
        "/admin/corpus/documents",
        params={
            "filename": "guide.md",
            "doc_type": "engineering_standard",
            "role": "backend_engineer",
        },
        content=b"Prefer backward-compatible API changes.",
        headers={"Content-Type": "application/octet-stream"},
    )
    assert uploaded.status_code == 200, uploaded.text
    ingested_record = uploaded.json()
    assert ingested_record["doc_id"] == failed_record["doc_id"]
    assert ingested_record["status"] == "ingested"
    assert ingested_record["chunk_count"] == 1

    indexed = retrieval_service.retrieve(
        query_text="Prefer backward-compatible API changes.",
        role="backend_engineer",
        doc_type="engineering_standard",
        top_k=5,
    )
    assert any(item.chunk.doc_id == ingested_record["doc_id"] for item in indexed)

    restored_service = GroundedRetrievalService.from_fixture(fixture_path)
    CorpusDocumentManager(restored_service, tmp_path / "corpus")
    restored = restored_service.retrieve(
        query_text="Prefer backward-compatible API changes.",
        role="backend_engineer",
        doc_type="engineering_standard",
        top_k=5,
    )
    assert any(item.chunk.doc_id == ingested_record["doc_id"] for item in restored)

    listed = client.get("/admin/corpus/documents")
    assert listed.status_code == 200, listed.text
    assert [item["doc_id"] for item in listed.json()] == [ingested_record["doc_id"]]

    reingested = client.post(
        f"/admin/corpus/documents/{ingested_record['doc_id']}/ingest"
    )
    assert reingested.status_code == 200, reingested.text
    assert reingested.json()["status"] == "ingested"

    failed_update = client.post(
        "/admin/corpus/documents",
        params={
            "filename": "guide.md",
            "doc_type": "engineering_standard",
            "role": "backend_engineer",
        },
        content=b"\xff",
        headers={"Content-Type": "application/octet-stream"},
    )
    assert failed_update.status_code == 200
    assert failed_update.json()["status"] == "failed"
    after_failed_update = retrieval_service.retrieve(
        query_text="Prefer backward-compatible API changes.",
        role="backend_engineer",
        doc_type="engineering_standard",
        top_k=5,
    )
    assert all(item.chunk.doc_id != ingested_record["doc_id"] for item in after_failed_update)

    deleted = client.delete(f"/admin/corpus/documents/{ingested_record['doc_id']}")
    assert deleted.status_code == 204
    assert client.get("/admin/corpus/documents").json() == []
    after_delete = retrieval_service.retrieve(
        query_text="Prefer backward-compatible API changes.",
        role="backend_engineer",
        doc_type="engineering_standard",
        top_k=5,
    )
    assert all(item.chunk.doc_id != ingested_record["doc_id"] for item in after_delete)


def test_admin_corpus_retry_recovers_from_transient_ingestion_failure(
    tmp_path: Path, monkeypatch
) -> None:
    fixture_path = Path(__file__).resolve().parents[2] / "agent" / "fixtures" / "corpus.json"
    retrieval_service = GroundedRetrievalService.from_fixture(fixture_path)
    original_ingest = retrieval_service.ingest_document
    attempts = 0

    def fail_once(document):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("Temporary embedding service failure")
        return original_ingest(document)

    monkeypatch.setattr(retrieval_service, "ingest_document", fail_once)
    manager = CorpusDocumentManager(retrieval_service, tmp_path / "corpus")
    monkeypatch.setattr(api_main, "CORPUS_MANAGER", manager)
    client = TestClient(api_main.app)

    uploaded = client.post(
        "/admin/corpus/documents",
        params={
            "filename": "retry.md",
            "doc_type": "engineering_standard",
            "role": "backend_engineer",
        },
        content=b"Retry this document after a transient error.",
        headers={"Content-Type": "application/octet-stream"},
    )
    assert uploaded.status_code == 200, uploaded.text
    failed_record = uploaded.json()
    assert failed_record["status"] == "failed"
    assert "Temporary embedding service failure" in failed_record["error"]

    retried = client.post(f"/admin/corpus/documents/{failed_record['doc_id']}/ingest")
    assert retried.status_code == 200, retried.text
    assert retried.json()["status"] == "ingested"
    assert attempts == 2
