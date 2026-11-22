from __future__ import annotations

import os
from contextlib import AbstractContextManager
from pathlib import Path
from threading import RLock
from typing import Any

from langgraph.graph.state import CompiledStateGraph

from services.agent.graph.studio_graph import builder

_lock = RLock()
_checkpoint_contexts: dict[str, AbstractContextManager[Any]] = {}
_checkpointed_graphs: dict[str, CompiledStateGraph] = {}


def get_checkpointed_graph(
    *, db_path: str | Path | None = None, dsn: str | None = None
) -> CompiledStateGraph:
    with _lock:
        backend = os.getenv("AI_INTERVIEWER_DB_BACKEND", "sqlite").strip().lower()
        context: AbstractContextManager[Any]
        if backend == "postgres":
            raw_dsn = dsn or os.getenv("AI_INTERVIEWER_LANGGRAPH_POSTGRES_DSN") or ""
            resolved_dsn = raw_dsn.strip()
            if not resolved_dsn:
                raise RuntimeError(
                    "AI_INTERVIEWER_LANGGRAPH_POSTGRES_DSN is required when "
                    "Postgres is selected; use a separate database from the API "
                    "because both systems own a checkpoints table"
                )
            try:
                from langgraph.checkpoint.postgres import PostgresSaver
            except ImportError as exc:
                raise RuntimeError(
                    "Postgres LangGraph checkpoints require installing "
                    "services/agent with the postgres extra"
                ) from exc
            key = f"postgres:{resolved_dsn}"
            context = PostgresSaver.from_conn_string(resolved_dsn)
        elif backend == "sqlite":
            from langgraph.checkpoint.sqlite import SqliteSaver

            configured_path = os.getenv("AI_INTERVIEWER_DB_PATH", "").strip()
            db_path = (
                Path(db_path or configured_path)
                if configured_path
                else Path(db_path)
                if db_path is not None
                else Path(__file__).resolve().parents[3]
                / "data"
                / "ai_interviewer.sqlite3"
            )
            db_path.parent.mkdir(parents=True, exist_ok=True)
            key = f"sqlite:{db_path.resolve()}"
            context = SqliteSaver.from_conn_string(str(db_path))
        else:
            raise RuntimeError(f"Unsupported checkpoint database backend: {backend}")

        if key in _checkpointed_graphs:
            return _checkpointed_graphs[key]

        _checkpoint_contexts[key] = context
        checkpointer = context.__enter__()
        setup = getattr(checkpointer, "setup", None)
        if callable(setup):
            setup()
        _checkpointed_graphs[key] = builder.compile(checkpointer=checkpointer)
        return _checkpointed_graphs[key]


def close_checkpointed_graph() -> None:
    with _lock:
        for context in _checkpoint_contexts.values():
            context.__exit__(None, None, None)
        _checkpoint_contexts.clear()
        _checkpointed_graphs.clear()