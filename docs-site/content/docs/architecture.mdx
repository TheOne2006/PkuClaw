---
title: 架构说明
description: PkuClaw 的核心模块、运行链路和目录结构。
---

PkuClaw 使用 daemon-centered runtime model：两类 Agent run、可编辑 runtime 文件、catalog-based skills，以及一条本地 channel outbox 队列。

## 核心链路

```text
User / Channel Event
        |
        v
  Channel Adapter
        |
        v
    CoreRuntime  <------ LoopManager
        |
        v
   AgentWrapper
        |
        v
  Agent Provider
        |
        +--> realtime response
        |
        +--> channel outbox queue --> daemon worker --> channel backend
```

## 模块划分

```text
pkuclaw/
  core/         # CoreRuntime、LoopManager、共享模型、Store
  runtime/      # configs/runtime/* 的热读 loader
  agents/       # AgentWrapper、sink、artifact、providers/codex.py
  channels/     # Feishu 等平台 adapter
  notify_queue/ # daemon 文件通知队列 worker
scripts/        # channel outbox queue CLI
configs/runtime/
  runtime.json
  events.json
  prompts.json
  skills.json
  skills/
```

## CoreRuntime

`CoreRuntime` 是 realtime 和 loop run 的入口。它不做自然语言分类，只接收明确的请求来源：

- 用户消息；
- quick action event id；
- LoopManager tick。

## AgentWrapper

`AgentWrapper` 负责：

1. 创建 run record；
2. 热读取 runtime config、events、prompts、skills；
3. 构建 prompt；
4. 选择 provider；
5. 持久化运行结果和 artifact 路径。

## LoopManager

`LoopManager` 热加载 `configs/runtime/runtime.json`，调度 enabled loop，并创建 `source = loop` run。

Loop prompt 要求：

- 没有重要变化时保持静默；
- 有重要变化时使用 Channel Outbox Skill；
- loop final answer 主要用于日志和 artifacts，不直接展示给用户。

## Channel outbox

Outbox 的目的不是替代 channel backend，而是给 Agent 一个最小、可审计、channel-neutral 的投递界面。

```text
Agent -> scripts/pkuclaw_outbox.py -> data/notify_queue/* -> daemon worker -> CoreRuntime -> Feishu/backend
```

## 设计约束

- 不新增第三类 run source。
- 不把 runtime 管理做成 MCP 工具层。
- 不在 prompt 中注入完整 skill markdown body。
- 不让脚本直连飞书或解析 target id。
- 不再使用 `sub-skills/` 作为 runtime skill source。
