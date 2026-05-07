---
title: Realtime Quick Actions
description: 使用 events.json 定义用户主动触发的实时快捷任务。
---

Quick action 是一种配置化的 realtime 入口。它不会创建第三类 run，也不会变成 loop。

## 文件位置

```text
configs/runtime/events.json
```

## Event 字段

每个 event 包含：

| 字段 | 说明 |
| --- | --- |
| `id` | PkuClaw 内部 event id，必须唯一。 |
| `enabled` | 是否启用。 |
| `title` | 展示标题。 |
| `description` | 展示描述。 |
| `task` | 触发后传给 Agent 的用户任务。 |
| `skill_names` | 建议 Agent 优先阅读的 skill。 |
| `ack` | 渠道收到点击后的短提示。 |

## 示例

```json
{
  "id": "weekly_deadlines",
  "enabled": true,
  "title": "查看本周 DDL",
  "description": "快速查看未来一周课程 DDL 和需要处理的事项。",
  "task": "查看未来一周课程 DDL、未完成作业和需要处理的学习事项，并给出简洁优先级建议。",
  "skill_names": ["tasks/sync-notices.md"],
  "ack": "正在查看本周 DDL。"
}
```

## Channel mapping

渠道适配器可以把平台原始 key 映射到 PkuClaw event id：

```json
{
  "channel_mappings": {
    "feishu": {
      "menu_weekly_deadlines": "weekly_deadlines"
    }
  }
}
```

如果平台 key 本身就是 PkuClaw event id，可以直接透传。

## 行为边界

- quick action 创建 `source = realtime` run；
- quick action 可以提供 suggested skills；
- quick action 不使用 loop 通知规则；
- channel UI-only 事件和噪声事件应留在 channel adapter 内处理。
