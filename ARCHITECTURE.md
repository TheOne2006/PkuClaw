# PkuClaw High-Level Architecture

This document describes the intended high-level architecture of PkuClaw.

PkuClaw is a daemon-centered agent runtime for PKU study workflows. It is not a
pku3b wrapper, not only a Feishu bot, and not a Codex-only project. The daemon
stays online, receives realtime messages, triggers periodic loop work, exposes
channel MCP tools, and delegates real work to agents through the Agent-Wrapper.

## System Shape

```text
PkuClaw Daemon
  |
  +-- Realtime Thread
  |     Feishu / future Web / future WeChat
  |     -> Agent-Wrapper
  |     -> Agent streaming reply
  |
  +-- Loop Thread
  |     timer only
  |     -> Agent-Wrapper
  |     -> Agent periodic update
  |
  +-- MCP Server Thread
        generic channel tools
        -> current implementation sends through Feishu

Agent-Wrapper
  -> hot-load runtime JSON config
  -> build run prompt
  -> inject prompt fragments / skills / tool docs
  -> choose model / reasoning / fast mode
  -> start or resume concrete Agent
  -> normalize events / artifacts / results

Agent
  -> Codex first
  -> future Claude Code / Kimi Code

Skill Docs
  -> pku3b usage
  -> workflow instructions
  -> tool/path conventions
```

## Core Components

`Daemon` is the always-online parent process. It owns process lifecycle, channel
connections, timing, queues, thread locks, store access, logging, and the MCP
server. Its expected shape is three main threads: realtime, loop, and MCP
server.

`Realtime Thread` receives user messages from channels such as Feishu. It does
not own business logic. It forwards messages to Agent-Wrapper and renders
streaming agent output back to the user.

`Loop Thread` is intentionally simple. It only wakes up on an interval and asks
Agent-Wrapper to run the configured loop prompt. Course checking and state
updates are agent work, not loop-thread logic.

`MCP Server Thread` exposes generic channel tools to agents. The interface
should stay channel-neutral, even if the first implementation sends through
Feishu.

`Agent-Wrapper` is the central orchestration layer inside the daemon. It prepares
the run prompt, hot-loads runtime config and prompt fragments, injects skills and
tool instructions, selects the concrete agent, starts or resumes it, receives
events, and writes artifacts.

`Agent` is the real worker. Codex is the first implementation, but the
architecture should allow future Claude Code or Kimi Code agents without
changing daemon-level concepts.

`pku3b` is an external CLI tool. It is not wrapped as an MCP tool in the first
design. Agents learn how to use it through skill documents and call it directly
when needed.

## Runtime Config

Most behavior belongs to Agent-Wrapper runtime config, loaded live from JSON
before each run.

Runtime config includes provider selection, model, reasoning level, Codex
fast/standard/deep mode, sandbox, timeout, loop interval, loop prompt, prompt
fragments, default skills, and notification policy.

Agent-Wrapper also loads prompt fragments and skill documents at run time. This
lets an agent modify configuration or prompt files and have changes affect the
next realtime run or loop tick without restarting the daemon.

If runtime JSON is invalid or missing, Agent-Wrapper should fall back to the last
valid config or defaults, and the fallback warning must be visible in logs and
run metadata.

## MCP Tool Boundary

MCP Tools are channel-action tools, not daemon-management tools.

First useful tools:

- `channel_send_text`
- `channel_send_card`
- `channel_send_image`
- `channel_update_card`

These are generic names. The first backend is Feishu, but future Web or WeChat
adapters should fit the same tool surface.

Not MCP Tools in this architecture:

- runtime config get/set
- run current/status/progress
- pku3b_run

Runtime and run context are injected by Agent-Wrapper. pku3b is exposed through
skill documentation.

## Execution Flow

For realtime messages, the channel adapter receives a user message, the daemon
creates a run, Agent-Wrapper builds a prompt, the concrete agent streams events,
and the realtime thread renders those events back to the user.

For loop work, the loop thread wakes up, sends the configured loop prompt to
Agent-Wrapper, the agent checks state and updates files, and it stays silent
unless it decides an important notification should be sent through channel MCP
tools.

## Design Rule

PkuClaw core should stay thin and durable. Business intelligence belongs in
Agent behavior, prompt construction, skills, and tools. The daemon provides
stable runtime structure; Agent-Wrapper turns context into agent work; agents do
the actual work.

---

# PkuClaw 高层架构

本文档描述 PkuClaw 的目标高层架构。

PkuClaw 是一个围绕 daemon 运行的 agent runtime，用来承载北大学习场景里的
即时问答、周期检查和工具调用。它不是 pku3b 的 Python wrapper，不只是飞书
机器人，也不是 Codex 专属项目。Daemon 常驻在线，接收即时消息，触发周期
loop，暴露 channel MCP tools，并通过 Agent-Wrapper 把真实工作交给 Agent。

## 系统形态

```text
PkuClaw Daemon
  |
  +-- Realtime Thread
  |     Feishu / future Web / future WeChat
  |     -> Agent-Wrapper
  |     -> Agent streaming reply
  |
  +-- Loop Thread
  |     timer only
  |     -> Agent-Wrapper
  |     -> Agent periodic update
  |
  +-- MCP Server Thread
        generic channel tools
        -> current implementation sends through Feishu

Agent-Wrapper
  -> 实时读取 runtime JSON config
  -> 拼凑 run prompt
  -> 注入 prompt fragments / skills / tool docs
  -> 选择 model / reasoning / fast mode
  -> 启动或恢复具体 Agent
  -> 归一化 events / artifacts / results

Agent
  -> Codex first
  -> future Claude Code / Kimi Code

Skill Docs
  -> pku3b usage
  -> workflow instructions
  -> tool/path conventions
```

## 核心组件

`Daemon` 是全程在线的母进程。它负责进程生命周期、通道连接、定时触发、
队列、线程锁、状态存储、日志和 MCP server。目标形态是三个主要线程：
realtime、loop、MCP server。

`Realtime Thread` 是即时消息入口，第一版接飞书，未来可以接 Web 或微信。它不
承载业务逻辑，只把用户消息交给 Agent-Wrapper，并把 Agent 的流式输出渲染回
聊天界面。

`Loop Thread` 要保持简单。它只按时间醒来，然后调用 Agent-Wrapper 运行配置里
的 loop prompt。课程检查、状态更新和通知判断都属于 Agent 工作，不属于 loop
线程本身的业务逻辑。

`MCP Server Thread` 暴露通用 channel tools 给 Agent。接口命名应保持
channel-neutral，哪怕第一版底层只通过飞书发送。

`Agent-Wrapper` 是 daemon 内部最关键的编排层。它负责准备 run prompt，实时
读取 runtime config 和 prompt fragments，注入 skills 和 tool instructions，
选择具体 Agent，启动或恢复 Agent，接收事件，并写入 artifacts。

`Agent` 是真正执行者。第一版是 Codex，但高层命名和边界不应绑定 Codex。未来
Claude Code 或 Kimi Code 应该可以作为新的 Agent 接入，而不改变 daemon 层概念。

`pku3b` 是外部 CLI 工具。第一版不把它包装成 MCP tool。Agent 通过 skill 文档
得知如何使用 pku3b，并在需要时自己调用。

## Runtime Config

绝大多数行为配置都属于 Agent-Wrapper 层，并且应在每次 run 前从 JSON 实时读取。

Runtime config 包括 provider、model、reasoning level、Codex fast/standard/deep
mode、sandbox、timeout、loop interval、loop prompt、prompt fragments、默认
skills、通知策略等。

Agent-Wrapper 也会在运行时读取 prompt fragments 和 skill 文档。这样 Agent 可以
修改配置或 prompt 文件，下一次 realtime run 或 loop tick 就会自动生效，不需要
重启 daemon。

如果 runtime JSON 缺失或损坏，Agent-Wrapper 应使用上一次有效配置或默认配置
fallback，并且必须把 fallback warning 写入日志和 run metadata，方便排查。

## MCP Tool 边界

MCP Tools 是 channel action tools，不是 daemon 管理接口。

第一版有价值的工具是：

- `channel_send_text`
- `channel_send_card`
- `channel_send_image`
- `channel_update_card`

这些工具使用通用命名。第一版 backend 是 Feishu，但未来 Web 或微信 adapter
应该能接入同一组 tool surface。

以下内容不属于这个架构里的 MCP Tools：

- runtime config get/set
- run current/status/progress
- pku3b_run

runtime 和 run context 由 Agent-Wrapper 注入给 Agent。pku3b 通过 skill 文档暴露。

## 执行流程

即时消息路径中，channel adapter 收到用户消息，daemon 创建 run，Agent-Wrapper
拼凑 prompt，具体 Agent 流式输出事件，realtime thread 把事件渲染回用户。

周期 loop 路径中，loop thread 按时间醒来，把配置的 loop prompt 交给
Agent-Wrapper。Agent 检查状态并更新文件。默认保持静默；只有 Agent 判断存在
重要通知时，才通过 channel MCP tools 主动发消息。

## 设计原则

PkuClaw core 应该保持薄而稳定。业务智能属于 Agent 行为、prompt 构建、skills
和 tools。Daemon 提供稳定运行结构；Agent-Wrapper 把上下文转换成 Agent 可以
执行的工作；Agent 负责真正执行。
