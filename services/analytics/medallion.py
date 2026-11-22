from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from services.analytics.plane import _build_turn_samples, build_gold_snapshot, collect_bronze
from services.api.persistence import PERSISTENCE


def materialize_medallion_snapshot(
    snapshot_id: int,
    *,
    persistence: Any = PERSISTENCE,
    integrity_repository: Any | None = None,
) -> dict[str, Any]:
    try:
        import duckdb
    except ImportError as exc:
        raise RuntimeError(
            "DuckDB lakehouse export requires installing services/api with the lakehouse extra"
        ) from exc

    warehouse = Path(
        os.getenv("AI_INTERVIEWER_DUCKDB_PATH", "data/lakehouse/warehouse.duckdb")
    )
    warehouse.parent.mkdir(parents=True, exist_ok=True)
    artifacts = Path(os.getenv("AI_INTERVIEWER_LAKEHOUSE_DIR", "data/lakehouse/parquet"))
    dataset = collect_bronze(persistence=persistence, integrity_repository=integrity_repository)
    turns = _build_turn_samples(dataset.events)
    gold = asdict(build_gold_snapshot(bronze=dataset, persistence=persistence))

    with duckdb.connect(str(warehouse)) as connection:
        connection.execute("CREATE SCHEMA IF NOT EXISTS bronze")
        connection.execute("CREATE SCHEMA IF NOT EXISTS silver")
        connection.execute("CREATE SCHEMA IF NOT EXISTS gold")
        connection.execute(
            """CREATE TABLE IF NOT EXISTS bronze.runs (
                snapshot_id BIGINT, run_id VARCHAR, role VARCHAR, doc_type VARCHAR,
                status VARCHAR, state_json VARCHAR, created_at VARCHAR, updated_at VARCHAR,
                PRIMARY KEY(snapshot_id, run_id))"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS bronze.events (
                snapshot_id BIGINT, event_id BIGINT, run_id VARCHAR, event_type VARCHAR,
                payload_json VARCHAR, created_at VARCHAR,
                PRIMARY KEY(snapshot_id, event_id))"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS bronze.reviews (
                snapshot_id BIGINT, review_id BIGINT, run_id VARCHAR, reviewer_name VARCHAR,
                decision VARCHAR, rationale VARCHAR, created_at VARCHAR, updated_at VARCHAR,
                PRIMARY KEY(snapshot_id, review_id))"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS bronze.integrity_dispositions (
                snapshot_id BIGINT, run_id VARCHAR, reviewer VARCHAR, disposition VARCHAR,
                created_at VARCHAR, PRIMARY KEY(snapshot_id, run_id))"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS silver.turns (
                snapshot_id BIGINT, run_id VARCHAR, role VARCHAR, doc_type VARCHAR,
                created_at VARCHAR, route VARCHAR, score DOUBLE,
                PRIMARY KEY(snapshot_id, run_id, created_at))"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS gold.metrics (
                snapshot_id BIGINT, metric VARCHAR, value_json VARCHAR,
                PRIMARY KEY(snapshot_id, metric))"""
        )
        _executemany(
            connection,
            "INSERT INTO bronze.runs VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
            [
                (
                    snapshot_id, run.run_id, run.role, run.doc_type, run.status,
                    run.state_json, run.created_at, run.updated_at,
                )
                for run in dataset.runs
            ],
        )
        _executemany(
            connection,
            "INSERT INTO bronze.events VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
            [
                (
                    snapshot_id, event.event_id, event.run_id, event.event_type,
                    json.dumps(event.payload, sort_keys=True), event.created_at,
                )
                for event in dataset.events
            ],
        )
        _executemany(
            connection,
            "INSERT INTO bronze.reviews VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
            [
                (
                    snapshot_id, review.review_id, review.run_id, review.reviewer_name,
                    review.decision, review.rationale, review.created_at, review.updated_at,
                )
                for review in dataset.reviews
            ],
        )
        _executemany(
            connection,
            "INSERT INTO bronze.integrity_dispositions VALUES (?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
            [
                (
                    snapshot_id, item.run_id, item.reviewer,
                    item.disposition, item.created_at,
                )
                for item in dataset.integrity_dispositions
            ],
        )
        _executemany(
            connection,
            "INSERT INTO silver.turns VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
            [
                (
                    snapshot_id, turn.run_id, turn.role, turn.doc_type,
                    turn.created_at, turn.route, turn.score,
                )
                for turn in turns
            ],
        )
        _executemany(
            connection,
            "INSERT INTO gold.metrics VALUES (?, ?, ?) ON CONFLICT DO NOTHING",
            [
                (snapshot_id, metric, json.dumps(value, sort_keys=True))
                for metric, value in gold.items()
            ],
        )

        output_files: list[Path] = []
        for layer, table in (
            ("bronze", "runs"),
            ("bronze", "events"),
            ("bronze", "reviews"),
            ("bronze", "integrity_dispositions"),
            ("silver", "turns"),
            ("gold", "metrics"),
        ):
            output = artifacts / layer / f"snapshot_id={snapshot_id}" / f"{table}.parquet"
            output.parent.mkdir(parents=True, exist_ok=True)
            output_sql = str(output.resolve()).replace("'", "''")
            connection.execute(
                f"COPY (SELECT * FROM {layer}.{table} WHERE snapshot_id = ?) "
                f"TO '{output_sql}' (FORMAT PARQUET, OVERWRITE_OR_IGNORE TRUE)",
                [snapshot_id],
            )
            output_files.append(output)

    _upload_to_minio(output_files, artifacts)
    return {
        "snapshot_id": snapshot_id,
        "warehouse": str(warehouse),
        "artifacts": [str(path) for path in output_files],
    }


def _executemany(connection: Any, statement: str, rows: list[tuple[Any, ...]]) -> None:
    if rows:
        connection.executemany(statement, rows)


def _upload_to_minio(files: list[Path], artifact_root: Path) -> None:
    endpoint = os.getenv("AI_INTERVIEWER_MINIO_ENDPOINT", "").strip()
    access_key = os.getenv("AI_INTERVIEWER_MINIO_ACCESS_KEY", "").strip()
    secret_key = os.getenv("AI_INTERVIEWER_MINIO_SECRET_KEY", "").strip()
    if not endpoint or not access_key or not secret_key:
        return

    try:
        from minio import Minio
    except ImportError as exc:
        raise RuntimeError(
            "MinIO upload requires installing services/api with the lakehouse extra"
        ) from exc

    parsed = urlparse(endpoint if "://" in endpoint else f"http://{endpoint}")
    client = Minio(
        parsed.netloc,
        access_key=access_key,
        secret_key=secret_key,
        secure=parsed.scheme == "https",
    )
    bucket = os.getenv("AI_INTERVIEWER_MINIO_BUCKET", "ai-interviewer-lakehouse")
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
    for path in files:
        object_name = path.relative_to(artifact_root).as_posix()
        client.fput_object(bucket, object_name, str(path))