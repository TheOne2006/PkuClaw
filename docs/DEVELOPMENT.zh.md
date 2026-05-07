# PkuClaw 开发说明

本文描述当前 runtime / prompt / skill 架构。

## 1. 两类 Agent run

PkuClaw 只有两类 Agent run，由 `source` 表示：

- `realtime`：用户实时消息触发，目标是直接自然中文回复用户。
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
  skills.json           # Skill Catalog source of truth
  skills/               # skill markdown 文件
```

如果 Agent 需要查看或修改 runtime，应直接读写这些文件，而不是调用 MCP runtime 管理工具。

## 3. Skill Catalog

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

## 4. Prompt 构建

`pkuclaw/agents/wrapper.py` 按 `source` 分支：

- `realtime` -> `_build_realtime_prompt(context)`
- `loop` -> `_build_loop_prompt(context)`

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
- loop id / scheduled_at / sink_mode / notify_policy / notification target；
- Objective；
- Notification Rules；
- Channel Notification Tools；
- Skill Catalog；
- Suggested Skills；
- Task。

Loop prompt 不复用 realtime prompt，也不包含 runtime 管理工具。

## 5. MCP 范围

MCP 目前只保留 loop 主动通知用户能力。可暴露给 loop prompt 的工具是：

- `channel_send_text`
- `channel_send_card`
- `channel_send_image`
- `channel_update_card`

Realtime prompt 不注入 MCP tools。runtime status/config/loop 管理工具已从 schema、handler、CoreRuntime Agent-facing surface 中移除。

## 6. runtime.json

`configs/runtime/runtime.json` 热加载。Loop 示例：

```json
{
  "id": "sync_notices",
  "enabled": true,
  "interval_seconds": 900,
  "prompt": "检查课程状态、教学网通知和本地数据。如果没有重要变化，保持静默；如果发现重要变化，使用 channel notification tools 通知用户。",
  "skill_names": ["tasks/sync-notices.md"],
  "sink_mode": "silent",
  "notify_policy": "important_only",
  "prevent_overlap": true
}
```

`permissions` 不再用于 Agent prompt 或 MCP runtime 写配置流程；优先从 runtime 文件中移除。

## 7. 开发检查

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
