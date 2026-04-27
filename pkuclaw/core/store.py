from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Conversation:
    conversation_id: str
    codex_session_id: str | None
    mode: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    conversation_id: str
    status: str
    intent: str
    user_text: str
    response_text: str | None
    result_path: str | None
    created_at: str
    updated_at: str
    finished_at: str | None


class Store:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._lock = threading.Lock()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init()

    def init(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                create table if not exists conversations (
                    chat_id text primary key,
                    codex_session_id text,
                    mode text not null default 'standard',
                    created_at text not null,
                    updated_at text not null
                );

                create table if not exists runs (
                    run_id text primary key,
                    chat_id text not null,
                    status text not null,
                    intent text not null,
                    user_text text not null,
                    response_text text,
                    result_path text,
                    stdout_path text,
                    stderr_path text,
                    prompt_path text,
                    error text,
                    metadata_json text not null default '{}',
                    created_at text not null,
                    updated_at text not null,
                    finished_at text,
                    foreign key (chat_id) references conversations(chat_id)
                );

                create table if not exists artifacts (
                    id integer primary key autoincrement,
                    run_id text not null,
                    kind text not null,
                    path text not null,
                    title text not null,
                    created_at text not null,
                    foreign key (run_id) references runs(run_id)
                );
                """
            )
            _ensure_column(
                conn,
                table="conversations",
                column="mode",
                definition="text not null default 'standard'",
            )

    def ensure_conversation(self, conversation_id: str) -> Conversation:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "select * from conversations where chat_id = ?", (conversation_id,)
            ).fetchone()
            if row is None:
                now = utc_now()
                conn.execute(
                    """
                    insert into conversations(chat_id, codex_session_id, created_at, updated_at)
                    values (?, null, ?, ?)
                    """,
                    (conversation_id, now, now),
                )
                row = conn.execute(
                    "select * from conversations where chat_id = ?", (conversation_id,)
                ).fetchone()
            return _conversation_from_row(row)

    def set_conversation_session(self, conversation_id: str, session_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                update conversations
                set codex_session_id = ?, updated_at = ?
                where chat_id = ?
                """,
                (session_id, utc_now(), conversation_id),
            )

    def set_conversation_mode(self, conversation_id: str, mode: str) -> Conversation:
        self.ensure_conversation(conversation_id)
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                update conversations
                set mode = ?, updated_at = ?
                where chat_id = ?
                """,
                (mode, utc_now(), conversation_id),
            )
        return self.ensure_conversation(conversation_id)

    def create_run(
        self,
        *,
        conversation_id: str,
        user_text: str,
        intent: str,
        metadata: dict[str, Any] | None = None,
    ) -> RunRecord:
        self.ensure_conversation(conversation_id)
        run_id = uuid.uuid4().hex
        now = utc_now()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                insert into runs(
                    run_id, chat_id, status, intent, user_text, metadata_json,
                    created_at, updated_at
                )
                values (?, ?, 'queued', ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    conversation_id,
                    intent,
                    user_text,
                    json.dumps(metadata or {}, ensure_ascii=False),
                    now,
                    now,
                ),
            )
        return self.get_run(run_id)

    def mark_run_running(
        self,
        run_id: str,
        *,
        prompt_path: Path,
        stdout_path: Path,
        stderr_path: Path,
    ) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                update runs
                set status = 'running', prompt_path = ?, stdout_path = ?,
                    stderr_path = ?, updated_at = ?
                where run_id = ?
                """,
                (
                    str(prompt_path),
                    str(stdout_path),
                    str(stderr_path),
                    utc_now(),
                    run_id,
                ),
            )

    def mark_run_succeeded(
        self,
        run_id: str,
        *,
        response_text: str,
        result_path: Path,
        session_id: str | None,
    ) -> None:
        run = self.get_run(run_id)
        if session_id:
            self.set_conversation_session(run.conversation_id, session_id)
        now = utc_now()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                update runs
                set status = 'succeeded', response_text = ?, result_path = ?,
                    updated_at = ?, finished_at = ?
                where run_id = ?
                """,
                (response_text, str(result_path), now, now, run_id),
            )
            conn.execute(
                """
                insert into artifacts(run_id, kind, path, title, created_at)
                values (?, 'codex_result', ?, 'Codex result', ?)
                """,
                (run_id, str(result_path), now),
            )

    def mark_run_failed(self, run_id: str, error: str) -> None:
        now = utc_now()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                update runs
                set status = 'failed', error = ?, updated_at = ?, finished_at = ?
                where run_id = ?
                """,
                (error, now, now, run_id),
            )

    def get_run(self, run_id: str) -> RunRecord:
        with self._connect() as conn:
            row = conn.execute("select * from runs where run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(f"run not found: {run_id}")
        return _run_from_row(row)

    def recent_runs(
        self,
        conversation_id: str | None = None,
        limit: int = 5,
    ) -> list[RunRecord]:
        sql = "select * from runs"
        params: tuple[Any, ...] = ()
        if conversation_id is not None:
            sql += " where chat_id = ?"
            params = (conversation_id,)
        sql += " order by created_at desc limit ?"
        params = (*params, limit)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_run_from_row(row) for row in rows]

    def counts_by_status(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                "select status, count(*) as count from runs group by status"
            ).fetchall()
        return {str(row["status"]): int(row["count"]) for row in rows}

    def active_conversation_count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("select count(*) as count from conversations").fetchone()
        return int(row["count"])

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("pragma journal_mode = wal")
        conn.execute("pragma foreign_keys = on")
        return conn


def _conversation_from_row(row: sqlite3.Row) -> Conversation:
    return Conversation(
        conversation_id=str(row["chat_id"]),
        codex_session_id=row["codex_session_id"],
        mode=str(row["mode"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _run_from_row(row: sqlite3.Row) -> RunRecord:
    return RunRecord(
        run_id=str(row["run_id"]),
        conversation_id=str(row["chat_id"]),
        status=str(row["status"]),
        intent=str(row["intent"]),
        user_text=str(row["user_text"]),
        response_text=row["response_text"],
        result_path=row["result_path"],
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        finished_at=row["finished_at"],
    )


def _ensure_column(
    conn: sqlite3.Connection,
    *,
    table: str,
    column: str,
    definition: str,
) -> None:
    rows = conn.execute(f"pragma table_info({table})").fetchall()
    existing = {str(row["name"]) for row in rows}
    if column in existing:
        return
    conn.execute(f"alter table {table} add column {column} {definition}")
