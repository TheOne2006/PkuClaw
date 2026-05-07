"""Codex CLI provider：启动 codex exec、归一化事件并读取结果。"""
from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from pkuclaw.agents.base import AgentRunContext
from pkuclaw.config import Settings
from pkuclaw.core import logging as log
from pkuclaw.core.models import (
    DEFAULT_AGENT_MODEL,
    DEFAULT_AGENT_REASONING_EFFORT,
    AgentEvent,
    AgentEventSink,
    AgentResult,
    AgentSettings,
)


CODEX_APPROVAL_REVIEWER = "auto_review"
CODEX_MCP_DEFAULT_TOOLS_APPROVAL_MODE = "approve"


class CodexAgent:
    """通过 codex exec --json 执行 PkuClaw prompt 的 Agent provider。"""
    name = "codex"

    def __init__(
        self,
        *,
        settings: Settings,
        repo_root: Path | None = None,
    ) -> None:
        self.settings = settings
        self.repo_root = (repo_root or Path.cwd()).resolve()

    def execute(
        self,
        context: AgentRunContext,
        prompt: str,
        sink: AgentEventSink,
    ) -> AgentResult:
        """执行一次 Codex run，处理启动事件、CLI 返回码、结果文件和 session id。"""
        run = context.run
        agent_settings = context.agent_settings
        paths = context.paths
        log.event(
            "codex agent context: "
            f"agent={self.name}, run={run.run_id}, source={context.request.source}, "
            f"mode={agent_settings.mode}, "
            f"model={self._effective_model(agent_settings) or 'default'}, "
            "reasoning="
            f"{self._effective_reasoning(agent_settings) or 'default'}, "
            f"existing_thread={context.conversation.agent_session_id or 'none'}"
        )
        _emit_agent_event(
            sink,
            AgentEvent(
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

        # Codex may create a new thread without printing its id directly; keep a
        # before/after snapshot so we can persist the session id for later resume.
        before_sessions = _read_session_index()
        command = self._build_command(
            session_id=context.conversation.agent_session_id,
            result_path=paths.result_path,
            agent_settings=agent_settings,
            runtime=context.runtime,
            enable_mcp=context.request.source == "loop",
        )
        mode = "resume" if context.conversation.agent_session_id else "new"
        log.stage(
            "Running Codex CLI: "
            f"mode={mode}, sandbox={self._effective_sandbox(context.runtime)}, "
            f"timeout={self._effective_timeout(context.runtime)}s"
        )
        log.event(
            "Codex artifacts: "
            f"stdout={paths.stdout_path}, stderr={paths.stderr_path}, "
            f"result={paths.result_path}"
        )

        try:
            stdout, returncode = self._run_streaming_process(
                command=command,
                prompt=prompt,
                stdout_path=paths.stdout_path,
                stderr_path=paths.stderr_path,
                timeout_seconds=self._effective_timeout(context.runtime),
                sink=sink,
                run_id=run.run_id,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = _timeout_output(exc)
            error = f"Codex timed out after {self._effective_timeout(context.runtime)}s"
            log.fail(error)
            _emit_agent_event(
                sink,
                AgentEvent(
                    run_id=run.run_id,
                    kind="error",
                    phase="timeout",
                    message=error,
                    data={"stdout_tail": stdout[-2000:]},
                ),
            )
            return AgentResult(
                run_id=run.run_id,
                status="failed",
                response_text=error,
                session_id=context.conversation.agent_session_id,
                result_path=paths.result_path,
                error=error,
            )

        stderr = _read_text_if_exists(paths.stderr_path)
        log.event(f"Codex CLI exited: code={returncode}")

        if returncode != 0:
            error = _summarize_failure(stderr, stdout)
            log.fail(f"Codex CLI failed: run={run.run_id}")
            _emit_agent_event(
                sink,
                AgentEvent(
                    run_id=run.run_id,
                    kind="error",
                    phase="failed",
                    message=error,
                    data={"returncode": returncode},
                ),
            )
            return AgentResult(
                run_id=run.run_id,
                status="failed",
                response_text=error,
                session_id=context.conversation.agent_session_id,
                result_path=paths.result_path,
                error=error,
            )

        session_id = context.conversation.agent_session_id or _detect_new_session_id(
            before_sessions=before_sessions,
            stdout=stdout,
        )
        # Prefer the explicit result file written by `codex exec -o`; stdout is
        # only a fallback for older/partial CLI event streams.
        response_text = _read_result_text(paths.result_path, stdout)
        if session_id:
            log.ok(f"Codex thread ready: {session_id}")
        else:
            log.warn(
                "Codex thread id was not detected; next message will start a new thread"
            )
        log.ok(f"Codex result loaded: {paths.result_path} ({len(response_text)} chars)")
        _emit_agent_event(
            sink,
            AgentEvent(
                run_id=run.run_id,
                kind="final",
                phase="finished",
                message=_truncate_markdown(response_text, 2500),
                data={
                    "status": "succeeded",
                    "session_id": session_id,
                    "result_path": str(paths.result_path),
                },
            ),
        )
        return AgentResult(
            run_id=run.run_id,
            status="succeeded",
            response_text=response_text,
            session_id=session_id,
            result_path=paths.result_path,
        )

    def _run_streaming_process(
        self,
        *,
        command: list[str],
        prompt: str,
        stdout_path: Path,
        stderr_path: Path,
        timeout_seconds: int,
        sink: AgentEventSink,
        run_id: str,
    ) -> tuple[str, int]:
        """启动 Codex CLI 并实时消费 stdout JSONL，转发为 AgentEvent。"""
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

            # stdout is consumed on a reader thread because the main loop also
            # enforces the overall timeout and forwards events to the sink.
            lines: queue.Queue[str | None] = queue.Queue()

            def read_stdout() -> None:
                """在后台线程中读取子进程 stdout，并用 None 标记流结束。"""
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
                    # Persist each Codex JSONL line verbatim first, then normalize
                    # it into a channel-neutral AgentEvent for UI sinks.
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
        agent_settings: AgentSettings,
        runtime: Any,
        enable_mcp: bool,
    ) -> list[str]:
        """根据是否已有 session 拼出 codex exec/resume 命令行。"""
        command = [self.settings.codex.bin, "exec"]
        if session_id:
            command.extend(["resume", "--json", "-o", str(result_path)])
            self._append_runtime_options(command, agent_settings)
            if enable_mcp:
                self._append_mcp_server(command)
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
        if enable_mcp:
            self._append_mcp_server(command)
        command.append("-")
        return command

    def _append_runtime_options(
        self,
        command: list[str],
        agent_settings: AgentSettings,
    ) -> None:
        """把固定 model、reasoning 和 auto-review 选项追加到 Codex 命令行。"""
        model = self._effective_model(agent_settings)
        if model:
            command.extend(["-m", model])
        reasoning = self._effective_reasoning(agent_settings)
        if reasoning:
            command.extend(["-c", f'model_reasoning_effort="{reasoning}"'])
        command.extend(
            [
                "-c",
                f'approvals_reviewer="{CODEX_APPROVAL_REVIEWER}"',
            ]
        )

    def _append_mcp_server(self, command: list[str]) -> None:
        """Expose channel notification tools to loop runs."""
        url = f"http://{self.settings.mcp.host}:{self.settings.mcp.port}/mcp"
        command.extend(
            [
                "-c",
                f'mcp_servers.pkuclaw_daemon.url="{url}"',
                "-c",
                (
                    "mcp_servers.pkuclaw_daemon.default_tools_approval_mode="
                    f'"{CODEX_MCP_DEFAULT_TOOLS_APPROVAL_MODE}"'
                ),
            ]
        )

    def _effective_model(self, agent_settings: AgentSettings) -> str | None:
        """合并会话/runtime 和启动配置后的 Codex model。"""
        return agent_settings.model or self.settings.codex.model or DEFAULT_AGENT_MODEL

    def _effective_reasoning(self, agent_settings: AgentSettings) -> str | None:
        """返回固定默认的 Codex reasoning effort，忽略旧 mode preset。"""
        return agent_settings.reasoning_effort or DEFAULT_AGENT_REASONING_EFFORT

    def _effective_sandbox(self, runtime: Any) -> str:
        """合并 runtime 和启动配置后的 Codex sandbox。"""
        return runtime.codex.sandbox or self.settings.codex.sandbox

    def _effective_timeout(self, runtime: Any) -> int:
        """合并 runtime 和启动配置后的 Codex 超时时间。"""
        return runtime.codex.timeout_seconds or self.settings.codex.timeout_seconds



def _read_session_index() -> list[dict[str, Any]]:
    """读取 Codex 本地 session_index.jsonl，无法读取时返回空列表。"""
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
    sink: AgentEventSink,
    event: AgentEvent,
) -> None:
    """隔离 channel sink 异常，避免 UI 更新失败打断 provider。"""
    try:
        sink.emit(event)
    except Exception as exc:  # pragma: no cover - defensive channel isolation
        log.warn(f"agent event sink failed: {exc}")


def _codex_json_line_to_agent_event(
    run_id: str,
    line: str,
) -> AgentEvent | None:
    """把 Codex JSONL 事件归一化为 PkuClaw AgentEvent。"""
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        text = line.strip()
        if not text:
            return None
        return AgentEvent(
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
    item_type = _codex_item_type(data)
    phase = _phase_from_codex_event_type(event_type, item_type=item_type)
    command = _find_key_recursive(data, {"command"})
    if isinstance(command, str) and command.strip():
        return AgentEvent(
            run_id=run_id,
            kind="progress",
            phase="command",
            message=f"执行命令：{_shorten(command.strip(), 180)}",
            data={"codex_type": event_type},
        )

    tool_name = _find_key_recursive(data, {"tool_name", "toolName", "name"})
    if isinstance(tool_name, str) and "tool" in event_type.lower():
        return AgentEvent(
            run_id=run_id,
            kind="progress",
            phase="tool",
            message=f"调用工具：{_shorten(tool_name.strip(), 120)}",
            data={"codex_type": event_type},
        )

    text = _find_key_recursive(data, {"delta", "text", "message", "content"})
    if isinstance(text, str) and text.strip():
        kind = "output" if _is_codex_assistant_output(event_type, item_type) else "progress"
        message = (
            _truncate_output_text(
                text,
                1200,
                preserve_edges="delta" in event_type.lower(),
            )
            if kind == "output"
            else _shorten(text.strip(), 500)
        )
        return AgentEvent(
            run_id=run_id,
            kind=kind,
            phase=phase,
            message=message,
            data={"codex_type": event_type},
        )

    message = {
        "session_configured": "Codex session configured.",
        "turn_started": "Codex started a turn.",
        "turn_completed": "Codex completed a turn.",
    }.get(event_type, f"Codex event: {event_type}")
    return AgentEvent(
        run_id=run_id,
        kind="progress",
        phase=phase,
        message=message,
        data={"codex_type": event_type},
    )


def _codex_item_type(data: dict[str, Any]) -> str:
    """从 Codex event 的 item 字段提取 item type。"""
    item = data.get("item")
    if not isinstance(item, dict):
        return ""
    return str(item.get("type") or "")


def _is_codex_assistant_output(event_type: str, item_type: str) -> bool:
    """判断 Codex 事件是否应视为 assistant 输出。"""
    lowered_event = event_type.lower()
    lowered_item = item_type.lower()
    return (
        "agent_message" in lowered_event
        or lowered_item == "agent_message"
        or "assistant_message" in lowered_event
        or lowered_item == "assistant_message"
        or "output" in lowered_event
        or "text" in lowered_event
    )


def _phase_from_codex_event_type(event_type: str, *, item_type: str = "") -> str:
    """把 Codex event/item 类型映射成 PkuClaw phase。"""
    lowered_item = item_type.lower()
    if lowered_item == "agent_message":
        return "output"
    if lowered_item == "command_execution":
        return "command"
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
    """从 TimeoutExpired 中提取 stdout/output 文本。"""
    output = getattr(exc, "stdout", None) or getattr(exc, "output", None) or ""
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return str(output)


def _read_text_if_exists(path: Path) -> str:
    """读取文本文件；文件不存在时返回空字符串。"""
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _kill_process(process: subprocess.Popen[str]) -> None:
    """尽力终止子进程，忽略终止过程中的异常。"""
    try:
        process.kill()
    except Exception:
        return


def _shorten(text: str, limit: int) -> str:
    """压缩空白并截断为单行短文本。"""
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip() + "..."


def _truncate_markdown(text: str, limit: int) -> str:
    """截断 Markdown 正文，适合 channel 卡片展示。"""
    content = text.strip()
    if len(content) <= limit:
        return content
    return content[:limit].rstrip() + "\n..."


def _truncate_output_text(text: str, limit: int, *, preserve_edges: bool) -> str:
    """根据是否 delta 事件决定是否保留边缘空白后截断输出。"""
    content = text if preserve_edges else text.strip()
    if len(content) <= limit:
        return content
    return content[:limit].rstrip() + "\n..."


def _detect_new_session_id(
    *,
    before_sessions: list[dict[str, Any]],
    stdout: str,
) -> str | None:
    """比较执行前后的 Codex session index，并回退扫描 stdout。"""
    before_ids = {item.get("id") for item in before_sessions}
    after_sessions = _read_session_index()
    new_sessions = [item for item in after_sessions if item.get("id") not in before_ids]
    if new_sessions:
        return str(new_sessions[-1].get("id"))
    return _find_session_id_in_jsonl(stdout)


def _find_session_id_in_jsonl(stdout: str) -> str | None:
    """从 Codex stdout JSONL 中查找 session/thread id。"""
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
    """在嵌套 dict/list 中深度查找任一候选键。"""
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
    """优先读取 result.md，缺失时从 stdout 中提取最后文本。"""
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
    """扫描 JSONL 并返回最后一段文本字段。"""
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
    """从 stderr/stdout 中截取失败摘要。"""
    combined = (stderr.strip() or stdout.strip() or "Codex failed with no output.")
    return combined[-2000:]
