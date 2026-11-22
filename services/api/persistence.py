from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

try:
    import psycopg
except ImportError:  # pragma: no cover - optional dependency for postgres backend
    psycopg = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_db_path() -> Path:
    env_path = os.getenv("AI_INTERVIEWER_DB_PATH")
    if env_path:
        return Path(env_path)

    return Path(__file__).resolve().parents[2] / "data" / "ai_interviewer.sqlite3"


@dataclass(frozen=True)
class PersistedRun:
    run_id: str
    role: str
    doc_type: str
    status: str
    state_json: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class AuditEvent:
    event_id: int
    run_id: str
    event_type: str
    payload: dict[str, Any]
    created_at: str


@dataclass(frozen=True)
class AuditCheckpoint:
    checkpoint_id: int
    run_id: str
    checkpoint_index: int
    state: dict[str, Any]
    created_at: str


@dataclass(frozen=True)
class ReviewDecision:
    review_id: int
    run_id: str
    reviewer_name: str
    decision: str
    rationale: str
    created_at: str
    updated_at: str
    override_outcome: str | None = None


@dataclass(frozen=True)
class RoleDefinition:
    role_id: str
    title: str
    location: str
    description: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class AnalyticsSnapshotRecord:
    snapshot_id: int
    label: str
    policy_version: str
    prompt_version: str
    payload_json: str
    llm_trace_rollup_json: str | None
    created_at: str


@dataclass(frozen=True)
class AnalyticsEvaluationRecord:
    evaluation_id: int
    evaluation_type: str
    status: str
    baseline_snapshot_id: int | None
    candidate_snapshot_id: int | None
    thresholds_json: str
    result_json: str
    llm_trace_rollup_json: str | None
    created_at: str


class PersistenceRepository(Protocol):
    def ensure_schema(self) -> None:
        ...

    def save_run_start(
        self,
        run_id: str,
        role: str,
        doc_type: str,
        state: dict[str, Any],
        payload: dict[str, Any],
    ) -> None:
        ...

    def save_turn(
        self,
        run_id: str,
        role: str,
        doc_type: str,
        state: dict[str, Any],
        payload: dict[str, Any],
        checkpoint_index: int,
        completed: bool,
    ) -> None:
        ...

    def load_run(self, run_id: str) -> PersistedRun | None:
        ...

    def load_events(self, run_id: str) -> list[AuditEvent]:
        ...

    def load_checkpoints(self, run_id: str) -> list[AuditCheckpoint]:
        ...

    def load_latest_state(self, run_id: str) -> dict[str, Any] | None:
        ...

    def list_runs(self) -> list[PersistedRun]:
        ...

    def save_analytics_snapshot(
        self,
        payload: dict[str, Any],
        label: str = "",
        policy_version: str = "unknown",
        prompt_version: str = "unknown",
        llm_trace_rollup: dict[str, Any] | None = None,
    ) -> AnalyticsSnapshotRecord:
        ...

    def load_analytics_snapshot(self, snapshot_id: int) -> AnalyticsSnapshotRecord | None:
        ...

    def load_latest_analytics_snapshot(self) -> AnalyticsSnapshotRecord | None:
        ...

    def list_analytics_snapshots(self, limit: int = 50) -> list[AnalyticsSnapshotRecord]:
        ...

    def save_analytics_evaluation(
        self,
        evaluation_type: str,
        status: str,
        thresholds: dict[str, Any],
        result: dict[str, Any],
        baseline_snapshot_id: int | None = None,
        candidate_snapshot_id: int | None = None,
        llm_trace_rollup: dict[str, Any] | None = None,
    ) -> AnalyticsEvaluationRecord:
        ...

    def load_analytics_evaluation(self, evaluation_id: int) -> AnalyticsEvaluationRecord | None:
        ...

    def list_analytics_evaluations(self, limit: int = 50) -> list[AnalyticsEvaluationRecord]:
        ...

    def load_audit_bundle(self, run_id: str) -> dict[str, Any] | None:
        ...

    def list_review_queue(self) -> list[PersistedRun]:
        ...

    def load_review_decision(self, run_id: str) -> ReviewDecision | None:
        ...

    def save_review_decision(
        self,
        run_id: str,
        reviewer_name: str,
        decision: str,
        rationale: str,
        override_outcome: str | None = None,
    ) -> ReviewDecision:
        ...

    def materialize_report(self, run_id: str, route: str) -> None:
        ...

    def save_role(
        self,
        role_id: str,
        title: str,
        location: str,
        description: str,
    ) -> RoleDefinition:
        ...

    def load_role(self, role_id: str) -> RoleDefinition | None:
        ...

    def list_roles(self) -> list[RoleDefinition]:
        ...


class RunPersistence:
    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or _default_db_path()
        self.ensure_schema()

    @property
    def db_path(self) -> Path:
        return self._db_path

    def ensure_schema(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    role TEXT NOT NULL,
                    doc_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS audit_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES runs(run_id)
                );

                CREATE TABLE IF NOT EXISTS checkpoints (
                    checkpoint_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    checkpoint_index INTEGER NOT NULL,
                    state_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES runs(run_id)
                );

                CREATE TABLE IF NOT EXISTS turn_records (
                    turn_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    question_index INTEGER NOT NULL,
                    competency TEXT,
                    question TEXT,
                    answer TEXT,
                    evaluation_score REAL,
                    evaluation_evidence_json TEXT NOT NULL,
                    grounded_context_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(run_id, question_index),
                    FOREIGN KEY(run_id) REFERENCES runs(run_id)
                );

                CREATE TABLE IF NOT EXISTS review_decisions (
                    review_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL UNIQUE,
                    reviewer_name TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    override_outcome TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES runs(run_id)
                );

                CREATE TABLE IF NOT EXISTS roles (
                    role_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    location TEXT NOT NULL,
                    description TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS analytics_snapshots (
                    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    label TEXT NOT NULL,
                    policy_version TEXT NOT NULL,
                    prompt_version TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    llm_trace_rollup_json TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS analytics_evaluations (
                    evaluation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    evaluation_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    baseline_snapshot_id INTEGER,
                    candidate_snapshot_id INTEGER,
                    thresholds_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    llm_trace_rollup_json TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(baseline_snapshot_id) REFERENCES analytics_snapshots(snapshot_id),
                    FOREIGN KEY(candidate_snapshot_id) REFERENCES analytics_snapshots(snapshot_id)
                );
                """
            )
            self._ensure_optional_column(
                connection=connection,
                table_name="analytics_snapshots",
                column_name="llm_trace_rollup_json",
                column_type="TEXT",
            )
            self._ensure_optional_column(
                connection=connection,
                table_name="analytics_evaluations",
                column_name="llm_trace_rollup_json",
                column_type="TEXT",
            )
            self._ensure_optional_column(
                connection=connection,
                table_name="review_decisions",
                column_name="override_outcome",
                column_type="TEXT",
            )

    def save_run_start(
        self,
        run_id: str,
        role: str,
        doc_type: str,
        state: dict[str, Any],
        payload: dict[str, Any],
    ) -> None:
        self._upsert_run(run_id, role, doc_type, "in_progress", state)
        self._append_event(run_id, "run_started", payload)
        self._append_checkpoint(run_id, checkpoint_index=0, state=state)

    def save_turn(
        self,
        run_id: str,
        role: str,
        doc_type: str,
        state: dict[str, Any],
        payload: dict[str, Any],
        checkpoint_index: int,
        completed: bool,
    ) -> None:
        status = "in_review" if completed else "in_progress"
        self._upsert_run(run_id, role, doc_type, status, state)
        event_type = str(payload.get("event_type") or ("turn_completed" if not completed else "run_completed"))
        self._append_event(run_id, event_type, payload)
        self._append_checkpoint(run_id, checkpoint_index=checkpoint_index, state=state)
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO turn_records(
                    run_id,question_index,competency,question,answer,evaluation_score,
                    evaluation_evidence_json,grounded_context_json,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(run_id,question_index) DO UPDATE SET
                    competency=excluded.competency,question=excluded.question,answer=excluded.answer,
                    evaluation_score=excluded.evaluation_score,evaluation_evidence_json=excluded.evaluation_evidence_json,
                    grounded_context_json=excluded.grounded_context_json,created_at=excluded.created_at""",
                (
                    run_id, checkpoint_index, payload.get("competency"), payload.get("question"),
                    payload.get("answer"), payload.get("evaluation_score"),
                    json.dumps(payload.get("evaluation_evidence", [])),
                    json.dumps(payload.get("grounded_context", [])), _utc_now(),
                ),
            )

    def load_run(self, run_id: str) -> PersistedRun | None:
        with self._connect() as connection:
            row = connection.execute(
                (
                    "SELECT run_id, role, doc_type, status, state_json, created_at, updated_at "
                    "FROM runs WHERE run_id = ?"
                ),
                (run_id,),
            ).fetchone()

        if row is None:
            return None

        return PersistedRun(
            run_id=row[0],
            role=row[1],
            doc_type=row[2],
            status=row[3],
            state_json=row[4],
            created_at=row[5],
            updated_at=row[6],
        )

    def load_events(self, run_id: str) -> list[AuditEvent]:
        with self._connect() as connection:
            rows = connection.execute(
                (
                    "SELECT event_id, run_id, event_type, payload_json, created_at "
                    "FROM audit_events WHERE run_id = ? ORDER BY event_id ASC"
                ),
                (run_id,),
            ).fetchall()

        return [
            AuditEvent(
                event_id=row[0],
                run_id=row[1],
                event_type=row[2],
                payload=json.loads(row[3]),
                created_at=row[4],
            )
            for row in rows
        ]

    def load_checkpoints(self, run_id: str) -> list[AuditCheckpoint]:
        with self._connect() as connection:
            rows = connection.execute(
                (
                    "SELECT checkpoint_id, run_id, checkpoint_index, state_json, created_at "
                    "FROM checkpoints WHERE run_id = ? ORDER BY checkpoint_id ASC"
                ),
                (run_id,),
            ).fetchall()

        return [
            AuditCheckpoint(
                checkpoint_id=row[0],
                run_id=row[1],
                checkpoint_index=row[2],
                state=json.loads(row[3]),
                created_at=row[4],
            )
            for row in rows
        ]

    def load_latest_state(self, run_id: str) -> dict[str, Any] | None:
        record = self.load_run(run_id)
        if record is None:
            return None

        return json.loads(record.state_json)

    def list_runs(self) -> list[PersistedRun]:
        with self._connect() as connection:
            rows = connection.execute(
                (
                    "SELECT run_id, role, doc_type, status, state_json, created_at, updated_at "
                    "FROM runs ORDER BY created_at ASC"
                )
            ).fetchall()

        return [
            PersistedRun(
                run_id=row[0],
                role=row[1],
                doc_type=row[2],
                status=row[3],
                state_json=row[4],
                created_at=row[5],
                updated_at=row[6],
            )
            for row in rows
        ]

    def save_analytics_snapshot(
        self,
        payload: dict[str, Any],
        label: str = "",
        policy_version: str = "unknown",
        prompt_version: str = "unknown",
        llm_trace_rollup: dict[str, Any] | None = None,
    ) -> AnalyticsSnapshotRecord:
        trace_rollup = llm_trace_rollup
        if trace_rollup is None:
            payload_rollup = payload.get("llm_trace_rollup")
            if isinstance(payload_rollup, dict):
                trace_rollup = payload_rollup

        now = _utc_now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO analytics_snapshots (
                    label,
                    policy_version,
                    prompt_version,
                    payload_json,
                    llm_trace_rollup_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    label.strip(),
                    policy_version.strip() or "unknown",
                    prompt_version.strip() or "unknown",
                    json.dumps(payload),
                    json.dumps(trace_rollup) if trace_rollup is not None else None,
                    now,
                ),
            )

        record = self.load_analytics_snapshot(int(cursor.lastrowid or 0))
        if record is None:
            raise RuntimeError("Analytics snapshot was not saved")

        return record

    def load_analytics_snapshot(self, snapshot_id: int) -> AnalyticsSnapshotRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                (
                    "SELECT snapshot_id, label, policy_version, prompt_version, "
                    "payload_json, llm_trace_rollup_json, created_at FROM analytics_snapshots "
                    "WHERE snapshot_id = ?"
                ),
                (snapshot_id,),
            ).fetchone()

        if row is None:
            return None

        return AnalyticsSnapshotRecord(
            snapshot_id=row[0],
            label=row[1],
            policy_version=row[2],
            prompt_version=row[3],
            payload_json=row[4],
            llm_trace_rollup_json=row[5],
            created_at=row[6],
        )

    def load_latest_analytics_snapshot(self) -> AnalyticsSnapshotRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                (
                    "SELECT snapshot_id, label, policy_version, prompt_version, "
                    "payload_json, llm_trace_rollup_json, created_at FROM analytics_snapshots "
                    "ORDER BY snapshot_id DESC LIMIT 1"
                )
            ).fetchone()

        if row is None:
            return None

        return AnalyticsSnapshotRecord(
            snapshot_id=row[0],
            label=row[1],
            policy_version=row[2],
            prompt_version=row[3],
            payload_json=row[4],
            llm_trace_rollup_json=row[5],
            created_at=row[6],
        )

    def list_analytics_snapshots(self, limit: int = 50) -> list[AnalyticsSnapshotRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                (
                    "SELECT snapshot_id, label, policy_version, prompt_version, "
                    "payload_json, llm_trace_rollup_json, created_at FROM analytics_snapshots "
                    "ORDER BY snapshot_id DESC LIMIT ?"
                ),
                (limit,),
            ).fetchall()

        return [
            AnalyticsSnapshotRecord(
                snapshot_id=row[0],
                label=row[1],
                policy_version=row[2],
                prompt_version=row[3],
                payload_json=row[4],
                llm_trace_rollup_json=row[5],
                created_at=row[6],
            )
            for row in rows
        ]

    def save_analytics_evaluation(
        self,
        evaluation_type: str,
        status: str,
        thresholds: dict[str, Any],
        result: dict[str, Any],
        baseline_snapshot_id: int | None = None,
        candidate_snapshot_id: int | None = None,
        llm_trace_rollup: dict[str, Any] | None = None,
    ) -> AnalyticsEvaluationRecord:
        now = _utc_now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO analytics_evaluations (
                    evaluation_type,
                    status,
                    baseline_snapshot_id,
                    candidate_snapshot_id,
                    thresholds_json,
                    result_json,
                    llm_trace_rollup_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evaluation_type.strip() or "drift_check",
                    status.strip() or "unknown",
                    baseline_snapshot_id,
                    candidate_snapshot_id,
                    json.dumps(thresholds),
                    json.dumps(result),
                    json.dumps(llm_trace_rollup) if llm_trace_rollup is not None else None,
                    now,
                ),
            )

        record = self.load_analytics_evaluation(int(cursor.lastrowid or 0))
        if record is None:
            raise RuntimeError("Analytics evaluation was not saved")

        return record

    def load_analytics_evaluation(self, evaluation_id: int) -> AnalyticsEvaluationRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                (
                    "SELECT evaluation_id, evaluation_type, status, baseline_snapshot_id, "
                    "candidate_snapshot_id, thresholds_json, result_json, "
                    "llm_trace_rollup_json, created_at "
                    "FROM analytics_evaluations WHERE evaluation_id = ?"
                ),
                (evaluation_id,),
            ).fetchone()

        if row is None:
            return None

        return AnalyticsEvaluationRecord(
            evaluation_id=row[0],
            evaluation_type=row[1],
            status=row[2],
            baseline_snapshot_id=row[3],
            candidate_snapshot_id=row[4],
            thresholds_json=row[5],
            result_json=row[6],
            llm_trace_rollup_json=row[7],
            created_at=row[8],
        )

    def list_analytics_evaluations(self, limit: int = 50) -> list[AnalyticsEvaluationRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                (
                    "SELECT evaluation_id, evaluation_type, status, baseline_snapshot_id, "
                    "candidate_snapshot_id, thresholds_json, result_json, "
                    "llm_trace_rollup_json, created_at "
                    "FROM analytics_evaluations ORDER BY evaluation_id DESC LIMIT ?"
                ),
                (limit,),
            ).fetchall()

        return [
            AnalyticsEvaluationRecord(
                evaluation_id=row[0],
                evaluation_type=row[1],
                status=row[2],
                baseline_snapshot_id=row[3],
                candidate_snapshot_id=row[4],
                thresholds_json=row[5],
                result_json=row[6],
                llm_trace_rollup_json=row[7],
                created_at=row[8],
            )
            for row in rows
        ]

    def _ensure_optional_column(
        self,
        connection: sqlite3.Connection,
        table_name: str,
        column_name: str,
        column_type: str,
    ) -> None:
        rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        existing = {str(row[1]) for row in rows}
        if column_name in existing:
            return

        connection.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
        )

    def load_audit_bundle(self, run_id: str) -> dict[str, Any] | None:
        record = self.load_run(run_id)
        if record is None:
            return None

        return {
            "run": record,
            "events": self.load_events(run_id),
            "checkpoints": self.load_checkpoints(run_id),
        }

    def list_review_queue(self) -> list[PersistedRun]:
        with self._connect() as connection:
            rows = connection.execute(
                (
                    "SELECT runs.run_id, runs.role, runs.doc_type, runs.status, "
                    "runs.state_json, runs.created_at, runs.updated_at "
                    "FROM runs LEFT JOIN review_decisions ON runs.run_id = review_decisions.run_id "
                    "WHERE runs.status = 'in_review' AND review_decisions.run_id IS NULL "
                    "ORDER BY runs.updated_at DESC"
                )
            ).fetchall()

        return [
            PersistedRun(
                run_id=row[0],
                role=row[1],
                doc_type=row[2],
                status=row[3],
                state_json=row[4],
                created_at=row[5],
                updated_at=row[6],
            )
            for row in rows
        ]

    def load_review_decision(self, run_id: str) -> ReviewDecision | None:
        with self._connect() as connection:
            row = connection.execute(
                (
                    "SELECT review_id, run_id, reviewer_name, decision, rationale, "
                    "created_at, updated_at, override_outcome FROM review_decisions WHERE run_id = ?"
                ),
                (run_id,),
            ).fetchone()

        if row is None:
            return None

        return ReviewDecision(
            review_id=row[0],
            run_id=row[1],
            reviewer_name=row[2],
            decision=row[3],
            rationale=row[4],
            created_at=row[5],
            updated_at=row[6],
            override_outcome=row[7],
        )

    def save_review_decision(
        self,
        run_id: str,
        reviewer_name: str,
        decision: str,
        rationale: str,
        override_outcome: str | None = None,
    ) -> ReviewDecision:
        record = self.load_run(run_id)
        if record is None:
            raise ValueError(f"Run not found: {run_id}")
        if record.status == "finalized":
            raise RuntimeError(f"Run is already finalized: {run_id}")

        now = _utc_now()
        existing = self.load_review_decision(run_id)
        with self._connect() as connection:
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO review_decisions (
                        run_id,
                        reviewer_name,
                        decision,
                        rationale,
                        override_outcome,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (run_id, reviewer_name, decision, rationale, override_outcome, now, now),
                )
            else:
                connection.execute(
                    """
                    UPDATE review_decisions
                    SET reviewer_name = ?,
                        decision = ?,
                        rationale = ?,
                        override_outcome = ?,
                        updated_at = ?
                    WHERE run_id = ?
                    """,
                    (reviewer_name, decision, rationale, override_outcome, now, run_id),
                )
            connection.execute(
                "UPDATE runs SET status = 'finalized', updated_at = ? WHERE run_id = ?",
                (now, run_id),
            )

        refreshed = self.load_review_decision(run_id)
        if refreshed is None:
            raise RuntimeError("Review decision was not saved")

        return refreshed

    def materialize_report(self, run_id: str, route: str) -> None:
        record = self.load_run(run_id)
        if record is None or record.status != "finalized":
            raise ValueError(f"Run is not finalized: {run_id}")
        state = json.loads(record.state_json)
        decision_log = state.setdefault("decision_log", [])
        if not any(item.get("node") == "report" for item in decision_log):
            decision_log.append({
                "node": "report",
                "route": route,
                "reason": "final report generated after reviewer finalization",
                "alternatives": [],
            })
        with self._connect() as connection:
            connection.execute(
                "UPDATE runs SET state_json=?, updated_at=? WHERE run_id=?",
                (json.dumps(state), _utc_now(), run_id),
            )
        self._append_checkpoint(run_id, checkpoint_index=len(self.load_checkpoints(run_id)), state=state)

    def save_role(
        self,
        role_id: str,
        title: str,
        location: str,
        description: str,
    ) -> RoleDefinition:
        normalized_id = role_id.strip()
        if not normalized_id:
            raise ValueError("role_id cannot be empty")

        clean_title = title.strip()
        clean_location = location.strip()
        clean_description = description.strip()
        if not clean_title or not clean_location or not clean_description:
            raise ValueError("title, location and description are required")

        now = _utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO roles (role_id, title, location, description, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(role_id) DO UPDATE SET
                    title = excluded.title,
                    location = excluded.location,
                    description = excluded.description,
                    updated_at = excluded.updated_at
                """,
                (
                    normalized_id,
                    clean_title,
                    clean_location,
                    clean_description,
                    now,
                    now,
                ),
            )

        saved = self.load_role(normalized_id)
        if saved is None:
            raise RuntimeError("Role definition was not saved")
        return saved

    def load_role(self, role_id: str) -> RoleDefinition | None:
        normalized_id = role_id.strip()
        with self._connect() as connection:
            row = connection.execute(
                (
                    "SELECT role_id, title, location, description, created_at, updated_at "
                    "FROM roles WHERE role_id = ?"
                ),
                (normalized_id,),
            ).fetchone()

        if row is None:
            return None

        return RoleDefinition(
            role_id=row[0],
            title=row[1],
            location=row[2],
            description=row[3],
            created_at=row[4],
            updated_at=row[5],
        )

    def list_roles(self) -> list[RoleDefinition]:
        with self._connect() as connection:
            rows = connection.execute(
                (
                    "SELECT role_id, title, location, description, created_at, updated_at "
                    "FROM roles ORDER BY title ASC"
                )
            ).fetchall()

        return [
            RoleDefinition(
                role_id=row[0],
                title=row[1],
                location=row[2],
                description=row[3],
                created_at=row[4],
                updated_at=row[5],
            )
            for row in rows
        ]

    def _upsert_run(
        self,
        run_id: str,
        role: str,
        doc_type: str,
        status: str,
        state: dict[str, Any],
    ) -> None:
        now = _utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO runs (
                    run_id,
                    role,
                    doc_type,
                    status,
                    state_json,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    role=excluded.role,
                    doc_type=excluded.doc_type,
                    status=excluded.status,
                    state_json=excluded.state_json,
                    updated_at=excluded.updated_at
                """,
                (run_id, role, doc_type, status, json.dumps(state), now, now),
            )

    def _append_event(self, run_id: str, event_type: str, payload: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO audit_events (run_id, event_type, payload_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (run_id, event_type, json.dumps(payload), _utc_now()),
            )

    def _append_checkpoint(self, run_id: str, checkpoint_index: int, state: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO checkpoints (run_id, checkpoint_index, state_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (run_id, checkpoint_index, json.dumps(state), _utc_now()),
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path)
        connection.row_factory = sqlite3.Row
        return connection


class PostgresRunPersistence:
    def __init__(self, dsn: str) -> None:
        if psycopg is None:
            raise RuntimeError(
                "Postgres backend requires psycopg. Install with: "
                "py -3 -m pip install psycopg[binary]"
            )
        self._dsn = dsn
        self.ensure_schema()

    @property
    def dsn(self) -> str:
        return self._dsn

    def ensure_schema(self) -> None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS runs (
                        run_id TEXT PRIMARY KEY,
                        role TEXT NOT NULL,
                        doc_type TEXT NOT NULL,
                        status TEXT NOT NULL,
                        state_json TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS audit_events (
                        event_id BIGSERIAL PRIMARY KEY,
                        run_id TEXT NOT NULL REFERENCES runs(run_id),
                        event_type TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS checkpoints (
                        checkpoint_id BIGSERIAL PRIMARY KEY,
                        run_id TEXT NOT NULL REFERENCES runs(run_id),
                        checkpoint_index INTEGER NOT NULL,
                        state_json TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """CREATE TABLE IF NOT EXISTS turn_records (
                        turn_id BIGSERIAL PRIMARY KEY,
                        run_id TEXT NOT NULL,
                        question_index INTEGER NOT NULL,
                        competency TEXT,
                        question TEXT,
                        answer TEXT,
                        evaluation_score DOUBLE PRECISION,
                        evaluation_evidence_json TEXT NOT NULL,
                        grounded_context_json TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        UNIQUE(run_id, question_index),
                        FOREIGN KEY(run_id) REFERENCES runs(run_id)
                    )"""
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS review_decisions (
                        review_id BIGSERIAL PRIMARY KEY,
                        run_id TEXT NOT NULL UNIQUE REFERENCES runs(run_id),
                        reviewer_name TEXT NOT NULL,
                        decision TEXT NOT NULL,
                        rationale TEXT NOT NULL,
                        override_outcome TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS roles (
                        role_id TEXT PRIMARY KEY,
                        title TEXT NOT NULL,
                        location TEXT NOT NULL,
                        description TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS analytics_snapshots (
                        snapshot_id BIGSERIAL PRIMARY KEY,
                        label TEXT NOT NULL,
                        policy_version TEXT NOT NULL,
                        prompt_version TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        llm_trace_rollup_json TEXT,
                        created_at TEXT NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS analytics_evaluations (
                        evaluation_id BIGSERIAL PRIMARY KEY,
                        evaluation_type TEXT NOT NULL,
                        status TEXT NOT NULL,
                        baseline_snapshot_id BIGINT REFERENCES analytics_snapshots(snapshot_id),
                        candidate_snapshot_id BIGINT REFERENCES analytics_snapshots(snapshot_id),
                        thresholds_json TEXT NOT NULL,
                        result_json TEXT NOT NULL,
                        llm_trace_rollup_json TEXT,
                        created_at TEXT NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE analytics_snapshots
                    ADD COLUMN IF NOT EXISTS llm_trace_rollup_json TEXT
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE analytics_evaluations
                    ADD COLUMN IF NOT EXISTS llm_trace_rollup_json TEXT
                    """
                )
                cursor.execute(
                    "ALTER TABLE review_decisions ADD COLUMN IF NOT EXISTS override_outcome TEXT"
                )
            connection.commit()

    def save_run_start(
        self,
        run_id: str,
        role: str,
        doc_type: str,
        state: dict[str, Any],
        payload: dict[str, Any],
    ) -> None:
        self._upsert_run(run_id, role, doc_type, "in_progress", state)
        self._append_event(run_id, "run_started", payload)
        self._append_checkpoint(run_id, checkpoint_index=0, state=state)

    def save_turn(
        self,
        run_id: str,
        role: str,
        doc_type: str,
        state: dict[str, Any],
        payload: dict[str, Any],
        checkpoint_index: int,
        completed: bool,
    ) -> None:
        status = "in_review" if completed else "in_progress"
        self._upsert_run(run_id, role, doc_type, status, state)
        event_type = str(payload.get("event_type") or ("turn_completed" if not completed else "run_completed"))
        self._append_event(run_id, event_type, payload)
        self._append_checkpoint(run_id, checkpoint_index=checkpoint_index, state=state)
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO turn_records(
                        run_id,question_index,competency,question,answer,evaluation_score,
                        evaluation_evidence_json,grounded_context_json,created_at
                    ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(run_id,question_index) DO UPDATE SET
                        competency=EXCLUDED.competency,question=EXCLUDED.question,answer=EXCLUDED.answer,
                        evaluation_score=EXCLUDED.evaluation_score,evaluation_evidence_json=EXCLUDED.evaluation_evidence_json,
                        grounded_context_json=EXCLUDED.grounded_context_json,created_at=EXCLUDED.created_at""",
                    (
                        run_id, checkpoint_index, payload.get("competency"), payload.get("question"),
                        payload.get("answer"), payload.get("evaluation_score"),
                        json.dumps(payload.get("evaluation_evidence", [])),
                        json.dumps(payload.get("grounded_context", [])), _utc_now(),
                    ),
                )
            connection.commit()

    def load_run(self, run_id: str) -> PersistedRun | None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    (
                        "SELECT run_id, role, doc_type, status, state_json, created_at, updated_at "
                        "FROM runs WHERE run_id = %s"
                    ),
                    (run_id,),
                )
                row = cursor.fetchone()

        if row is None:
            return None

        return PersistedRun(
            run_id=row[0],
            role=row[1],
            doc_type=row[2],
            status=row[3],
            state_json=row[4],
            created_at=row[5],
            updated_at=row[6],
        )

    def load_events(self, run_id: str) -> list[AuditEvent]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    (
                        "SELECT event_id, run_id, event_type, payload_json, created_at "
                        "FROM audit_events WHERE run_id = %s ORDER BY event_id ASC"
                    ),
                    (run_id,),
                )
                rows = cursor.fetchall()

        return [
            AuditEvent(
                event_id=row[0],
                run_id=row[1],
                event_type=row[2],
                payload=json.loads(row[3]),
                created_at=row[4],
            )
            for row in rows
        ]

    def load_checkpoints(self, run_id: str) -> list[AuditCheckpoint]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    (
                        "SELECT checkpoint_id, run_id, checkpoint_index, state_json, created_at "
                        "FROM checkpoints WHERE run_id = %s ORDER BY checkpoint_id ASC"
                    ),
                    (run_id,),
                )
                rows = cursor.fetchall()

        return [
            AuditCheckpoint(
                checkpoint_id=row[0],
                run_id=row[1],
                checkpoint_index=row[2],
                state=json.loads(row[3]),
                created_at=row[4],
            )
            for row in rows
        ]

    def load_latest_state(self, run_id: str) -> dict[str, Any] | None:
        record = self.load_run(run_id)
        if record is None:
            return None

        return json.loads(record.state_json)

    def list_runs(self) -> list[PersistedRun]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    (
                        "SELECT run_id, role, doc_type, status, state_json, created_at, updated_at "
                        "FROM runs ORDER BY created_at ASC"
                    )
                )
                rows = cursor.fetchall()

        return [
            PersistedRun(
                run_id=row[0],
                role=row[1],
                doc_type=row[2],
                status=row[3],
                state_json=row[4],
                created_at=row[5],
                updated_at=row[6],
            )
            for row in rows
        ]

    def save_analytics_snapshot(
        self,
        payload: dict[str, Any],
        label: str = "",
        policy_version: str = "unknown",
        prompt_version: str = "unknown",
        llm_trace_rollup: dict[str, Any] | None = None,
    ) -> AnalyticsSnapshotRecord:
        trace_rollup = llm_trace_rollup
        if trace_rollup is None:
            payload_rollup = payload.get("llm_trace_rollup")
            if isinstance(payload_rollup, dict):
                trace_rollup = payload_rollup

        now = _utc_now()
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO analytics_snapshots (
                        label,
                        policy_version,
                        prompt_version,
                        payload_json,
                        llm_trace_rollup_json,
                        created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING snapshot_id
                    """,
                    (
                        label.strip(),
                        policy_version.strip() or "unknown",
                        prompt_version.strip() or "unknown",
                        json.dumps(payload),
                        json.dumps(trace_rollup) if trace_rollup is not None else None,
                        now,
                    ),
                )
                row = cursor.fetchone()
            connection.commit()

        record = self.load_analytics_snapshot(int(row[0])) if row else None
        if record is None:
            raise RuntimeError("Analytics snapshot was not saved")

        return record

    def load_analytics_snapshot(self, snapshot_id: int) -> AnalyticsSnapshotRecord | None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    (
                        "SELECT snapshot_id, label, policy_version, prompt_version, "
                        "payload_json, llm_trace_rollup_json, created_at "
                        "FROM analytics_snapshots "
                        "WHERE snapshot_id = %s"
                    ),
                    (snapshot_id,),
                )
                row = cursor.fetchone()

        if row is None:
            return None

        return AnalyticsSnapshotRecord(
            snapshot_id=row[0],
            label=row[1],
            policy_version=row[2],
            prompt_version=row[3],
            payload_json=row[4],
            llm_trace_rollup_json=row[5],
            created_at=row[6],
        )

    def load_latest_analytics_snapshot(self) -> AnalyticsSnapshotRecord | None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    (
                        "SELECT snapshot_id, label, policy_version, prompt_version, "
                        "payload_json, llm_trace_rollup_json, created_at "
                        "FROM analytics_snapshots "
                        "ORDER BY snapshot_id DESC LIMIT 1"
                    )
                )
                row = cursor.fetchone()

        if row is None:
            return None

        return AnalyticsSnapshotRecord(
            snapshot_id=row[0],
            label=row[1],
            policy_version=row[2],
            prompt_version=row[3],
            payload_json=row[4],
            llm_trace_rollup_json=row[5],
            created_at=row[6],
        )

    def list_analytics_snapshots(self, limit: int = 50) -> list[AnalyticsSnapshotRecord]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    (
                        "SELECT snapshot_id, label, policy_version, prompt_version, "
                        "payload_json, llm_trace_rollup_json, created_at "
                        "FROM analytics_snapshots "
                        "ORDER BY snapshot_id DESC LIMIT %s"
                    ),
                    (limit,),
                )
                rows = cursor.fetchall()

        return [
            AnalyticsSnapshotRecord(
                snapshot_id=row[0],
                label=row[1],
                policy_version=row[2],
                prompt_version=row[3],
                payload_json=row[4],
                llm_trace_rollup_json=row[5],
                created_at=row[6],
            )
            for row in rows
        ]

    def save_analytics_evaluation(
        self,
        evaluation_type: str,
        status: str,
        thresholds: dict[str, Any],
        result: dict[str, Any],
        baseline_snapshot_id: int | None = None,
        candidate_snapshot_id: int | None = None,
        llm_trace_rollup: dict[str, Any] | None = None,
    ) -> AnalyticsEvaluationRecord:
        now = _utc_now()
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO analytics_evaluations (
                        evaluation_type,
                        status,
                        baseline_snapshot_id,
                        candidate_snapshot_id,
                        thresholds_json,
                        result_json,
                        llm_trace_rollup_json,
                        created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING evaluation_id
                    """,
                    (
                        evaluation_type.strip() or "drift_check",
                        status.strip() or "unknown",
                        baseline_snapshot_id,
                        candidate_snapshot_id,
                        json.dumps(thresholds),
                        json.dumps(result),
                        json.dumps(llm_trace_rollup) if llm_trace_rollup is not None else None,
                        now,
                    ),
                )
                row = cursor.fetchone()
            connection.commit()

        record = self.load_analytics_evaluation(int(row[0])) if row else None
        if record is None:
            raise RuntimeError("Analytics evaluation was not saved")

        return record

    def load_analytics_evaluation(self, evaluation_id: int) -> AnalyticsEvaluationRecord | None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    (
                        "SELECT evaluation_id, evaluation_type, status, baseline_snapshot_id, "
                        "candidate_snapshot_id, thresholds_json, result_json, "
                        "llm_trace_rollup_json, created_at "
                        "FROM analytics_evaluations WHERE evaluation_id = %s"
                    ),
                    (evaluation_id,),
                )
                row = cursor.fetchone()

        if row is None:
            return None

        return AnalyticsEvaluationRecord(
            evaluation_id=row[0],
            evaluation_type=row[1],
            status=row[2],
            baseline_snapshot_id=row[3],
            candidate_snapshot_id=row[4],
            thresholds_json=row[5],
            result_json=row[6],
            llm_trace_rollup_json=row[7],
            created_at=row[8],
        )

    def list_analytics_evaluations(self, limit: int = 50) -> list[AnalyticsEvaluationRecord]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    (
                        "SELECT evaluation_id, evaluation_type, status, baseline_snapshot_id, "
                        "candidate_snapshot_id, thresholds_json, result_json, "
                        "llm_trace_rollup_json, created_at "
                        "FROM analytics_evaluations ORDER BY evaluation_id DESC LIMIT %s"
                    ),
                    (limit,),
                )
                rows = cursor.fetchall()

        return [
            AnalyticsEvaluationRecord(
                evaluation_id=row[0],
                evaluation_type=row[1],
                status=row[2],
                baseline_snapshot_id=row[3],
                candidate_snapshot_id=row[4],
                thresholds_json=row[5],
                result_json=row[6],
                llm_trace_rollup_json=row[7],
                created_at=row[8],
            )
            for row in rows
        ]

    def load_audit_bundle(self, run_id: str) -> dict[str, Any] | None:
        record = self.load_run(run_id)
        if record is None:
            return None

        return {
            "run": record,
            "events": self.load_events(run_id),
            "checkpoints": self.load_checkpoints(run_id),
        }

    def list_review_queue(self) -> list[PersistedRun]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    (
                        "SELECT runs.run_id, runs.role, runs.doc_type, runs.status, "
                        "runs.state_json, runs.created_at, runs.updated_at "
                        "FROM runs LEFT JOIN review_decisions "
                        "ON runs.run_id = review_decisions.run_id "
                        "WHERE runs.status = 'in_review' AND review_decisions.run_id IS NULL "
                        "ORDER BY runs.updated_at DESC"
                    )
                )
                rows = cursor.fetchall()

        return [
            PersistedRun(
                run_id=row[0],
                role=row[1],
                doc_type=row[2],
                status=row[3],
                state_json=row[4],
                created_at=row[5],
                updated_at=row[6],
            )
            for row in rows
        ]

    def load_review_decision(self, run_id: str) -> ReviewDecision | None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    (
                        "SELECT review_id, run_id, reviewer_name, decision, rationale, "
                        "created_at, updated_at, override_outcome FROM review_decisions WHERE run_id = %s"
                    ),
                    (run_id,),
                )
                row = cursor.fetchone()

        if row is None:
            return None

        return ReviewDecision(
            review_id=row[0],
            run_id=row[1],
            reviewer_name=row[2],
            decision=row[3],
            rationale=row[4],
            created_at=row[5],
            updated_at=row[6],
            override_outcome=row[7],
        )

    def save_review_decision(
        self,
        run_id: str,
        reviewer_name: str,
        decision: str,
        rationale: str,
        override_outcome: str | None = None,
    ) -> ReviewDecision:
        record = self.load_run(run_id)
        if record is None:
            raise ValueError(f"Run not found: {run_id}")

        now = _utc_now()
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO review_decisions (
                        run_id,
                        reviewer_name,
                        decision,
                        rationale,
                        override_outcome,
                        created_at,
                        updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(run_id) DO UPDATE SET
                        reviewer_name = EXCLUDED.reviewer_name,
                        decision = EXCLUDED.decision,
                        rationale = EXCLUDED.rationale,
                        override_outcome = EXCLUDED.override_outcome,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (run_id, reviewer_name, decision, rationale, override_outcome, now, now),
                )
                cursor.execute(
                    "UPDATE runs SET status = 'finalized', updated_at = %s WHERE run_id = %s",
                    (now, run_id),
                )
            connection.commit()

        refreshed = self.load_review_decision(run_id)
        if refreshed is None:
            raise RuntimeError("Review decision was not saved")

        return refreshed

    def materialize_report(self, run_id: str, route: str) -> None:
        record = self.load_run(run_id)
        if record is None or record.status != "finalized":
            raise ValueError(f"Run is not finalized: {run_id}")
        state = json.loads(record.state_json)
        decision_log = state.setdefault("decision_log", [])
        if not any(item.get("node") == "report" for item in decision_log):
            decision_log.append({
                "node": "report", "route": route,
                "reason": "final report generated after reviewer finalization",
                "alternatives": [],
            })
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE runs SET state_json=%s, updated_at=%s WHERE run_id=%s",
                    (json.dumps(state), _utc_now(), run_id),
                )
            connection.commit()
        self._append_checkpoint(run_id, checkpoint_index=len(self.load_checkpoints(run_id)), state=state)

    def save_role(
        self,
        role_id: str,
        title: str,
        location: str,
        description: str,
    ) -> RoleDefinition:
        now = _utc_now()
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO roles(role_id,title,location,description,created_at,updated_at)
                    VALUES(%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(role_id) DO UPDATE SET
                        title=EXCLUDED.title,
                        location=EXCLUDED.location,
                        description=EXCLUDED.description,
                        updated_at=EXCLUDED.updated_at
                    """,
                    (role_id, title, location, description, now, now),
                )
            connection.commit()
        role = self.load_role(role_id)
        if role is None:
            raise RuntimeError("Role was not saved")
        return role

    def load_role(self, role_id: str) -> RoleDefinition | None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT role_id,title,location,description,created_at,updated_at "
                    "FROM roles WHERE role_id=%s",
                    (role_id,),
                )
                row = cursor.fetchone()
        if row is None:
            return None
        return RoleDefinition(*row)

    def list_roles(self) -> list[RoleDefinition]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT role_id,title,location,description,created_at,updated_at "
                    "FROM roles ORDER BY title"
                )
                rows = cursor.fetchall()
        return [RoleDefinition(*row) for row in rows]

    def _upsert_run(
        self,
        run_id: str,
        role: str,
        doc_type: str,
        status: str,
        state: dict[str, Any],
    ) -> None:
        now = _utc_now()
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO runs (
                        run_id,
                        role,
                        doc_type,
                        status,
                        state_json,
                        created_at,
                        updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(run_id) DO UPDATE SET
                        role = EXCLUDED.role,
                        doc_type = EXCLUDED.doc_type,
                        status = EXCLUDED.status,
                        state_json = EXCLUDED.state_json,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (run_id, role, doc_type, status, json.dumps(state), now, now),
                )
            connection.commit()

    def _append_event(self, run_id: str, event_type: str, payload: dict[str, Any]) -> None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO audit_events (run_id, event_type, payload_json, created_at)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (run_id, event_type, json.dumps(payload), _utc_now()),
                )
            connection.commit()

    def _append_checkpoint(self, run_id: str, checkpoint_index: int, state: dict[str, Any]) -> None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO checkpoints (run_id, checkpoint_index, state_json, created_at)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (run_id, checkpoint_index, json.dumps(state), _utc_now()),
                )
            connection.commit()

    def _connect(self):
        assert psycopg is not None
        return psycopg.connect(self._dsn)


def _build_persistence() -> PersistenceRepository:
    backend = os.getenv("AI_INTERVIEWER_DB_BACKEND", "sqlite").strip().lower()
    if backend == "postgres":
        dsn = os.getenv("AI_INTERVIEWER_POSTGRES_DSN", "").strip()
        if not dsn:
            raise RuntimeError(
                "AI_INTERVIEWER_POSTGRES_DSN is required when AI_INTERVIEWER_DB_BACKEND=postgres"
            )
        return PostgresRunPersistence(dsn=dsn)

    return RunPersistence()


PERSISTENCE: PersistenceRepository = _build_persistence()
