from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List

try:
    import psycopg
except ImportError:  # pragma: no cover - optional PostgreSQL backend
    psycopg = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class InterviewRecord:
    interview_id: str
    candidate_name: str
    candidate_email: str
    role_id: str
    job_offer: str
    scheduled_at: str
    expires_at: str
    status: str
    reviewer: str
    link_token_hash: str
    created_at: str
    updated_at: str
    invitation_status: str
    invitation_sent_at: str | None
    invitation_error: str | None
    invitation_attempts: int
    invitation_token_encrypted: str | None
    active_run_id: str | None = None


class _PostgresConnection:
    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def __enter__(self) -> _PostgresConnection:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        try:
            return bool(self._connection.__exit__(exc_type, exc_value, traceback))
        finally:
            self._connection.close()

    def execute(self, statement: str, parameters: object = ()):
        statement = statement.replace(
            "INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY"
        ).replace("BEGIN IMMEDIATE", "BEGIN")
        statement = re.sub(r"\?", "%s", statement)
        if parameters:
            return self._connection.execute(statement, parameters)
        return self._connection.execute(statement)


class InterviewRepository:
    def __init__(self, path: Path, *, postgres_dsn: str | None = None) -> None:
        self._path = path
        self._postgres_dsn = postgres_dsn
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if postgres_dsn and psycopg is None:
            raise RuntimeError(
                "PostgreSQL interview storage requires psycopg. "
                "Install services/api with the postgres extra."
            )
        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS scheduled_interviews (
                    interview_id TEXT PRIMARY KEY,
                    candidate_name TEXT NOT NULL,
                    candidate_email TEXT NOT NULL,
                    role_id TEXT NOT NULL,
                    job_offer TEXT NOT NULL,
                    scheduled_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reviewer TEXT NOT NULL DEFAULT '',
                    link_token_hash TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    invitation_status TEXT NOT NULL DEFAULT 'not_sent',
                    invitation_sent_at TEXT,
                    invitation_error TEXT,
                    invitation_attempts INTEGER NOT NULL DEFAULT 0,
                    invitation_token_encrypted TEXT,
                    active_run_id TEXT
                )
                """
            )
            migrations = {
                "invitation_status": "TEXT NOT NULL DEFAULT 'not_sent'",
                "invitation_sent_at": "TEXT",
                "invitation_error": "TEXT",
                "invitation_attempts": "INTEGER NOT NULL DEFAULT 0",
                "invitation_token_encrypted": "TEXT",
                "active_run_id": "TEXT",
            }
            if self._postgres_dsn:
                for column, definition in migrations.items():
                    db.execute(
                        "ALTER TABLE scheduled_interviews "
                        f"ADD COLUMN IF NOT EXISTS {column} {definition}"
                    )
            else:
                columns = {
                    row[1] for row in db.execute("PRAGMA table_info(scheduled_interviews)")
                }
                for column, definition in migrations.items():
                    if column not in columns:
                        db.execute(
                            f"ALTER TABLE scheduled_interviews ADD COLUMN {column} {definition}"
                        )
            db.execute(
                """CREATE TABLE IF NOT EXISTS admin_audit_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    actor TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    target TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )"""
            )
            db.execute(
                """CREATE TABLE IF NOT EXISTS analytics_sync_runs (
                    sync_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    status TEXT NOT NULL,
                    snapshot_id INTEGER,
                    diagnostics TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT NOT NULL
                )"""
            )
            db.execute(
                """CREATE TABLE IF NOT EXISTS role_configurations (
                    role_id TEXT PRIMARY KEY,
                    config_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )"""
            )
            db.execute(
                """CREATE TABLE IF NOT EXISTS integrity_dispositions (
                    run_id TEXT PRIMARY KEY,
                    reviewer TEXT NOT NULL,
                    disposition TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )"""
            )
            db.execute(
                """CREATE TABLE IF NOT EXISTS follow_up_requests (
                    run_id TEXT PRIMARY KEY,
                    reviewer TEXT NOT NULL,
                    requested_action TEXT NOT NULL,
                    status TEXT NOT NULL,
                    note TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )"""
            )
            db.execute(
                """CREATE TABLE IF NOT EXISTS admin_settings (
                    setting_key TEXT PRIMARY KEY,
                    setting_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )"""
            )

    def save_role_configuration(self, role_id: str, config: dict) -> dict:
        with self._connect() as db:
            db.execute(
                "INSERT INTO role_configurations(role_id,config_json,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(role_id) DO UPDATE SET config_json=excluded.config_json,updated_at=excluded.updated_at",
                (role_id, json.dumps(config), _now()),
            )
        return self.get_role_configuration(role_id)

    def get_role_configuration(self, role_id: str) -> dict:
        with self._connect() as db:
            row = db.execute(
                "SELECT config_json,updated_at FROM role_configurations WHERE role_id=?", (role_id,)
            ).fetchone()
        if row is None:
            return {
                "role_id": role_id,
                "decision_threshold": 0.75,
                "recommendation_low_max": 0.40,
                "recommendation_high_min": 0.70,
                "conclusion_threshold": 0.55,
                "confidence_threshold": 0.70,
                "max_turns": 3,
                "interviewer_persona": "",
                "question_prompt": "",
                "updated_at": None,
            }
        config = json.loads(row[0])
        config.setdefault("max_turns", 3)
        return {"role_id": role_id, **config, "updated_at": row[1]}

    def save_setting(self, key: str, value: dict) -> dict:
        with self._connect() as db:
            db.execute(
                "INSERT INTO admin_settings(setting_key,setting_json,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(setting_key) DO UPDATE SET setting_json=excluded.setting_json,updated_at=excluded.updated_at",
                (key, json.dumps(value), _now()),
            )
        setting = self.get_setting(key)
        assert setting is not None
        return setting

    def get_setting(self, key: str) -> dict | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT setting_json,updated_at FROM admin_settings WHERE setting_key=?", (key,)
            ).fetchone()
        if row is None:
            return None
        return {**json.loads(row[0]), "updated_at": row[1]}

    def save_integrity_disposition(
        self, run_id: str, reviewer: str, disposition: str, rationale: str
    ) -> dict:
        value = {
            "run_id": run_id,
            "reviewer": reviewer.strip() or "reviewer",
            "disposition": disposition,
            "rationale": rationale.strip(),
            "created_at": _now(),
        }
        with self._connect() as db:
            db.execute(
                "INSERT INTO integrity_dispositions(run_id,reviewer,disposition,rationale,created_at) "
                "VALUES(?,?,?,?,?) ON CONFLICT(run_id) DO UPDATE SET reviewer=excluded.reviewer, "
                "disposition=excluded.disposition,rationale=excluded.rationale,created_at=excluded.created_at",
                (run_id, value["reviewer"], disposition, rationale.strip(), value["created_at"]),
            )
        return value

    def get_integrity_disposition(self, run_id: str) -> dict | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT run_id,reviewer,disposition,rationale,created_at FROM integrity_dispositions WHERE run_id=?",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return {"run_id": row[0], "reviewer": row[1], "disposition": row[2], "rationale": row[3], "created_at": row[4]}

    def list_integrity_dispositions(self) -> list[dict]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT run_id,reviewer,disposition,created_at "
                "FROM integrity_dispositions ORDER BY run_id"
            ).fetchall()
        return [
            {
                "run_id": row[0],
                "reviewer": row[1],
                "disposition": row[2],
                "created_at": row[3],
            }
            for row in rows
        ]

    def save_follow_up(self, run_id: str, reviewer: str, requested_action: str) -> dict:
        now = _now()
        with self._connect() as db:
            db.execute(
                "INSERT INTO follow_up_requests(run_id,reviewer,requested_action,status,note,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?) ON CONFLICT(run_id) DO UPDATE SET reviewer=excluded.reviewer, "
                "requested_action=excluded.requested_action,status='requested',note='',updated_at=excluded.updated_at",
                (run_id, reviewer.strip() or "reviewer", requested_action.strip(), "requested", "", now, now),
            )
        return self.get_follow_up(run_id) or {}

    def get_follow_up(self, run_id: str) -> dict | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT run_id,reviewer,requested_action,status,note,created_at,updated_at "
                "FROM follow_up_requests WHERE run_id=?", (run_id,)
            ).fetchone()
        if row is None:
            return None
        return {
            "run_id": row[0], "reviewer": row[1], "requested_action": row[2],
            "status": row[3], "note": row[4], "created_at": row[5], "updated_at": row[6],
        }

    def update_follow_up(self, run_id: str, reviewer: str, status: str, note: str) -> dict:
        with self._connect() as db:
            cursor = db.execute(
                "UPDATE follow_up_requests SET status=?,note=?,updated_at=? WHERE run_id=?",
                (status, note.strip(), _now(), run_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(run_id)
        return self.get_follow_up(run_id) or {}

    def record_audit(self, event_type: str, target: str, details: dict | None = None,
                     actor: str = "local-admin") -> None:
        with self._connect() as db:
            db.execute(
                "INSERT INTO admin_audit_events(actor,event_type,target,details_json,created_at) VALUES(?,?,?,?,?)",
                (actor, event_type, target, json.dumps(details or {}), _now()),
            )

    def list_audit(self, *, search: str = "", event_type: str = "", limit: int = 50,
                   offset: int = 0) -> tuple[list[dict], int]:
        filters = []
        params: list[object] = []
        if search.strip():
            term = f"%{search.strip()}%"
            filters.append("(actor LIKE ? OR event_type LIKE ? OR target LIKE ? OR details_json LIKE ?)")
            params.extend([term, term, term, term])
        if event_type.strip():
            filters.append("event_type = ?")
            params.append(event_type.strip())
        clause = f"WHERE {' AND '.join(filters)}" if filters else ""
        with self._connect() as db:
            total = db.execute(f"SELECT COUNT(*) FROM admin_audit_events {clause}", params).fetchone()[0]
            rows = db.execute(
                f"SELECT event_id,actor,event_type,target,details_json,created_at FROM admin_audit_events {clause} ORDER BY event_id DESC LIMIT ? OFFSET ?",
                [*params, max(1, min(limit, 200)), max(0, offset)],
            ).fetchall()
        return [
            {"event_id": row[0], "actor": row[1], "event_type": row[2], "target": row[3],
             "details": json.loads(row[4]), "created_at": row[5]}
            for row in rows
        ], int(total)

    def record_sync_run(self, status: str, snapshot_id: int | None, diagnostics: str,
                        started_at: str, completed_at: str) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT INTO analytics_sync_runs(status,snapshot_id,diagnostics,started_at,completed_at) VALUES(?,?,?,?,?)",
                (status, snapshot_id, diagnostics, started_at, completed_at),
            )

    def list_sync_runs(self, limit: int = 50) -> list[dict]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT sync_id,status,snapshot_id,diagnostics,started_at,completed_at FROM analytics_sync_runs ORDER BY sync_id DESC LIMIT ?",
                (max(1, min(limit, 200)),),
            ).fetchall()
        return [
            {"sync_id": row[0], "status": row[1], "snapshot_id": row[2],
             "diagnostics": row[3], "started_at": row[4], "completed_at": row[5]}
            for row in rows
        ]

    def activate_due(self) -> list[tuple[str, str]]:
        now = datetime.now(timezone.utc)
        now_text = now.isoformat()
        with self._connect() as db:
            due_rows = db.execute(
                "SELECT interview_id,scheduled_at,expires_at FROM scheduled_interviews WHERE status='scheduled'"
            ).fetchall()
            changed = []
            for interview_id, scheduled_at, expires_at in due_rows:
                if datetime.fromisoformat(expires_at) <= now:
                    status = "expired"
                elif datetime.fromisoformat(scheduled_at) <= now:
                    status = "active"
                else:
                    continue
                db.execute(
                    "UPDATE scheduled_interviews SET status=?,updated_at=? WHERE interview_id=?",
                    (status, now_text, interview_id),
                )
                changed.append((interview_id, status))
        return changed

    def create(self, *, candidate_name: str, candidate_email: str, role_id: str,
               job_offer: str, scheduled_at: str, expires_at: str) -> tuple[InterviewRecord, str]:
        self._validate_schedule(scheduled_at, expires_at)
        token = secrets.token_urlsafe(32)
        interview_id = f"ivw_{secrets.token_hex(6)}"
        now = _now()
        encrypted_token = self._encrypt_token(token)
        with self._connect() as db:
            db.execute(
                """INSERT INTO scheduled_interviews
                (interview_id,candidate_name,candidate_email,role_id,job_offer,scheduled_at,
                 expires_at,status,reviewer,link_token_hash,created_at,updated_at,
                 invitation_token_encrypted)
                VALUES (?,?,?,?,?,?,?,'scheduled','',?,?,?,?)""",
                (interview_id, candidate_name.strip(), candidate_email.strip().lower(),
                 role_id.strip(), job_offer.strip(), scheduled_at, expires_at,
                 _token_hash(token), now, now, encrypted_token),
            )
        return self.get(interview_id), token

    def create_many(self, rows: list[dict[str, str]]) -> list[tuple[InterviewRecord, str]]:
        created = []
        for row in rows:
            created.append(self.create(**row))
        return created

    def list(self, *, search: str = "", status: str = "", limit: int = 50,
             offset: int = 0) -> tuple[list[InterviewRecord], int]:
        where = []
        params: list[object] = []
        if search.strip():
            term = f"%{search.strip()}%"
            where.append("(candidate_name LIKE ? OR candidate_email LIKE ? OR role_id LIKE ? OR interview_id LIKE ?)")
            params.extend([term, term, term, term])
        if status.strip():
            where.append("status = ?")
            params.append(status.strip())
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        with self._connect() as db:
            total = db.execute(f"SELECT COUNT(*) FROM scheduled_interviews {clause}", params).fetchone()[0]
            rows = db.execute(
                f"SELECT * FROM scheduled_interviews {clause} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                [*params, max(1, min(limit, 200)), max(0, offset)],
            ).fetchall()
        return [self._record(row) for row in rows], int(total)

    def get(self, interview_id: str) -> InterviewRecord:
        with self._connect() as db:
            row = db.execute("SELECT * FROM scheduled_interviews WHERE interview_id=?", (interview_id,)).fetchone()
        if row is None:
            raise KeyError(interview_id)
        return self._record(row)

    def resolve_token(self, token: str, *, activate_due: bool = True) -> InterviewRecord | None:
        if not token:
            return None
        with self._connect() as db:
            row = db.execute("SELECT * FROM scheduled_interviews WHERE link_token_hash=?", (_token_hash(token),)).fetchone()
            if row is None:
                return None
            record = self._record(row)
            now = datetime.now(timezone.utc)
            if datetime.fromisoformat(record.expires_at) <= now:
                return self._set_status(db, record.interview_id, "expired")
            if record.status in {"revoked", "expired", "completed"}:
                return record
            if activate_due and record.status == "scheduled" and datetime.fromisoformat(record.scheduled_at) <= now:
                return self._set_status(db, record.interview_id, "active")
            return record

    def regenerate_link(
        self, interview_id: str, *, reset_invitation_status: bool = True
    ) -> tuple[InterviewRecord, str]:
        token = secrets.token_urlsafe(32)
        now = _now()
        encrypted_token = self._encrypt_token(token)
        invitation_update = (
            "invitation_status=CASE WHEN status='active' "
            "THEN 'not_sent' ELSE invitation_status END, "
            "invitation_sent_at=CASE WHEN status='active' THEN NULL "
            "ELSE invitation_sent_at END, "
            "invitation_error=NULL, "
            if reset_invitation_status
            else ""
        )
        with self._connect() as db:
            cursor = db.execute(
                "UPDATE scheduled_interviews SET link_token_hash=?, invitation_token_encrypted=?, "
                f"{invitation_update}updated_at=? "
                "WHERE interview_id=? AND status NOT IN ('completed','revoked','expired')",
                (_token_hash(token), encrypted_token, now, interview_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(interview_id)
        return self.get(interview_id), token

    def get_candidate_token(self, interview_id: str) -> str | None:
        from cryptography.fernet import InvalidToken

        record = self.get(interview_id)
        if not record.invitation_token_encrypted:
            return None
        try:
            return self._decrypt_token(record.invitation_token_encrypted)
        except (InvalidToken, FileNotFoundError):
            return None

    def claim_invitation_send(
        self, interview_id: str, *, allow_logged: bool = False
    ) -> tuple[InterviewRecord, bool]:
        with self._connect() as db:
            if self._postgres_dsn:
                db.execute("BEGIN")
                row = db.execute(
                    "SELECT * FROM scheduled_interviews WHERE interview_id=? FOR UPDATE",
                    (interview_id,),
                ).fetchone()
            else:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    "SELECT * FROM scheduled_interviews WHERE interview_id=?", (interview_id,)
                ).fetchone()
            if row is None:
                raise KeyError(interview_id)
            record = self._record(row)
            if record.status != "active":
                return record, False
            if record.invitation_status == "sent":
                return record, False
            if record.invitation_status == "logged" and not allow_logged:
                return record, False
            if record.invitation_status == "sending":
                return record, False
            db.execute(
                "UPDATE scheduled_interviews SET invitation_status='sending', "
                "invitation_error=NULL, "
                "invitation_attempts=invitation_attempts+1, updated_at=? "
                "WHERE interview_id=?",
                (_now(), interview_id),
            )
            row = db.execute(
                "SELECT * FROM scheduled_interviews WHERE interview_id=?", (interview_id,)
            ).fetchone()
        return self._record(row), True

    def list_active_pending_invitations(self) -> List[InterviewRecord]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM scheduled_interviews "
                "WHERE status='active' AND invitation_status='not_sent'"
            ).fetchall()
        return [self._record(row) for row in rows]

    def finish_invitation_send(
        self, interview_id: str, status: str, error: str | None = None
    ) -> InterviewRecord:
        sent_at = _now() if status == "sent" else None
        with self._connect() as db:
            db.execute(
                "UPDATE scheduled_interviews SET invitation_status=?, "
                "invitation_sent_at=COALESCE(?, invitation_sent_at), "
                "invitation_error=?, updated_at=? "
                "WHERE interview_id=?",
                (status, sent_at, error, _now(), interview_id),
            )
        return self.get(interview_id)

    def reset_stale_invitation_sends(self, stale_before: str) -> int:
        with self._connect() as db:
            cursor = db.execute(
                "UPDATE scheduled_interviews SET invitation_status='failed', "
                "invitation_error=?, updated_at=? "
                "WHERE invitation_status='sending' AND updated_at < ?",
                ("Previous send attempt did not finish; retry is available.", _now(), stale_before),
            )
        return cursor.rowcount

    def set_status(self, interview_id: str, status: str) -> InterviewRecord:
        with self._connect() as db:
            if status in {"active", "revoked", "completed"}:
                db.execute(
                    "UPDATE scheduled_interviews SET status=?, active_run_id=NULL, updated_at=? WHERE interview_id=?",
                    (status, _now(), interview_id),
                )
                row = db.execute(
                    "SELECT * FROM scheduled_interviews WHERE interview_id=?", (interview_id,)
                ).fetchone()
                if row is None:
                    raise KeyError(interview_id)
                return self._record(row)
            return self._set_status(db, interview_id, status)

    def set_active_run(self, interview_id: str, run_id: str) -> InterviewRecord:
        with self._connect() as db:
            cursor = db.execute(
                "UPDATE scheduled_interviews SET status='in_progress', active_run_id=?, updated_at=? "
                "WHERE interview_id=?",
                (run_id, _now(), interview_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(interview_id)
        return self.get(interview_id)

    def get_interview_id_for_run(self, run_id: str) -> str | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT interview_id FROM scheduled_interviews WHERE active_run_id=?",
                (run_id,),
            ).fetchone()
        return str(row[0]) if row else None

    def assign_reviewer(self, interview_id: str, reviewer: str) -> InterviewRecord:
        with self._connect() as db:
            cursor = db.execute(
                "UPDATE scheduled_interviews SET reviewer=?, updated_at=? WHERE interview_id=?",
                (reviewer.strip(), _now(), interview_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(interview_id)
        return self.get(interview_id)

    @staticmethod
    def _validate_schedule(scheduled_at: str, expires_at: str) -> None:
        start = datetime.fromisoformat(scheduled_at.replace("Z", "+00:00"))
        expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        if start.tzinfo is None or expiry.tzinfo is None:
            raise ValueError("scheduled_at and expires_at must include a timezone")
        if expiry <= start:
            raise ValueError("expires_at must be later than scheduled_at")

    def _set_status(self, db: Any, interview_id: str, status: str) -> InterviewRecord:
        db.execute("UPDATE scheduled_interviews SET status=?, updated_at=? WHERE interview_id=?",
                   (status, _now(), interview_id))
        row = db.execute("SELECT * FROM scheduled_interviews WHERE interview_id=?", (interview_id,)).fetchone()
        if row is None:
            raise KeyError(interview_id)
        return self._record(row)

    @staticmethod
    def _record(row: sqlite3.Row | tuple) -> InterviewRecord:
        return InterviewRecord(*row)

    def _connect(self) -> Any:
        if self._postgres_dsn:
            assert psycopg is not None
            return _PostgresConnection(psycopg.connect(self._postgres_dsn))
        db = sqlite3.connect(self._path)
        db.row_factory = sqlite3.Row
        return db

    def _encrypt_token(self, token: str) -> str:
        from cryptography.fernet import Fernet

        secret = os.getenv("AI_INTERVIEWER_INVITATION_ENCRYPTION_KEY", "").strip()
        if secret:
            key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
        else:
            key_path = self._path.with_name(f"{self._path.stem}.invitation.key")
            try:
                key = key_path.read_bytes()
            except FileNotFoundError:
                generated = Fernet.generate_key()
                try:
                    with key_path.open("xb") as key_file:
                        key_file.write(generated)
                    try:
                        os.chmod(key_path, 0o600)
                    except OSError:
                        pass
                    key = generated
                except FileExistsError:
                    key = key_path.read_bytes()
        return Fernet(key).encrypt(token.encode("utf-8")).decode("ascii")

    def _decrypt_token(self, encrypted: str) -> str:
        from cryptography.fernet import Fernet

        secret = os.getenv("AI_INTERVIEWER_INVITATION_ENCRYPTION_KEY", "").strip()
        if secret:
            key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
        else:
            key = self._path.with_name(f"{self._path.stem}.invitation.key").read_bytes()
        return Fernet(key).decrypt(encrypted.encode("ascii")).decode("utf-8")
