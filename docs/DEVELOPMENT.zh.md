# PkuClaw 开发说明

本文描述当前 runtime / prompt / skill 架构。

## 1. 两类 Agent run

PkuClaw 只有两类 Agent run，由 `source` 表示：

- `realtime`：用户实时消息或配置化 quick action 触发，目标是直接自然中文流式回复用户。
- `loop`：后台周期任务触发，默认静默，只在重要变化时通知用户。

CoreRuntime 不再做自然语言意图分类。实时消息创建：

```text
source = realtime
suggested_skills = ()
```

LoopManager 从 `configs/runtime/runtime.json` 读取对应 loop，并创建：

```text
source = loop
suggested_skills = loop.skill_names
```

## 2. Runtime 文件

运行时配置是 Agent 可直接读写的文件：

```text
configs/runtime/
  runtime.json          # agent/codex/loops/notification 配置
  events.json           # realtime quick action 配置
  prompts.json          # realtime/loop prompt 模板
  skills.json           # Skill Catalog source of truth
  skills/               # skill markdown 文件
    runtime/            # runtime/config/skill 编写规范
    pku3b/              # pku3b 安装和使用说明
    tasks/              # 课程/学习任务
    tools/              # 非 pku3b 通用辅助能力
```

如果 Agent 需要查看或修改 runtime，应直接读写这些文件，而不是调用 MCP runtime 管理工具。

## 3. Realtime quick actions

`configs/runtime/events.json` 定义用户主动触发的快捷实时任务。每个 event 包含：

- `id`
- `title` / `description`
- `task`
- `skill_names`
- `ack`
- `enabled`

Channel adapter 负责判断平台原始事件属于哪一类：

- channel UI 事件：例如查看运行详情、翻页，直接在 channel 层处理；
- 噪声/no-op：忽略；
- quick action：输出干净的 PkuClaw `event_id` 给 CoreRuntime。

如果平台 key 已经等于 PkuClaw event id，可以原样传；如果不是，则由 channel 根据 `events.json` 的 `channel_mappings` 或自身逻辑映射。CoreRuntime 只按 `event_id` 查 `events.json`，并创建普通 `source=realtime` run，流式显示回 channel。

## 4. Skill Catalog

`configs/runtime/skills.json` 与 `configs/runtime/skills/**` 是 skill 唯一运行时来源。

Catalog 条目包含：

- `name`
- `description`
- `path`
- `dependencies`
- `allowed_sources`
- `requires_confirmation`

Prompt 中只注入 Skill Catalog。Agent 根据任务选择相关 skill，并按 `path` 打开 markdown 文件；依赖也由 Agent 按 catalog 读取。完整 skill markdown 不默认注入。

`sub-skills/` 已废弃，不再作为 runtime skill 来源。

## 5. Prompt 构建

`pkuclaw/agents/wrapper.py` 按 `source` 分支：

- `realtime` -> `_build_realtime_prompt(context)`
- `loop` -> `_build_loop_prompt(context)`

Prompt 正文文案不写死在 wrapper 代码里。`AgentWrapper` 每次构建 prompt 时热读
`configs/runtime/prompts.json`，只向模板注入变量，例如 `skill_catalog`、
`user_request`、`loop_id`、`channel_notification_tools` 等。要改身份、规则、
Objective、通知文案、Suggested Skills 小节等，直接改 runtime 的 `prompts.json`。

### Realtime prompt

只包含：

- 简短身份；
- 回复规则；
- Skill Catalog；
- User Request。

不得包含 run id、source、Agent settings、provider/model/reasoning、repository root、run directory、runtime config path、Recent Runs、MCP tools、完整 skill 正文等内部实现细节。

### Loop prompt

包含：

- 后台周期任务身份；
- loop id / scheduled_at / sink_mode / notification policy / notification target；
- Objective；
- Notification Rules；
- Channel Notification Tools；
- Skill Catalog；
- Suggested Skills；
- Task。

Loop prompt 不复用 realtime prompt，也不包含 runtime 管理工具。

## 6. 代码归属

当前 Python 包分层：

```text
pkuclaw/
  core/       # CoreRuntime、LoopManager、共享模型、Store
  runtime/    # configs/runtime/* 的热读 loader：config/events/prompts/skills
  agents/     # AgentWrapper、sink、artifact、providers/codex.py
  channels/   # Feishu 等平台 adapter：事件转换、流式展示、卡片详情
  mcp/        # loop 主动通知用户的 channel notification tools
```

不要再新增顶层 `runtime_*.py`、`code_agents/` 或业务 connector 包。
如果是 runtime 文件 loader，放 `pkuclaw/runtime/`；如果是具体 Agent provider，放
`pkuclaw/agents/providers/`；如果是平台事件/展示逻辑，放对应 `channels/`。

## 7. MCP 范围

MCP 目前只保留 loop 主动通知用户能力。可暴露给 loop prompt 的工具是：

- `channel_send_text`
- `channel_send_card`
- `channel_send_image`
- `channel_update_card`

Realtime prompt 不注入 MCP tools。runtime status/config/loop 管理工具已从 schema、handler、CoreRuntime Agent-facing surface 中移除。

## 8. runtime.json

`configs/runtime/runtime.json` 热加载。通知目标优先级：

1. 当前 loop 的 `default_channel/default_target_type/default_target_id`；
2. 全局 `notifications.default_channel/default_target_type/default_target_id`。

MCP send tools 不接受 `channel`、`target_type`、`target_id` 或 `loop_id` 参数；
Agent 只传内容，daemon 根据当前 loop 自动解析覆盖目标或全局默认目标。未配置时发送会失败并提示配置缺失。

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
  "prompt": "检查课程状态、教学网通知和本地数据。如果没有重要变化，保持静默；如果发现重要变化，使用 channel notification tools 通知用户。",
  "skill_names": ["tasks/sync-notices.md"],
  "sink_mode": "silent",
  "prevent_overlap": true
}
```

`permissions` 不再用于 Agent prompt 或 MCP runtime 写配置流程；优先从 runtime 文件中移除。

## 9. 开发检查

常用检查：

```bash
python -m compileall pkuclaw
python -m unittest discover
```

新增 prompt 或 runtime 变更时，至少检查：

- realtime prompt 不包含 loop-only 信息；
- loop prompt 不包含 realtime-only 回复要求；
- realtime prompt 不包含 MCP tools；
- loop prompt 只包含 channel notification tools；
- skill catalog 来自 `configs/runtime/skills.json`，缺失/损坏时 daemon 不崩溃并给出 warning。
