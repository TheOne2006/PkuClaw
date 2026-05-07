"""SQLite state store for conversations, runs, channel messages and audit records."""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from pkuclaw.core.models import (
    DEFAULT_AGENT_MODE,
    DEFAULT_AGENT_MODEL,
    DEFAULT_AGENT_PROVIDER,
    DEFAULT_AGENT_REASONING_EFFORT,
    AgentSettings,
)


def utc_now() -> str:
    """返回带 UTC timezone 的 ISO8601 时间戳。"""
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Conversation:
    """持久化会话记录和该会话的默认 Agent 设置。"""
    conversation_id: str
    agent_session_id: str | None
    agent_settings: AgentSettings
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class RunRecord:
    """持久化 Agent run 的核心状态字段。"""
    run_id: str
    conversation_id: str
    status: str
    source: str
    user_text: str
    response_text: str | None
    result_path: str | None
    error: str | None
    created_at: str
    updated_at: str
    finished_at: str | None


@dataclass(frozen=True)
class ArtifactRecord:
    """run 产生的用户可见产物记录。"""
    id: int
    run_id: str
    kind: str
    path: str
    title: str
    created_at: str


@dataclass(frozen=True)
class RunDetailRecord:
    """详情页使用的结构化 run 事实快照。"""
    run: RunRecord
    metadata: dict[str, Any]
    agent: AgentSettings
    paths: dict[str, str]
    artifacts: tuple[ArtifactRecord, ...]


@dataclass(frozen=True)
class ChannelMessageRecord:
    """run 与外部 channel 消息 ID 的映射记录。"""
    id: int
    run_id: str
    channel: str
    target_id: str
    external_message_id: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class RuntimeChangeRecord:
    """runtime.json 变更审计记录。"""
    id: int
    run_id: str | None
    actor: str
    file: str
    action: str
    old_hash: str | None
    new_hash: str | None
    diff_summary: str
    status: str
    created_at: str


class Store:
    """SQLite 数据访问对象，封装 schema 和查询更新。"""
    def __init__(
        self,
        db_path: Path,
        *,
        default_agent_settings: AgentSettings | None = None,
    ) -> None:
        self.db_path = db_path
        self.default_agent_settings = _complete_agent_settings(default_agent_settings)
        self._lock = threading.Lock()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init()

    def init(self) -> None:
        """创建当前 SQLite schema。"""
        with self._connect() as conn:
            # Schema lives in code so a fresh daemon can create
            # its local state without a separate migration tool.
            conn.executescript(
                """
                create table if not exists conversations (
                    chat_id text primary key,
                    agent_session_id text,
                    agent_provider text not null,
                    agent_mode text not null,
                    agent_model text not null,
                    agent_reasoning_effort text not null,
                    created_at text not null,
                    updated_at text not null
                );

                create table if not exists runs (
                    run_id text primary key,
                    chat_id text not null,
                    status text not null,
                    source text not null,
                    user_text text not null,
                    response_text text,
                    result_path text,
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

                create table if not exists channel_messages (
                    id integer primary key autoincrement,
                    run_id text not null,
                    channel text not null,
                    target_id text not null,
                    external_message_id text not null,
                    created_at text not null,
                    updated_at text not null,
                    unique(run_id, channel, target_id),
                    foreign key (run_id) references runs(run_id)
                );

                create table if not exists runtime_changes (
                    id integer primary key autoincrement,
                    run_id text,
                    actor text not null,
                    file text not null,
                    action text not null,
                    old_hash text,
                    new_hash text,
                    diff_summary text not null,
                    status text not null,
                    created_at text not null
                );
                """
            )

    def ensure_conversation(self, conversation_id: str) -> Conversation:
        """读取会话；不存在时创建一条默认会话记录。"""
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "select * from conversations where chat_id = ?", (conversation_id,)
            ).fetchone()
            if row is None:
                now = utc_now()
                defaults = self.default_agent_settings
                conn.execute(
                    """
                    insert into conversations(
                        chat_id, agent_session_id, agent_provider, agent_mode,
                        agent_model, agent_reasoning_effort, created_at, updated_at
                    )
                    values (?, null, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        conversation_id,
                        defaults.provider,
                        defaults.mode,
                        defaults.model,
                        defaults.reasoning_effort,
                        now,
                        now,
                    ),
                )
                row = conn.execute(
                    "select * from conversations where chat_id = ?", (conversation_id,)
                ).fetchone()
            return _conversation_from_row(row)

    def set_conversation_session(self, conversation_id: str, session_id: str) -> None:
        """记录该 conversation 对应的 Codex session/thread id。"""
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                update conversations
                set agent_session_id = ?, updated_at = ?
                where chat_id = ?
                """,
                (session_id, utc_now(), conversation_id),
            )

    def update_agent_settings(
        self,
        conversation_id: str,
        *,
        provider: str | None = None,
        mode: str | None = None,
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> Conversation:
        """更新单个会话的 Agent provider/mode/model/reasoning 默认值。"""
        self.ensure_conversation(conversation_id)
        current = self.ensure_conversation(conversation_id).agent_settings
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                update conversations
                set agent_provider = ?, agent_mode = ?, agent_model = ?,
                    agent_reasoning_effort = ?, updated_at = ?
                where chat_id = ?
                """,
                (
                    provider if provider is not None else current.provider,
                    mode if mode is not None else current.mode,
                    model if model is not None else current.model,
                    (
                        reasoning_effort
                        if reasoning_effort is not None
                        else current.reasoning_effort
                    ),
                    utc_now(),
                    conversation_id,
                ),
            )
        return self.ensure_conversation(conversation_id)

    def create_run(
        self,
        *,
        conversation_id: str,
        user_text: str,
        source: str,
        metadata: dict[str, Any] | None = None,
    ) -> RunRecord:
        """插入 queued run 记录并返回持久化对象。"""
        self.ensure_conversation(conversation_id)
        run_id = uuid.uuid4().hex
        now = utc_now()
        with self._lock, self._connect() as conn:
            metadata_json = json.dumps(metadata or {}, ensure_ascii=False)
            conn.execute(
                """
                insert into runs(
                    run_id, chat_id, status, source, user_text, metadata_json,
                    created_at, updated_at
                )
                values (?, ?, 'queued', ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    conversation_id,
                    source,
                    user_text,
                    metadata_json,
                    now,
                    now,
                ),
            )
        return self.get_run(run_id)

    def mark_run_running(self, run_id: str) -> None:
        """把 run 标记为 running。"""
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                update runs
                set status = 'running', updated_at = ?
                where run_id = ?
                """,
                (
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
        """把 run 标记为 succeeded，并保存响应、结果路径和 session id。"""
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
                values (?, 'agent_result', ?, 'Agent result', ?)
                """,
                (run_id, str(result_path), now),
            )

    def mark_run_failed(
        self,
        run_id: str,
        error: str,
        *,
        response_text: str | None = None,
        result_path: Path | None = None,
    ) -> None:
        """把 run 标记为 failed，并保存错误信息。"""
        now = utc_now()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                update runs
                set status = 'failed', error = ?,
                    response_text = coalesce(?, response_text),
                    result_path = coalesce(?, result_path),
                    updated_at = ?, finished_at = ?
                where run_id = ?
                """,
                (
                    error,
                    response_text,
                    str(result_path) if result_path is not None else None,
                    now,
                    now,
                    run_id,
                ),
            )

    def update_run_metadata(self, run_id: str, metadata: dict[str, Any]) -> None:
        """合并更新 run 的 metadata_json 字段。"""
        current = self.get_run_metadata(run_id)
        # Metadata is a shallow JSON object; callers pass only the keys they own.
        current.update(metadata)
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                update runs
                set metadata_json = ?, updated_at = ?
                where run_id = ?
                """,
                (json.dumps(current, ensure_ascii=False), utc_now(), run_id),
            )

    def get_run_metadata(self, run_id: str) -> dict[str, Any]:
        """读取并解析 run metadata_json。"""
        with self._connect() as conn:
            row = conn.execute(
                "select metadata_json from runs where run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"run not found: {run_id}")
        data = json.loads(str(row["metadata_json"]))
        if not isinstance(data, dict):
            raise RuntimeError(f"run metadata_json must be an object: {run_id}")
        return data

    def run_artifacts(self, run_id: str) -> tuple[ArtifactRecord, ...]:
        """读取一个 run 的用户可见产物记录。"""
        with self._connect() as conn:
            rows = conn.execute(
                """
                select * from artifacts
                where run_id = ?
                order by id asc
                """,
                (run_id,),
            ).fetchall()
        return tuple(_artifact_from_row(row) for row in rows)

    def get_run_detail(self, run_id: str) -> RunDetailRecord:
        """读取详情页所需的结构化 run 事实快照。"""
        run = self.get_run(run_id)
        metadata = self.get_run_metadata(run_id)
        agent_raw = _required_metadata_object(metadata, "agent", run_id=run_id)
        paths_raw = _required_metadata_object(metadata, "paths", run_id=run_id)
        return RunDetailRecord(
            run=run,
            metadata=metadata,
            agent=AgentSettings(
                provider=_required_metadata_str(agent_raw, "provider", run_id=run_id),
                mode=_required_metadata_str(agent_raw, "mode", run_id=run_id),
                model=_required_metadata_str(agent_raw, "model", run_id=run_id),
                reasoning_effort=_required_metadata_str(
                    agent_raw,
                    "reasoning_effort",
                    run_id=run_id,
                ),
            ),
            paths={
                "run_dir": _required_metadata_str(paths_raw, "run_dir", run_id=run_id),
                "prompt": _required_metadata_str(paths_raw, "prompt", run_id=run_id),
                "stdout": _required_metadata_str(paths_raw, "stdout", run_id=run_id),
                "stderr": _required_metadata_str(paths_raw, "stderr", run_id=run_id),
                "result": _required_metadata_str(paths_raw, "result", run_id=run_id),
            },
            artifacts=self.run_artifacts(run_id),
        )

    def record_channel_message(
        self,
        *,
        run_id: str,
        channel: str,
        target_id: str,
        external_message_id: str,
    ) -> None:
        """记录或更新 run 到外部消息 ID 的映射。"""
        now = utc_now()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                insert into channel_messages(
                    run_id, channel, target_id, external_message_id,
                    created_at, updated_at
                )
                values (?, ?, ?, ?, ?, ?)
                on conflict(run_id, channel, target_id) do update set
                    external_message_id = excluded.external_message_id,
                    updated_at = excluded.updated_at
                """,
                (run_id, channel, target_id, external_message_id, now, now),
            )

    def get_channel_message(
        self,
        *,
        run_id: str,
        channel: str,
        target_id: str,
    ) -> ChannelMessageRecord | None:
        """读取 run 在某 channel/target 上发送过的外部消息。"""
        with self._connect() as conn:
            row = conn.execute(
                """
                select * from channel_messages
                where run_id = ? and channel = ? and target_id = ?
                """,
                (run_id, channel, target_id),
            ).fetchone()
        if row is None:
            return None
        return _channel_message_from_row(row)

    def record_runtime_change(
        self,
        *,
        run_id: str | None,
        actor: str,
        file: str,
        action: str,
        old_hash: str | None,
        new_hash: str | None,
        diff_summary: str,
        status: str,
    ) -> int:
        """Append one sanitized runtime config change audit record."""

        actor = actor.strip() or "unknown"
        action = action.strip() or "runtime_change"
        now = utc_now()
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                """
                insert into runtime_changes(
                    run_id, actor, file, action, old_hash, new_hash,
                    diff_summary, status, created_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id or None,
                    actor,
                    file,
                    action,
                    old_hash,
                    new_hash,
                    diff_summary[:1000],
                    status,
                    now,
                ),
            )
            return int(cursor.lastrowid)

    def runtime_changes(self, *, limit: int = 50) -> list[RuntimeChangeRecord]:
        """按时间倒序读取最近的 runtime 配置审计记录。"""
        with self._connect() as conn:
            rows = conn.execute(
                """
                select * from runtime_changes
                order by id desc
                limit ?
                """,
                (max(1, min(limit, 200)),),
            ).fetchall()
        return [_runtime_change_from_row(row) for row in rows]

    def get_run(self, run_id: str) -> RunRecord:
        """按 run_id 读取一条运行记录。"""
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
        """读取最近运行记录，可按 conversation 过滤。"""
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
        """统计各 run 状态的数量。"""
        with self._connect() as conn:
            rows = conn.execute(
                "select status, count(*) as count from runs group by status"
            ).fetchall()
        return {str(row["status"]): int(row["count"]) for row in rows}

    def active_conversation_count(self) -> int:
        """统计 Store 中已有会话数。"""
        with self._connect() as conn:
            row = conn.execute("select count(*) as count from conversations").fetchone()
        return int(row["count"])

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """打开 SQLite 连接并启用 WAL 和外键约束。"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        # WAL improves concurrent read/write behavior for Feishu callbacks,
        # LoopManager workers, and local notify queue workers sharing the same local DB.
        conn.execute("pragma journal_mode = wal")
        conn.execute("pragma foreign_keys = on")
        try:
            with conn:
                yield conn
        finally:
            conn.close()


def _conversation_from_row(row: sqlite3.Row) -> Conversation:
    """把 SQLite row 转换为 Conversation。"""
    return Conversation(
        conversation_id=str(row["chat_id"]),
        agent_session_id=row["agent_session_id"],
        agent_settings=AgentSettings(
            provider=_required_row_str(row, "agent_provider"),
            mode=_required_row_str(row, "agent_mode"),
            model=_required_row_str(row, "agent_model"),
            reasoning_effort=_required_row_str(row, "agent_reasoning_effort"),
        ),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _run_from_row(row: sqlite3.Row) -> RunRecord:
    """把 SQLite row 转换为 RunRecord。"""
    return RunRecord(
        run_id=str(row["run_id"]),
        conversation_id=str(row["chat_id"]),
        status=str(row["status"]),
        source=str(row["source"]),
        user_text=str(row["user_text"]),
        response_text=row["response_text"],
        result_path=row["result_path"],
        error=row["error"],
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        finished_at=row["finished_at"],
    )


def _artifact_from_row(row: sqlite3.Row) -> ArtifactRecord:
    """把 SQLite row 转换为 ArtifactRecord。"""
    return ArtifactRecord(
        id=int(row["id"]),
        run_id=str(row["run_id"]),
        kind=str(row["kind"]),
        path=str(row["path"]),
        title=str(row["title"]),
        created_at=str(row["created_at"]),
    )


def _channel_message_from_row(row: sqlite3.Row) -> ChannelMessageRecord:
    """把 SQLite row 转换为 ChannelMessageRecord。"""
    return ChannelMessageRecord(
        id=int(row["id"]),
        run_id=str(row["run_id"]),
        channel=str(row["channel"]),
        target_id=str(row["target_id"]),
        external_message_id=str(row["external_message_id"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _runtime_change_from_row(row: sqlite3.Row) -> RuntimeChangeRecord:
    """把 SQLite row 转换为 RuntimeChangeRecord。"""
    return RuntimeChangeRecord(
        id=int(row["id"]),
        run_id=row["run_id"],
        actor=str(row["actor"]),
        file=str(row["file"]),
        action=str(row["action"]),
        old_hash=row["old_hash"],
        new_hash=row["new_hash"],
        diff_summary=str(row["diff_summary"]),
        status=str(row["status"]),
        created_at=str(row["created_at"]),
    )


def _complete_agent_settings(settings: AgentSettings | None) -> AgentSettings:
    """补齐默认 Agent 设置，确保新 conversation 字段非空。"""
    settings = settings or AgentSettings()
    return AgentSettings(
        provider=settings.provider or DEFAULT_AGENT_PROVIDER,
        mode=settings.mode or DEFAULT_AGENT_MODE,
        model=settings.model or DEFAULT_AGENT_MODEL,
        reasoning_effort=(
            settings.reasoning_effort or DEFAULT_AGENT_REASONING_EFFORT
        ),
    )


def _required_row_str(row: sqlite3.Row, column: str) -> str:
    """读取当前 schema 下必须存在且非空的字符串列。"""
    value = row[column]
    if value is None or not str(value).strip():
        raise RuntimeError(f"required database column is empty: {column}")
    return str(value)


def _required_metadata_object(
    metadata: dict[str, Any],
    key: str,
    *,
    run_id: str,
) -> dict[str, Any]:
    """读取当前 metadata schema 下必须存在的对象字段。"""
    value = metadata.get(key)
    if not isinstance(value, dict):
        raise RuntimeError(f"run metadata missing object '{key}': {run_id}")
    return value


def _required_metadata_str(
    metadata: dict[str, Any],
    key: str,
    *,
    run_id: str,
) -> str:
    """读取当前 metadata schema 下必须存在且非空的字符串字段。"""
    value = metadata.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"run metadata missing string '{key}': {run_id}")
    return value.strip()
