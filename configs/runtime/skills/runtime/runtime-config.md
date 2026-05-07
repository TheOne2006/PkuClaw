---
name: pkuclaw-runtime-config
description: 安全调整 PkuClaw runtime 配置、prompt、event 和 loop 的操作规范
---

# PkuClaw Runtime 配置修改

本 skill 只在用户明确要求“改 runtime / 配置 / prompt / loop / event / skill catalog”时使用。它描述如何安全修改 PkuClaw 自身运行时文件，不参与普通课程任务。

## Runtime 文件边界

可调整的 runtime 文件位于：

```text
configs/runtime/
  runtime.json      # Agent provider、Codex 参数、loop 配置、通知策略
  events.json       # realtime quick actions
  prompts.json      # realtime / loop prompt 模板
  skills.json       # Skill Catalog
  skills/**         # runtime skill markdown
```

不要把启动期凭据、飞书密钥、系统包安装、账号密码或 OTP 写入 runtime 文件。

## 修改原则

- 先读当前文件和相关 loader/schema，再修改。
- 一次只改用户要求的最小范围。
- 保持 `schema_version` 不变，除非同步修改 loader 和测试。
- `realtime` prompt 不注入 outbox 脚本正文；`loop` prompt 默认静默，需要通知时只能使用 Channel Outbox Skill 的 text/image/file。
- loop 不应自动执行提交作业、删除数据、登录交互、安装系统依赖等高风险动作。
- 修改 `skills.json` 时，必须保证每个 `path` 指向存在的 markdown 文件。

## 常见改动

### 调整 loop

修改 `runtime.json` 的 `loops[]`。需要保留：

- `id`
- `enabled`
- `interval_seconds`
- `prompt`
- `skill_names`
- `sink_mode`
- `prevent_overlap`

新增 loop 时必须避免重复 `id`，并优先使用已有 task skill。

### 调整 loop 通知目标

所有 loop 共用的默认通知目标写在 `runtime.json` 的 `notifications` section：

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

单个 loop 可以用同名字段覆盖默认目标：

```json
{
  "loops": [
    {
      "id": "special_loop",
      "default_channel": "feishu",
      "default_target_type": "chat_id",
      "default_target_id": "oc_xxx"
    }
  ]
}
```

outbox 脚本不接受 `channel`、`target_type` 或 `target_id` 参数；Agent 只传 text/image/file 内容。provider 会写入 `PKUCLAW_OUTBOX_QUEUE_DIR`、`PKUCLAW_RUN_ID`、`PKUCLAW_RUN_SOURCE`，loop 还会写入 `PKUCLAW_LOOP_ID`。daemon 优先根据 run id 使用原始 channel target，其次使用 loop 覆盖目标，否则退回 `notifications` 默认目标。目标字段要么三个都写，要么都不写。

### 调整 quick action

修改 `events.json` 的 `events[]`。每个 event 应包含：

- `id`
- `enabled`
- `title`
- `description`
- `task`
- `skill_names`
- `ack`

quick action 是 realtime run，不应创建 loop。

### 调整 prompt

修改 `prompts.json` 时只使用 AgentWrapper 已提供的变量。模板中的字面 `{` / `}` 要写成 `{{` / `}}`。

## 验证

修改后至少运行：

```bash
python -m compileall pkuclaw
python - <<'PY'
from pathlib import Path
from pkuclaw.runtime.config import RuntimeConfigStore
from pkuclaw.runtime.events import read_event_catalog
from pkuclaw.runtime.prompts import read_prompt_templates
from pkuclaw.runtime.skills import load_skill_registry
root = Path('configs/runtime')
print(RuntimeConfigStore(root).read_snapshot().warnings)
print(read_event_catalog(root).warnings)
print(read_prompt_templates(root).schema_version)
print(load_skill_registry(root / 'skills.json', skills_dir=root / 'skills').warnings)
PY
```

若用户要求提交成完整改动，再运行相关单测。
