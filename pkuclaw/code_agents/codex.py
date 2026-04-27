from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from pkuclaw.capabilities import render_capabilities
from pkuclaw.config import Settings
from pkuclaw.core import logging as log
from pkuclaw.core.models import (
    CodeAgentEvent,
    CodeAgentEventSink,
    CodeAgentResult,
    CodeAgentSettings,
    TaskPlan,
    merge_agent_settings,
)
from pkuclaw.core.store import RunRecord, Store
from pkuclaw.runtime_config import RuntimeConfigLoader

class CodexAgent:
    name = "codex"

    def __init__(
        self,
        *,
        settings: Settings,
        store: Store,
        runtime_config: RuntimeConfigLoader,
        repo_root: Path | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.runtime_config = runtime_config
        self.repo_root = (repo_root or Path.cwd()).resolve()
        self.runs_dir = self.settings.app.data_dir / "code_agent_runs" / self.name

    def run(
        self,
        run: RunRecord,
        plan: TaskPlan,
        sink: CodeAgentEventSink,
    ) -> CodeAgentResult:
        conversation = self.store.ensure_conversation(run.conversation_id)
        runtime = self.runtime_config.read()
        agent_settings = merge_agent_settings(
            runtime.code_agent,
            conversation.agent_settings,
        )
        run_dir = self.runs_dir / run.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        log.event(
            "code agent context: "
            f"agent={self.name}, run={run.run_id}, intent={plan.intent}, "
            f"mode={agent_settings.mode}, "
            f"model={self._effective_model(agent_settings) or 'default'}, "
            "reasoning="
            f"{self._effective_reasoning(agent_settings) or 'default'}, "
            f"existing_thread={conversation.agent_session_id or 'none'}"
        )

        prompt_path = run_dir / "prompt.md"
        result_path = run_dir / "result.md"
        stdout_path = run_dir / "stdout.jsonl"
        stderr_path = run_dir / "stderr.log"

        log.stage(f"Building Codex prompt: run={run.run_id}")
        prompt = self._build_prompt(
            run=run,
            plan=plan,
            run_dir=run_dir,
            runtime=runtime,
            agent_settings=agent_settings,
        )
        prompt_path.write_text(prompt, encoding="utf-8")
        log.ok(f"Prompt written: {prompt_path} ({len(prompt)} chars)")
        self.store.mark_run_running(
            run.run_id,
            prompt_path=prompt_path,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )
        _emit_agent_event(
            sink,
            CodeAgentEvent(
                run_id=run.run_id,
                kind="started",
                phase="starting",
                message="Codex run is starting.",
                data={
                    "provider": self.name,
                    "mode": agent_settings.mode,
                    "model": self._effective_model(agent_settings),
                    "reasoning": self._effective_reasoning(agent_settings),
                },
            ),
        )

        before_sessions = _read_session_index()
        command = self._build_command(
            session_id=conversation.agent_session_id,
            result_path=result_path,
            agent_settings=agent_settings,
            runtime=runtime,
        )
        mode = "resume" if conversation.agent_session_id else "new"
        log.stage(
            "Running Codex CLI: "
            f"mode={mode}, sandbox={self._effective_sandbox(runtime)}, "
            f"timeout={self._effective_timeout(runtime)}s"
        )
        log.event(
            "Code agent artifacts: "
            f"stdout={stdout_path}, stderr={stderr_path}, result={result_path}"
        )

        try:
            stdout, returncode = self._run_streaming_process(
                command=command,
                prompt=prompt,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                timeout_seconds=self._effective_timeout(runtime),
                sink=sink,
                run_id=run.run_id,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = _timeout_output(exc)
            error = f"Codex timed out after {self._effective_timeout(runtime)}s"
            self.store.mark_run_failed(run.run_id, error)
            log.fail(error)
            _emit_agent_event(
                sink,
                CodeAgentEvent(
                    run_id=run.run_id,
                    kind="error",
                    phase="timeout",
                    message=error,
                    data={"stdout_tail": stdout[-2000:]},
                ),
            )
            return CodeAgentResult(
                run_id=run.run_id,
                status="failed",
                response_text=error,
                session_id=conversation.agent_session_id,
                result_path=result_path,
            )

        stderr = _read_text_if_exists(stderr_path)
        log.event(f"Codex CLI exited: code={returncode}")

        if returncode != 0:
            error = _summarize_failure(stderr, stdout)
            self.store.mark_run_failed(run.run_id, error)
            log.fail(f"Codex CLI failed: run={run.run_id}")
            _emit_agent_event(
                sink,
                CodeAgentEvent(
                    run_id=run.run_id,
                    kind="error",
                    phase="failed",
                    message=error,
                    data={"returncode": returncode},
                ),
            )
            return CodeAgentResult(
                run_id=run.run_id,
                status="failed",
                response_text=error,
                session_id=conversation.agent_session_id,
                result_path=result_path,
            )

        session_id = conversation.agent_session_id or _detect_new_session_id(
            before_sessions=before_sessions,
            stdout=stdout,
        )
        response_text = _read_result_text(result_path, stdout)
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
        _emit_agent_event(
            sink,
            CodeAgentEvent(
                run_id=run.run_id,
                kind="final",
                phase="finished",
                message=_shorten(response_text, 1200),
                data={
                    "status": "succeeded",
                    "session_id": session_id,
                    "result_path": str(result_path),
                },
            ),
        )
        return CodeAgentResult(
            run_id=run.run_id,
            status="succeeded",
            response_text=response_text,
            session_id=session_id,
            result_path=result_path,
        )

    def _run_streaming_process(
        self,
        *,
        command: list[str],
        prompt: str,
        stdout_path: Path,
        stderr_path: Path,
        timeout_seconds: int,
        sink: CodeAgentEventSink,
        run_id: str,
    ) -> tuple[str, int]:
        stdout_lines: list[str] = []
        with (
            stdout_path.open("w", encoding="utf-8") as stdout_file,
            stderr_path.open("w", encoding="utf-8") as stderr_file,
        ):
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=stderr_file,
                text=True,
                cwd=self.repo_root,
                bufsize=1,
            )
            if process.stdin is None or process.stdout is None:
                raise RuntimeError("Codex process streams were not created")
            process.stdin.write(prompt)
            process.stdin.close()

            lines: queue.Queue[str | None] = queue.Queue()

            def read_stdout() -> None:
                try:
                    for line in process.stdout:
                        lines.put(line)
                finally:
                    lines.put(None)

            reader = threading.Thread(
                target=read_stdout,
                name=f"codex-stdout-{run_id[:8]}",
                daemon=True,
            )
            reader.start()

            deadline = time.monotonic() + timeout_seconds
            stdout_done = False
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    _kill_process(process)
                    raise subprocess.TimeoutExpired(
                        command,
                        timeout_seconds,
                        output="".join(stdout_lines),
                    )

                try:
                    line = lines.get(timeout=min(0.2, max(0.01, remaining)))
                except queue.Empty:
                    if stdout_done and process.poll() is not None:
                        break
                    continue

                if line is None:
                    stdout_done = True
                else:
                    stdout_file.write(line)
                    stdout_file.flush()
                    stdout_lines.append(line)
                    event = _codex_json_line_to_agent_event(run_id, line)
                    if event is not None:
                        _emit_agent_event(sink, event)

                if stdout_done and process.poll() is not None:
                    break

            returncode = process.wait(timeout=1)
            reader.join(timeout=1)
        return "".join(stdout_lines), returncode

    def _build_command(
        self,
        *,
        session_id: str | None,
        result_path: Path,
        agent_settings: CodeAgentSettings,
        runtime: Any,
    ) -> list[str]:
        command = [self.settings.codex.bin, "exec"]
        if session_id:
            command.extend(["resume", "--json", "-o", str(result_path)])
            self._append_runtime_options(command, agent_settings)
            command.extend([session_id, "-"])
            return command

        command.extend(
            [
                "--json",
                "-C",
                str(self.repo_root),
                "-s",
                self._effective_sandbox(runtime),
                "-o",
                str(result_path),
            ]
        )
        self._append_runtime_options(command, agent_settings)
        command.append("-")
        return command

    def _append_runtime_options(
        self,
        command: list[str],
        agent_settings: CodeAgentSettings,
    ) -> None:
        model = self._effective_model(agent_settings)
        if model:
            command.extend(["-m", model])
        reasoning = self._effective_reasoning(agent_settings)
        if reasoning:
            command.extend(["-c", f'model_reasoning_effort="{reasoning}"'])

    def _effective_model(self, agent_settings: CodeAgentSettings) -> str | None:
        return agent_settings.model or self.settings.codex.model

    def _effective_reasoning(self, agent_settings: CodeAgentSettings) -> str | None:
        if agent_settings.reasoning_effort:
            return agent_settings.reasoning_effort
        return {
            "fast": "low",
            "standard": "medium",
            "deep": "high",
        }.get(agent_settings.mode)

    def _effective_sandbox(self, runtime: Any) -> str:
        return runtime.codex.sandbox or self.settings.codex.sandbox

    def _effective_timeout(self, runtime: Any) -> int:
        return runtime.codex.timeout_seconds or self.settings.codex.timeout_seconds

    def _build_prompt(
        self,
        *,
        run: RunRecord,
        plan: TaskPlan,
        run_dir: Path,
        runtime: Any,
        agent_settings: CodeAgentSettings,
    ) -> str:
        capabilities = render_capabilities(plan.capability_names)
        recent = self.store.recent_runs(conversation_id=run.conversation_id, limit=5)
        recent_lines = [
            f"- {item.created_at} [{item.intent}/{item.status}] {item.user_text[:80]}"
            for item in recent
            if item.run_id != run.run_id
        ]
        recent_text = "\n".join(recent_lines) or "- none"

        return f"""# PkuClaw Code Agent Task

You are being invoked by the PkuClaw backend core loop, not directly by a chat user.

## Code Agent

{self.name}

## Selected Intent

{plan.intent}

## Code Agent Settings

- Provider: `{agent_settings.provider}`
- Mode: `{agent_settings.mode}`
- Model: `{self._effective_model(agent_settings) or "default"}`
- Reasoning effort: `{self._effective_reasoning(agent_settings) or "default"}`
- Runtime config: `{runtime.path}`

## Available Runtime Facts

- Repository root: `{self.repo_root}`
- Run directory: `{run_dir}`
- Teaching snapshots directory: `{self.settings.app.data_dir / "snapshots"}`
- Feishu/Web/WeChat I/O is owned by channel adapters, not by this code agent.
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


def _emit_agent_event(
    sink: CodeAgentEventSink,
    event: CodeAgentEvent,
) -> None:
    try:
        sink.emit(event)
    except Exception as exc:  # pragma: no cover - defensive channel isolation
        log.warn(f"code-agent event sink failed: {exc}")


def _codex_json_line_to_agent_event(
    run_id: str,
    line: str,
) -> CodeAgentEvent | None:
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        text = line.strip()
        if not text:
            return None
        return CodeAgentEvent(
            run_id=run_id,
            kind="output",
            phase="output",
            message=_shorten(text, 500),
            data={},
        )
    if not isinstance(data, dict):
        return None

    event_type = str(
        data.get("type")
        or data.get("event")
        or data.get("kind")
        or "codex_event"
    )
    phase = _phase_from_codex_event_type(event_type)
    command = _find_key_recursive(data, {"command"})
    if isinstance(command, str) and command.strip():
        return CodeAgentEvent(
            run_id=run_id,
            kind="progress",
            phase="command",
            message=f"执行命令：{_shorten(command.strip(), 180)}",
            data={"codex_type": event_type},
        )

    tool_name = _find_key_recursive(data, {"tool_name", "toolName", "name"})
    if isinstance(tool_name, str) and "tool" in event_type.lower():
        return CodeAgentEvent(
            run_id=run_id,
            kind="progress",
            phase="tool",
            message=f"调用工具：{_shorten(tool_name.strip(), 120)}",
            data={"codex_type": event_type},
        )

    text = _find_key_recursive(data, {"text", "message", "content"})
    if isinstance(text, str) and text.strip():
        kind = "output" if phase == "output" else "progress"
        return CodeAgentEvent(
            run_id=run_id,
            kind=kind,
            phase=phase,
            message=_shorten(text.strip(), 500),
            data={"codex_type": event_type},
        )

    message = {
        "session_configured": "Codex session configured.",
        "turn_started": "Codex started a turn.",
        "turn_completed": "Codex completed a turn.",
    }.get(event_type, f"Codex event: {event_type}")
    return CodeAgentEvent(
        run_id=run_id,
        kind="progress",
        phase=phase,
        message=message,
        data={"codex_type": event_type},
    )


def _phase_from_codex_event_type(event_type: str) -> str:
    lowered = event_type.lower()
    if "session" in lowered:
        return "session"
    if "command" in lowered or "exec" in lowered:
        return "command"
    if "tool" in lowered:
        return "tool"
    if "message" in lowered or "output" in lowered or "text" in lowered:
        return "output"
    if "completed" in lowered or "finished" in lowered:
        return "finished"
    return "running"


def _timeout_output(exc: subprocess.TimeoutExpired) -> str:
    output = getattr(exc, "stdout", None) or getattr(exc, "output", None) or ""
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return str(output)


def _read_text_if_exists(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _kill_process(process: subprocess.Popen[str]) -> None:
    try:
        process.kill()
    except Exception:
        return


def _shorten(text: str, limit: int) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip() + "..."


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
    return (
        _last_text_from_jsonl(stdout)
        or stdout.strip()
        or "Codex completed with no output."
    )


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
