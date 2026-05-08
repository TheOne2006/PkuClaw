# PkuClaw 架构

PkuClaw 采用以 daemon 为中心的运行时模型：两个 Agent 运行来源、可编辑的运行时文件、基于目录的技能（Skill），以及一个本地 channel outbox 队列。realtime 和 loop 运行都会通过脚本使用该队列。

## 1. 运行来源

Agent 只有两个运行来源：

| 来源 | 触发方式 | 行为 |
| --- | --- | --- |
| `realtime` | 用户消息或已配置的快捷操作 | 通过流式 channel UI 直接回复用户。普通消息没有预选技能；快捷操作可以带有建议技能。 |
| `loop` | `LoopManager` 的定时 tick | 运行已配置的后台任务。除非有重要信息，否则保持静默。 |

CoreRuntime 不会把用户文本分类为不同任务类别。普通 realtime 消息会创建 `source="realtime"` 且 `suggested_skills=()`。已配置的 realtime 快捷操作从 `configs/runtime/events.json` 加载，也会创建 `source="realtime"`。loop 会创建 `source="loop"`，并使用该 loop 配置的 `suggested_skills`，同时把 channel outbox skill 作为建议技能。

## 2. 运行时文件

运行时状态以可编辑文件的形式暴露：

```text
configs/runtime/
  runtime.json
  events.json
  prompts.json
  skills.json
  skills/
    runtime/            # runtime/config/skill 编写规则
    pku3b/              # pku3b 安装与使用文档
    tasks/              # 面向用户的学习/课程任务
    tools/              # 共享辅助工具，包括 channel outbox 脚本
```

Agent 在需要时会直接读取或编辑这些文件。运行时配置不通过 Agent 协议层管理。

## 3. Realtime 快捷操作

`configs/runtime/events.json` 定义用户触发的快捷操作。每个 event 都有一个 `id`、`task`、可选的 `suggested_skills`，以及展示元数据。Channel adapter 决定平台事件是仅用于 UI、被忽略/no-op，还是快捷操作。对于快捷操作，它们会把干净的 PkuClaw `event_id` 传给 CoreRuntime；原始平台 key 只有在已经等于某个已配置的 PkuClaw id 时，才可以被映射或原样传递。

CoreRuntime 会把已配置的 event 转换成一次普通的流式 realtime run。这保留了双来源模型：快捷操作属于 realtime，而不是第三种 run 类型。

## 4. 技能目录

`configs/runtime/skills.json` 是技能目录的事实来源。它指向 `configs/runtime/skills/**` 下的 markdown 文件，并包含：

- `name`
- `description`
- `path`
- `dependencies`
- `allowed_sources`
- `requires_confirmation`

AgentWrapper 会把目录渲染进 prompt。技能正文默认不会注入。Suggested Skills 只列出相关技能的元数据；由 Agent 决定要打开哪些文件。

如果 `skills.json` 缺失或无效，daemon 会带着空目录继续运行，并给出 warning。

## 5. Prompt 构建器

AgentWrapper 会根据 `source` 分支处理：

- `_build_realtime_prompt(context)` 创建 `# PkuClaw Realtime Task`，其中包含简短身份说明、回复规则、Skill Catalog、Suggested Skills 和 User Request。普通 realtime 消息会把 Suggested Skills 渲染为 `- none`；已配置的快捷操作可以提供明确建议。
- `_build_loop_prompt(context)` 创建 `# PkuClaw Loop Task`，其中包含 loop id、计划时间、sink 模式、通知策略、通知目标、通知规则、Skill Catalog、建议技能和 Task。

这两类 prompt 的措辞/模板都不硬编码在 `AgentWrapper` 中。
它们会在每次构建 prompt 时从 `configs/runtime/prompts.json` 热读取。
代码只提供命名变量，例如 `skill_catalog`、`user_request`、
`suggested_skills`、`loop_id`、`scheduled_at` 和 `notification_target`。

Realtime prompt 不包含 run id、source 标签、provider 设置、仓库路径、运行时路径、近期 run、outbox 脚本正文，或完整的技能 markdown 正文。

Loop prompt 不复用 realtime 回复规则，也不包含运行时管理工具。

## 6. Channel outbox 路径

Realtime 产物交付和 loop 通知使用同一条 channel-neutral outbox 路径：

```text
Agent -> channel-outbox skill -> scripts/pkuclaw_outbox.py -> file queue -> daemon queue worker -> CoreRuntime -> channel backend
```

模型可见的 API 只有 text/image/file。默认情况下，队列以文件形式存储在应用数据目录下，使用 `data/notify_queue/`，并包含 `pending/`、`processing/`、`done/`、`failed/`、`acks/` 等子目录。脚本不会打开网络 socket，不会直接调用飞书，不会解析运行时目标，也不会渲染卡片。daemon 大约每 5 秒扫描一次队列，并通过 CoreRuntime 负责目标解析和 channel 投递。

## 7. Loop 行为

`LoopManager` 会热加载 `configs/runtime/runtime.json`，调度已启用的 loop，并请求 CoreRuntime 创建 `source="loop"` 的 run。Loop prompt 会告知 Agent：

- 没有重要变化：保持静默；
- 有重要变化：通过 Channel Outbox Skill 入队 text/image/file；
- loop 的最终回答用于日志/产物，不对用户可见。

Outbox 请求只包含 text/image/file 内容，以及由 provider 环境变量提供的 run 上下文。daemon 会先解析原始 run 的 channel 目标，然后解析 loop 专属的 `default_channel/default_target_type/default_target_id` 覆盖项，最后解析共享的 `notifications.default_channel/default_target_type/default_target_id`。如果没有任何配置，发送会明确失败，而不是要求 Agent 猜测接收者。卡片创建和 update-card 都是 channel/runtime 内部机制，不是模型可见 API。

## 8. 仓库布局

```text
pkuclaw/
  agents/             # AgentWrapper、sinks、artifacts、provider 实现
    providers/
      codex.py
  core/               # CoreRuntime、LoopManager、共享模型、Store
    runtime.py
    loops.py
    models.py
    store.py
  notify_queue/       # daemon 文件通知队列 worker
  runtime/            # 热加载的可编辑运行时文件 reader
    config.py         # configs/runtime/runtime.json
    events.py         # configs/runtime/events.json
    prompts.py        # configs/runtime/prompts.json
    skills.py         # configs/runtime/skills.json + skills/**
scripts/              # channel outbox 队列 CLI
configs/runtime/
  runtime.json
  events.json
  prompts.json
  skills.json
  skills/
```

`sub-skills/` 不再作为运行时技能来源使用。
