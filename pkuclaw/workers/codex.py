from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from pkuclaw.capabilities import render_capabilities
from pkuclaw.config import Settings
from pkuclaw.core import logging as log
from pkuclaw.core.models import TaskPlan, WorkerResult
from pkuclaw.core.store import RunRecord, Store


CodexRunResult = WorkerResult


class CodexWorker:
    def __init__(
        self,
        *,
        settings: Settings,
        store: Store,
        repo_root: Path | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.repo_root = (repo_root or Path.cwd()).resolve()
        self.runs_dir = self.settings.app.data_dir / "codex_runs"

    def run(self, run: RunRecord, plan: TaskPlan) -> CodexRunResult:
        conversation = self.store.ensure_conversation(run.conversation_id)
        run_dir = self.runs_dir / run.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        log.event(
            "codex context: "
            f"run={run.run_id}, intent={plan.intent}, "
            f"mode={conversation.mode}, "
            f"existing_thread={conversation.codex_session_id or 'none'}"
        )

        prompt_path = run_dir / "prompt.md"
        result_path = run_dir / "result.md"
        stdout_path = run_dir / "stdout.jsonl"
        stderr_path = run_dir / "stderr.log"

        log.stage(f"Building Codex prompt: run={run.run_id}")
        prompt = self._build_prompt(run=run, plan=plan, run_dir=run_dir)
        prompt_path.write_text(prompt, encoding="utf-8")
        log.ok(f"Prompt written: {prompt_path} ({len(prompt)} chars)")
        self.store.mark_run_running(
            run.run_id,
            prompt_path=prompt_path,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )

        before_sessions = _read_session_index()
        command = self._build_command(
            session_id=conversation.codex_session_id,
            result_path=result_path,
        )
        mode = "resume" if conversation.codex_session_id else "new"
        log.stage(
            "Running Codex CLI: "
            f"mode={mode}, sandbox={self.settings.codex.sandbox}, "
            f"timeout={self.settings.codex.timeout_seconds}s"
        )
        log.event(
            "Codex artifacts: "
            f"stdout={stdout_path}, stderr={stderr_path}, result={result_path}"
        )

        try:
            completed = subprocess.run(
                command,
                input=prompt,
                text=True,
                capture_output=True,
                cwd=self.repo_root,
                timeout=self.settings.codex.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            stdout_path.write_text(exc.stdout or "", encoding="utf-8")
            stderr_path.write_text(exc.stderr or "", encoding="utf-8")
            error = f"Codex timed out after {self.settings.codex.timeout_seconds}s"
            self.store.mark_run_failed(run.run_id, error)
            log.fail(error)
            return CodexRunResult(
                run_id=run.run_id,
                status="failed",
                response_text=error,
                session_id=conversation.codex_session_id,
                result_path=result_path,
            )

        stdout_path.write_text(completed.stdout, encoding="utf-8")
        stderr_path.write_text(completed.stderr, encoding="utf-8")
        log.event(f"Codex CLI exited: code={completed.returncode}")

        if completed.returncode != 0:
            error = _summarize_failure(completed.stderr, completed.stdout)
            self.store.mark_run_failed(run.run_id, error)
            log.fail(f"Codex CLI failed: run={run.run_id}")
            return CodexRunResult(
                run_id=run.run_id,
                status="failed",
                response_text=error,
                session_id=conversation.codex_session_id,
                result_path=result_path,
            )

        session_id = conversation.codex_session_id or _detect_new_session_id(
            before_sessions=before_sessions,
            stdout=completed.stdout,
        )
        response_text = _read_result_text(result_path, completed.stdout)
        if session_id:
            log.ok(f"Codex thread ready: {session_id}")
        else:
            log.warn(
                "Codex thread id was not detected; next message will start a new thread"
            )
        log.ok(f"Codex result loaded: {result_path} ({len(response_text)} chars)")
        self.store.mark_run_succeeded(
            run.run_id,
            response_text=response_text,
            result_path=result_path,
            session_id=session_id,
        )
        return CodexRunResult(
            run_id=run.run_id,
            status="succeeded",
            response_text=response_text,
            session_id=session_id,
            result_path=result_path,
        )

    def _build_command(self, *, session_id: str | None, result_path: Path) -> list[str]:
        command = [self.settings.codex.bin, "exec"]
        if session_id:
            command.extend(["resume", "--json", "-o", str(result_path)])
            if self.settings.codex.model:
                command.extend(["-m", self.settings.codex.model])
            command.extend([session_id, "-"])
            return command

        command.extend(
            [
                "--json",
                "-C",
                str(self.repo_root),
                "-s",
                self.settings.codex.sandbox,
                "-o",
                str(result_path),
            ]
        )
        if self.settings.codex.model:
            command.extend(["-m", self.settings.codex.model])
        command.append("-")
        return command

    def _build_prompt(
        self,
        *,
        run: RunRecord,
        plan: TaskPlan,
        run_dir: Path,
    ) -> str:
        conversation = self.store.ensure_conversation(run.conversation_id)
        capabilities = render_capabilities(plan.capability_names)
        recent = self.store.recent_runs(conversation_id=run.conversation_id, limit=5)
        recent_lines = [
            f"- {item.created_at} [{item.intent}/{item.status}] {item.user_text[:80]}"
            for item in recent
            if item.run_id != run.run_id
        ]
        recent_text = "\n".join(recent_lines) or "- none"

        return f"""# PkuClaw Core Loop Worker Task

You are being invoked by the PkuClaw backend core loop, not directly by a chat user.

## Selected Intent

{plan.intent}

## Conversation Mode

{conversation.mode}

## Available Runtime Facts

- Repository root: `{self.repo_root}`
- Run directory: `{run_dir}`
- Teaching snapshots directory: `{self.settings.app.data_dir / "snapshots"}`
- Feishu/Web/WeChat I/O is owned by channel adapters, not by this worker.
- Homework submission requires explicit backend confirmation.

## Recent Conversation Runs

{recent_text}

## Backend Capability Contracts

{capabilities}

## User Message

{run.user_text}
"""


def _read_session_index() -> list[dict[str, Any]]:
    path = Path.home() / ".codex" / "session_index.jsonl"
    if not path.exists():
        return []
    sessions: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            sessions.append(data)
    return sessions


def _detect_new_session_id(
    *,
    before_sessions: list[dict[str, Any]],
    stdout: str,
) -> str | None:
    before_ids = {item.get("id") for item in before_sessions}
    after_sessions = _read_session_index()
    new_sessions = [item for item in after_sessions if item.get("id") not in before_ids]
    if new_sessions:
        return str(new_sessions[-1].get("id"))
    return _find_session_id_in_jsonl(stdout)


def _find_session_id_in_jsonl(stdout: str) -> str | None:
    for line in stdout.splitlines():
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        found = _find_key_recursive(
            data,
            {"session_id", "sessionId", "thread_id", "threadId"},
        )
        if isinstance(found, str):
            return found
    return None


def _find_key_recursive(value: Any, keys: set[str]) -> Any:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in keys:
                return item
            found = _find_key_recursive(item, keys)
            if found is not None:
                return found
    if isinstance(value, list):
        for item in value:
            found = _find_key_recursive(item, keys)
            if found is not None:
                return found
    return None


def _read_result_text(result_path: Path, stdout: str) -> str:
    if result_path.exists():
        text = result_path.read_text(encoding="utf-8").strip()
        if text:
            return text
    return _last_text_from_jsonl(stdout) or stdout.strip() or "Codex completed with no output."


def _last_text_from_jsonl(stdout: str) -> str | None:
    last_text: str | None = None
    for line in stdout.splitlines():
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        text = _find_key_recursive(data, {"text", "message", "content"})
        if isinstance(text, str) and text.strip():
            last_text = text.strip()
    return last_text


def _summarize_failure(stderr: str, stdout: str) -> str:
    combined = (stderr.strip() or stdout.strip() or "Codex failed with no output.")
    return combined[-2000:]
