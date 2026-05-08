# PkuClaw 开发说明

本文描述当前 runtime / prompt / skill / channel outbox 架构。修改 runtime prompt、通知策略、loop/realtime 行为或 channel outbox 前，请先阅读本文、`ARCHITECTURE.md` 和相关测试。

## 1. 两类 Agent run

PkuClaw 只有两类 Agent run，由 `source` 表示：

| source | 触发方式 | 默认行为 |
| --- | --- | --- |
| `realtime` | 用户实时消息或配置化 quick action | 直接自然中文流式回复用户。普通消息不预选 skill；quick action 可提供 suggested skills。 |
| `loop` | `LoopManager` 后台周期 tick | 默认静默；只有通知策略允许且发现重要变化/阻塞时才使用 channel outbox。 |

CoreRuntime 不做自然语言意图分类。实时消息创建：

```text
source = realtime
suggested_skills = ()
sink_mode = streaming
```

LoopManager 从本地 `configs/runtime/runtime.json` 读取 enabled loop，并创建：

```text
source = loop
suggested_skills = loop.skill_names + (tools/channel-outbox.md,)
sink_mode = loop.sink_mode
```

Quick action 是 realtime 的配置化入口，不是第三类 run。

## 2. Runtime 文件

运行时配置是 Agent 和 operator 可审计、可热加载的普通文件：

```text
configs/runtime/
  runtime.example.json  # 可提交的本地 runtime 配置模板
  runtime.json          # 不提交；agent/codex/loops/notification 配置
  events.json           # realtime quick action 配置
  prompts.json          # realtime/loop prompt 模板
  skills.json           # Skill Catalog source of truth
  skills/               # skill markdown 文件
    runtime/            # runtime/config/skill 编写规范
    pku3b/              # pku3b 安装和使用说明
    tasks/              # 课程/学习任务
    tools/              # 通用辅助能力与 channel outbox 脚本说明
```

如果 Agent 需要查看或修改 runtime，应直接读写这些文件。启动期凭据、飞书密钥、绑定 host/port、真实用户 target id 等不属于安全的公共示例，不应随意写入文档或提交。

## 3. Realtime quick actions

`configs/runtime/events.json` 定义用户主动触发的快捷实时任务。每个 event 包含：

- `id`
- `enabled`
- `title` / `description`
- `task`
- `skill_names`
- `ack`

Channel adapter 负责判断平台原始事件属于哪一类：

- channel UI 事件：例如查看运行详情、翻页，留在 channel 层处理；
- 噪声/no-op：忽略；
- quick action：映射为干净的 PkuClaw `event_id` 给 CoreRuntime。

如果平台 key 已经等于 PkuClaw event id，可以原样传；如果不是，则由 channel 根据 `events.json.channel_mappings` 或自身逻辑映射。

## 4. Skill Catalog

`configs/runtime/skills.json` 与 `configs/runtime/skills/**` 是 runtime skill 的唯一来源。

Catalog 条目包含：

- `name`
- `description`
- `path`
- `dependencies`
- `allowed_sources`
- `requires_confirmation`

Prompt 中只注入 Skill Catalog 元数据。Agent 根据任务选择相关 skill，并按 `path` 打开 markdown 文件；依赖也由 Agent 按 catalog 读取。完整 skill markdown 不默认注入。

`sub-skills/` 已废弃，不再作为 runtime skill 来源。

## 5. Prompt 构建

`pkuclaw/agents/wrapper.py` 按 `source` 分支：

- `realtime` -> `_build_realtime_prompt(context)`
- `loop` -> `_build_loop_prompt(context)`

Prompt 正文文案不写死在 wrapper 代码里。`AgentWrapper` 每次构建 prompt 时热读 `configs/runtime/prompts.json`，只向模板注入变量，例如 `skill_catalog`、`user_request`、`loop_id`、`channel_outbox_skill` 等。要改身份、规则、Objective、通知文案、Suggested Skills 小节等，优先改 `prompts.json`。

### Realtime prompt

只包含：

- 简短身份；
- 回复规则；
- Skill Catalog；
- quick action 的 Suggested Skills（如有）；
- User Request。

不得包含 run id、source、Agent settings、provider/model/reasoning、repository root、run directory、runtime config path、Recent Runs、outbox 脚本正文、完整 skill 正文等内部实现细节。

### Loop prompt

包含：

- 后台周期任务身份；
- loop id / scheduled_at / sink_mode / notification policy / notification target；
- Objective；
- Notification Rules；
- Channel Outbox Skill 指针；
- Skill Catalog；
- Suggested Skills；
- Task。

Loop prompt 不复用 realtime 回复规则，也不包含 runtime 管理工具。

## 6. 代码归属

当前 Python 包分层：

```text
pkuclaw/
  core/         # CoreRuntime、LoopManager、共享模型、Store
  runtime/      # configs/runtime/* 的热读 loader：config/events/prompts/skills
  agents/       # AgentWrapper、sink、artifact、providers/codex.py
  channels/     # Feishu 等平台 adapter：事件转换、流式展示、卡片详情
  notify_queue/ # daemon 文件 outbox 队列 worker
scripts/        # outbox 脚本 thin clients
```

不要再新增顶层 `runtime_*.py`、`code_agents/`、`notify_http/` 或业务 connector 包。如果是 runtime 文件 loader，放 `pkuclaw/runtime/`；如果是具体 Agent provider，放 `pkuclaw/agents/providers/`；如果是平台事件/展示逻辑，放对应 `channels/`。

## 7. Channel outbox 链路

Realtime artifact delivery 和 loop 通知共用一条 channel-neutral 文件队列：

```text
Agent -> Channel Outbox Skill -> scripts/pkuclaw_outbox.py -> data/notify_queue/pending/*.json -> daemon queue worker -> CoreRuntime -> channel backend
```

模型可见能力只有三类：

```bash
python scripts/pkuclaw_outbox.py text --text "..." --title "optional"
python scripts/pkuclaw_outbox.py image --path image.png --caption "optional"
python scripts/pkuclaw_outbox.py file --path result.pdf --caption "optional"
```

脚本层只负责把 JSON job 写入共享队列目录，并可等待 daemon ack。脚本不访问 localhost HTTP，不直连飞书，不解析 runtime target，不做卡片渲染；这些由 daemon/CoreRuntime 和 channel backend 统一负责。

队列默认位于 `data/notify_queue/`（由 `[app].data_dir` + `[notify_queue].queue_dir` 解析），包含：

```text
pending/ processing/ done/ failed/ acks/
```

Agent 进程会收到这些环境变量：

- `PKUCLAW_OUTBOX_QUEUE_DIR`
- `PKUCLAW_RUN_ID`
- `PKUCLAW_RUN_SOURCE`
- `PKUCLAW_LOOP_ID`（仅 loop）

不要给脚本传 `channel`、`target_type` 或 `target_id`。脚本也没有模型可见的 `card` / `update-card` API；飞书卡片、Markdown 渲染、资源上传和卡片更新都是 channel/runtime 内部实现。

## 8. runtime.json

`configs/runtime/runtime.example.json` 是可提交模板；本地复制为
`configs/runtime/runtime.json` 后由 daemon 热加载。`runtime.json` 不提交，
因为它可能包含飞书 `open_id`/`chat_id` 等本地 channel 目标。通知策略支持：

```text
important_only | always | silent | on_error | digest
```

通知目标解析优先级：

1. 当前 run 的原始 channel target；
2. 当前 loop 的 `default_channel/default_target_type/default_target_id`；
3. 全局 `notifications.default_channel/default_target_type/default_target_id`。

全局通知目标示例：

```json
{
  "notifications": {
    "policy": "important_only",
    "default_channel": "feishu",
    "default_target_type": "open_id",
    "default_target_id": "ou_xxx"
  }
}
```

Loop 示例：

```json
{
  "id": "sync_notices",
  "enabled": true,
  "interval_seconds": 900,
  "prompt": "检查课程状态、教学网通知和本地数据。如果没有重要变化，保持静默；如果发现重要变化，使用 Channel Outbox Skill 通知用户。",
  "skill_names": ["tasks/sync-notices.md"],
  "sink_mode": "silent",
  "prevent_overlap": true,
  "max_concurrent_runs": 1
}
```

`permissions` 不再用于 Agent prompt；优先从 runtime 文件中移除。

## 9. 开发检查

常用检查：

```bash
python -m compileall pkuclaw scripts
python -m unittest discover
```

文档站改动还应运行：

```bash
cd docs-site
npm ci
npm run build
```

新增 prompt 或 runtime 变更时，至少检查：

- realtime prompt 不包含 loop-only 信息；
- loop prompt 不包含 realtime-only 回复要求；
- realtime prompt 不包含 outbox 脚本正文；
- loop prompt 指向 Channel Outbox Skill；
- skill catalog 来自 `configs/runtime/skills.json`，缺失/损坏时 daemon 不崩溃并给出 warning。
