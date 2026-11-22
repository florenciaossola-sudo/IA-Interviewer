from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from urllib.request import Request, urlopen

from airflow import DAG
from airflow.operators.python import PythonOperator


def retry_pending_ingestions() -> dict[str, int]:
    api_url = os.getenv("AI_INTERVIEWER_API_URL", "http://host.docker.internal:8081").rstrip("/")
    with urlopen(f"{api_url}/admin/corpus/documents", timeout=30) as response:
        documents = json.loads(response.read().decode("utf-8"))

    attempted = 0
    failed = 0
    for document in documents:
        if document.get("status") not in {"failed", "ingesting"}:
            continue
        request = Request(
            f"{api_url}/admin/corpus/documents/{document['doc_id']}/ingest",
            data=b"",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        attempted += 1
        try:
            with urlopen(request, timeout=120) as response:
                result = json.loads(response.read().decode("utf-8"))
            failed += result.get("status") != "ingested"
        except Exception:
            failed += 1
            raise
    return {"attempted": attempted, "failed": failed}


with DAG(
    dag_id="corpus_ingestion",
    description="Retry failed or interrupted corpus ingestion through the API",
    start_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
    schedule="*/30 * * * *",
    catchup=False,
    max_active_runs=1,
    tags=["ai-interviewer", "corpus"],
) as dag:
    PythonOperator(
        task_id="retry_pending_ingestions",
        python_callable=retry_pending_ingestions,
        retries=2,
    )