---
title: Skill Catalog
description: PkuClaw runtime skill 的目录、依赖和加载规则。
---

PkuClaw 的 skill source of truth 是：

```text
configs/runtime/skills.json
configs/runtime/skills/**
```

Prompt 中只渲染目录元数据。Agent 根据任务决定是否按 `path` 打开具体 markdown 文件。

## Catalog 字段

| 字段 | 说明 |
| --- | --- |
| `name` | 目录中的技能名。 |
| `description` | 给 Agent 选择技能时看的简介。 |
| `path` | skill markdown 相对 `configs/runtime/skills/` 的路径。 |
| `dependencies` | 依赖的其他 skill。 |
| `allowed_sources` | 允许在 `realtime`、`loop` 或两者中使用。 |
| `requires_confirmation` | 执行敏感操作前是否需要用户确认。 |

## Suggested skills 不是强制注入

Quick action 和 loop 都可以提供 `skill_names`，但这只是建议：

```text
Suggested skills for this run (read them by path if useful)
```

Agent 仍需根据任务判断是否打开这些文件。

## Skill markdown 的职责

建议每个 skill 保持单一职责，例如：

- `tasks/sync-notices.md`：教学网通知/DDL 同步任务规则；
- `tools/channel-outbox.md`：outbox 脚本使用方式；
- `runtime/authoring.md`：如何安全修改 runtime 文件。

## 编写原则

- 明确适用的 run source。
- 明确需要确认的操作。
- 不写入密钥、token、用户隐私数据。
- 给出可执行命令时说明前置条件和失败处理。
- 如果依赖其他 skill，放进 catalog 的 `dependencies`。
