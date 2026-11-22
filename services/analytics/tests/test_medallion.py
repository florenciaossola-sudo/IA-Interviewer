from __future__ import annotations

from pathlib import Path

import pytest

from services.analytics.medallion import materialize_medallion_snapshot
from services.api.persistence import RunPersistence


def test_medallion_snapshot_is_idempotent_and_exports_parquet(tmp_path, monkeypatch) -> None:
    duckdb = pytest.importorskip("duckdb", reason="DuckDB is an optional lakehouse extra")
    warehouse = tmp_path / "warehouse.duckdb"
    artifacts = tmp_path / "parquet"
    monkeypatch.setenv("AI_INTERVIEWER_DUCKDB_PATH", str(warehouse))
    monkeypatch.setenv("AI_INTERVIEWER_LAKEHOUSE_DIR", str(artifacts))
    monkeypatch.delenv("AI_INTERVIEWER_MINIO_ENDPOINT", raising=False)

    persistence = RunPersistence(tmp_path / "runs.sqlite3")
    persistence.save_run_start(
        run_id="iv_lakehouse",
        role="backend_engineer",
        doc_type="role_description",
        state={"role": "backend_engineer", "doc_type": "role_description"},
        payload={"run_id": "iv_lakehouse"},
    )
    persistence.save_turn(
        run_id="iv_lakehouse",
        role="backend_engineer",
        doc_type="role_description",
        state={"route_history": ["conclude"]},
        payload={
            "run_id": "iv_lakehouse",
            "event_type": "turn_completed",
            "competency": "debugging",
            "question": "How do you debug a production issue?",
            "answer": "I inspect traces and reproduce the failure.",
            "evaluation_score": 0.9,
            "evaluation_evidence": ["traces"],
            "grounded_context": [],
            "graph_state": {"route_history": ["conclude"]},
        },
        checkpoint_index=1,
        completed=True,
    )

    first = materialize_medallion_snapshot(1, persistence=persistence)
    second = materialize_medallion_snapshot(1, persistence=persistence)

    assert first["snapshot_id"] == second["snapshot_id"] == 1
    assert len(first["artifacts"]) == 6
    assert all(Path(path).exists() for path in first["artifacts"])
    with duckdb.connect(str(warehouse), read_only=True) as connection:
        assert connection.execute("SELECT count(*) FROM bronze.runs").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM bronze.events").fetchone()[0] == 2