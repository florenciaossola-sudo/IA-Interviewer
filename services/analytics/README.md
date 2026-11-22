# Analytics Plane

Phase 7 analytics helpers for medallion-style snapshots and comparisons.

Current slice:
- bronze extraction from the configured operational persistence backend (SQLite locally or Postgres)
- silver normalization of turns, scores, routes, and review decisions
- gold snapshot metrics for trends, drift, fairness, and override patterns
- snapshot comparison for before/after analysis
- scheduler jobs:
	- snapshot sync job to persist periodic gold snapshots
	- drift-check job to compare baseline/candidate snapshots with threshold-based alerts

Optional lakehouse profile:
- Set `AI_INTERVIEWER_LAKEHOUSE_ENABLED=1` and install `services/api[lakehouse]` to
	materialize Bronze, Silver, and Gold tables in DuckDB and export snapshot-partitioned Parquet.
- Set `AI_INTERVIEWER_MINIO_ENDPOINT`, `AI_INTERVIEWER_MINIO_ACCESS_KEY`, and
	`AI_INTERVIEWER_MINIO_SECRET_KEY` to upload Parquet artifacts to MinIO.
- The `infra` Airflow profile runs corpus-ingestion retries and nightly analytics sync/drift DAGs.