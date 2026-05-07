"""构建并发送飞书侧运行详情卡。"""
from __future__ import annotations

from typing import Any

from pkuclaw.agents.artifacts import build_codex_artifact_detail
from pkuclaw.config import Settings
from pkuclaw.core import logging as log
from pkuclaw.core.runtime import CoreRuntime

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
    """通过统一 run detail helper 生成运行详情卡 JSON。"""
    detail = build_codex_artifact_detail(
        store=core_runtime.store,
        run_id=run_id,
    )
    return renderer.run_detail_card(
        run_id=run_id,
        status=detail.run.status,
        elapsed=detail.elapsed,
        agent_context=detail.agent_context,
        paths=detail.paths,
        artifact_summary=detail.artifact_summary,
        events=detail.events,
        page=page,
    )
