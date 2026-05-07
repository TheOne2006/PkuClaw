"""构建并发送飞书侧运行详情卡。"""
from __future__ import annotations

from typing import Any

from pkuclaw.code_agents.artifacts import build_codex_artifact_detail
from pkuclaw.config import Settings
from pkuclaw.core import logging as log
from pkuclaw.core.app import CoreRuntime
from pkuclaw.core.models import merge_agent_settings

from .cards import FeishuCardKitClient, FeishuCardRenderer
from .ids import short_id


def send_run_detail_card(
    settings: Settings,
    core_runtime: CoreRuntime,
    renderer: FeishuCardRenderer,
    message_client: FeishuCardKitClient,
    receive_id_type: str,
    receive_id: str,
    run_id: str,
    page: int,
) -> None:
    """构建运行详情卡并异步发送到飞书目标。"""
    try:
        detail_card = build_run_detail_card(
            settings=settings,
            core_runtime=core_runtime,
            renderer=renderer,
            run_id=run_id,
            page=page,
        )
        message_client.send_card(
            receive_id_type=receive_id_type,
            receive_id=receive_id,
            card=detail_card,
        )
    except Exception as exc:
        log.fail(f"failed to send run detail card: run={run_id}, error={exc}")
        return
    log.ok(
        "run detail card sent: "
        f"run={run_id}, page={page}, target={short_id(receive_id)}"
    )


def build_run_detail_card(
    *,
    settings: Settings,
    core_runtime: CoreRuntime,
    renderer: FeishuCardRenderer,
    run_id: str,
    page: int,
) -> dict[str, Any]:
    """读取 Store 和 Codex artifacts，生成运行详情卡 JSON。"""
    run = core_runtime.store.get_run(run_id)
    detail = build_codex_artifact_detail(data_dir=settings.app.data_dir, run=run)
    return renderer.run_detail_card(
        run_id=run_id,
        status=run.status,
        elapsed=detail.elapsed,
        agent_context=agent_context(core_runtime, run.conversation_id),
        artifacts=detail.artifacts,
        events=detail.events,
        page=page,
    )


def agent_context(core_runtime: CoreRuntime, conversation_id: str) -> dict[str, str]:
    """合并 runtime 和会话覆盖，生成详情卡展示用的 Agent 设置。"""
    conversation = core_runtime.store.ensure_conversation(conversation_id)
    runtime = core_runtime.runtime_config.read_snapshot()
    settings = merge_agent_settings(runtime.agent, conversation.agent_settings)
    mode = settings.mode or "standard"
    return {
        "provider": settings.provider or "codex",
        "mode": mode,
        "model": settings.model or "默认",
        "reasoning": settings.reasoning_effort or "默认",
    }
