# Infra

## Local Postgres and Object Store

The default developer setup remains SQLite and in-memory retrieval. To exercise the
Postgres/pgvector and MinIO path without changing existing local data:

```powershell
docker compose -f infra/docker-compose.yml up -d postgres minio
$env:AI_INTERVIEWER_DB_BACKEND = "postgres"
$env:AI_INTERVIEWER_POSTGRES_DSN = "postgresql://aiuser:local-dev-only@127.0.0.1:5432/ai_interviewer"
$env:AI_INTERVIEWER_LANGGRAPH_POSTGRES_DSN = "postgresql://aiuser:local-dev-only@127.0.0.1:5432/ai_interviewer_langgraph"
$env:AI_INTERVIEWER_RETRIEVAL_BACKEND = "pgvector"
$env:AI_INTERVIEWER_RETRIEVAL_BOOTSTRAP_FIXTURE = "1"
$env:AI_INTERVIEWER_LAKEHOUSE_ENABLED = "1"
$env:AI_INTERVIEWER_DUCKDB_PATH = "data/lakehouse/warehouse.duckdb"
$env:AI_INTERVIEWER_LAKEHOUSE_DIR = "data/lakehouse/parquet"
$env:AI_INTERVIEWER_MINIO_ENDPOINT = "127.0.0.1:9000"
$env:AI_INTERVIEWER_MINIO_ACCESS_KEY = "minioadmin"
$env:AI_INTERVIEWER_MINIO_SECRET_KEY = "local-minio-only"
py -3 -m pip install -e "services/api[postgres,lakehouse]" -e "services/agent[postgres]"
py -3 -m uvicorn services.api.main:app --host 127.0.0.1 --port 8081 --reload
```

The credentials above are local-development defaults only. Replace them before using a
shared or deployed environment. Postgres stores runs, scheduled interviews, role settings,
follow-ups, and audit records. LangGraph checkpoints use the separate
`ai_interviewer_langgraph` database because LangGraph owns fixed table names that overlap
the operational schema. Source documents remain under `data/`.

## Airflow Profile

With the API running on the host, start the optional scheduler profile:

```powershell
docker compose -f infra/docker-compose.yml --profile airflow up --build
```

The `corpus_ingestion` DAG retries documents left in `failed` or `ingesting` state. The
nightly analytics DAG writes Gold snapshots to Postgres, materializes Bronze/Silver/Gold
tables and Parquet artifacts in DuckDB, and uploads artifacts to MinIO when configured.
Airflow uses its own `airflow` database on the same local Postgres server.
