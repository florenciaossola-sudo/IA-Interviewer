from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from airflow import DAG
from airflow.operators.python import PythonOperator

from services.analytics.scheduler import run_drift_check_job, run_snapshot_sync_job
from services.api.interviews import InterviewRepository
from services.api.persistence import PERSISTENCE


def _integrity_repository() -> InterviewRepository:
    dsn = os.getenv("AI_INTERVIEWER_POSTGRES_DSN", "").strip()
    if not dsn:
        raise RuntimeError("AI_INTERVIEWER_POSTGRES_DSN is required for analytics sync")
    return InterviewRepository(
        Path("/opt/ai-interviewer/data/interviews.sqlite3"), postgres_dsn=dsn
    )


def sync_analytics() -> dict:
    return run_snapshot_sync_job(
        label="airflow-nightly",
        integrity_repository=_integrity_repository(),
    )


def check_drift() -> dict:
    snapshots = PERSISTENCE.list_analytics_snapshots(limit=2)
    if len(snapshots) < 2:
        return {"status": "skipped", "reason": "Two snapshots are required for drift checks"}
    return run_drift_check_job(
        baseline_snapshot_id=snapshots[1].snapshot_id,
        candidate_snapshot_id=snapshots[0].snapshot_id,
        persistence=PERSISTENCE,
    )


with DAG(
    dag_id="nightly_analytics_sync",
    description="Build Bronze/Silver/Gold analytics and check drift",
    start_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
    schedule="0 2 * * *",
    catchup=False,
    max_active_runs=1,
    tags=["ai-interviewer", "analytics"],
) as dag:
    sync = PythonOperator(task_id="sync_bronze_silver_gold", python_callable=sync_analytics)
    drift = PythonOperator(task_id="check_scoring_and_fairness_drift", python_callable=check_drift)
    sync >> drift