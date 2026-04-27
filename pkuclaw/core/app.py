from __future__ import annotations

from pkuclaw.backbone.teaching import TeachingBackbone
from pkuclaw.core import logging as log
from pkuclaw.core.control import mode_label, parse_control_command
from pkuclaw.core.models import ChannelMessage, CoreDispatch, TaskPlan, WorkerResult
from pkuclaw.core.router import classify_message
from pkuclaw.core.store import Store
from pkuclaw.workers.codex import CodexWorker


class CoreLoop:
    """Shared application loop used by Feishu, future web, and future WeChat."""

    def __init__(
        self,
        *,
        store: Store,
        codex_worker: CodexWorker,
        teaching_backbone: TeachingBackbone | None = None,
    ) -> None:
        self.store = store
        self.codex_worker = codex_worker
        self.teaching_backbone = teaching_backbone

    def ingest(self, message: ChannelMessage) -> CoreDispatch:
        command = parse_control_command(text=message.text, event_key=message.event_key)
        if command is not None:
            reply = self._handle_control(
                conversation_id=message.conversation_id,
                kind=command.kind,
                value=command.value,
            )
            return CoreDispatch(reply_text=reply, handled_locally=True)

        plan = classify_message(message.text)
        run = self.store.create_run(
            conversation_id=message.conversation_id,
            user_text=message.text,
            intent=plan.intent,
            metadata={
                "channel": message.channel,
                "sender_id": message.sender_id,
                "capability_names": list(plan.capability_names),
            },
        )
        log.event(
            "core dispatch: "
            f"conversation={_short_id(message.conversation_id)}, "
            f"run={run.run_id}, intent={plan.intent}, "
            f"capabilities={','.join(plan.capability_names) or 'base'}"
        )
        return CoreDispatch(
            reply_text=f"{plan.ack}\n\nrun_id: `{run.run_id}`",
            run_id=run.run_id,
            plan=plan,
        )

    def run_worker(self, run_id: str, plan: TaskPlan) -> WorkerResult:
        run = self.store.get_run(run_id)
        return self.codex_worker.run(run, plan)

    def collect_teaching_snapshot(self) -> str:
        if self.teaching_backbone is None:
            raise RuntimeError("teaching backbone is not configured")
        snapshot = self.teaching_backbone.collect_snapshot()
        return f"教学网快照已更新：`{snapshot.path}`"

    def _handle_control(
        self,
        *,
        conversation_id: str,
        kind: str,
        value: str | None,
    ) -> str:
        if kind == "set_mode":
            if value is None:
                raise RuntimeError("mode value is required")
            conversation = self.store.set_conversation_mode(conversation_id, value)
            log.ok(
                "mode switched: "
                f"conversation={_short_id(conversation_id)}, mode={conversation.mode}"
            )
            return f"已切换到 {mode_label(conversation.mode)} 模式。"

        if kind == "status":
            conversation = self.store.ensure_conversation(conversation_id)
            counts = self.store.counts_by_status()
            status_text = ", ".join(
                f"{name}={count}" for name, count in sorted(counts.items())
            )
            return (
                f"当前模式：{mode_label(conversation.mode)}\n"
                f"Codex thread：{conversation.codex_session_id or '无'}\n"
                f"任务统计：{status_text or '暂无任务'}"
            )

        if kind == "recent_runs":
            recent = self.store.recent_runs(conversation_id=conversation_id, limit=5)
            if not recent:
                return "最近没有任务。"
            lines = [
                (
                    f"- {run.run_id[:8]} [{run.intent}/{run.status}] "
                    f"{' '.join(run.user_text.split())[:40]}"
                )
                for run in recent
            ]
            return "最近任务：\n" + "\n".join(lines)

        raise RuntimeError(f"unknown control command: {kind}")


def _short_id(value: str) -> str:
    if len(value) <= 12:
        return value
    return f"{value[:6]}...{value[-4:]}"
