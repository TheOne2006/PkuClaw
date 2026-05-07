---
name: pkuclaw-task-sync-notices
description: 基于稳定课程快照同步通知、作业、DDL 和公告
---

# 任务：同步课程通知

核心原则：先读稳定快照，再做摘要和变化判断。不要让 Agent 在常规 loop 中直接驱动教学网登录、交互式 CLI 或 sub-agent。

## 为什么不直接依赖 pku3b

`pku3b` 是面向人类终端的强工具，但不适合作为 loop 默认路径：

- 登录/OTP/验证码可能需要 TTY；
- 输出含进度条、ANSI 样式和缓存行为，解析不够稳定；
- 网络、教学网状态和账号状态会让 loop 变得高噪声；
- 安装、构建、登录和抓取都可能涉及凭据或系统依赖。

因此本 skill 默认只消费已经生成好的结构化快照。需要接入 pku3b 时，应先做一个确定性的 snapshot collector/wrapper，再让本 skill 读取 wrapper 产物。

## 默认数据源约定

优先读取：

```text
data/pkuclaw/course-sync/parsed/latest.json
data/pkuclaw/course-sync/summaries/latest.md
data/pkuclaw/course-sync/state/last.json
```

`latest.json` 推荐结构：

```json
{
  "generated_at": "ISO-8601",
  "source": "snapshot-collector | manual | pku3b-wrapper",
  "status": "ok | partial | stale | auth_required | tool_missing | unavailable",
  "assignments": [
    {
      "id": "stable-id-or-empty",
      "course": "课程名",
      "title": "作业名",
      "status": "raw status",
      "due_at": "ISO-8601-or-empty",
      "due_text": "原始截止描述",
      "urgent_level": "overdue | due_24h | due_7d | normal | done | unknown"
    }
  ],
  "announcements": [
    {"id": "stable-id-or-empty", "course": "课程名", "title": "公告标题", "created_at": "optional"}
  ],
  "errors": []
}
```

如果这些文件不存在，不要臆造课程状态；Realtime 中说明“还没有配置课程快照数据源”，Loop 中只有在需要用户处理时通知。

## Realtime 执行方式

1. 读取 `summaries/latest.md`；没有则读 `parsed/latest.json` 并临时生成摘要。
2. 回答用户关心的问题：本周 DDL、未完成作业、最新公告、需要优先处理的事项。
3. 如果快照 stale/partial/auth_required/tool_missing，明确说明状态和下一步。
4. 不提交作业，不下载附件，不自动登录教学网。

## Loop 执行方式

1. 读取 `parsed/latest.json` 和 `state/last.json`。
2. 用 `tools/data-parser.md` 的 diff 规则判断变化。
3. 写回摘要到 `summaries/latest.md`；必要时更新 `state/last.json`。
4. 没有重要变化：保持静默。
5. 有重要变化：使用 channel notification tools 通知。

## 重要变化定义

- 新增作业或 DDL 变化；
- 24 小时内到期、逾期、状态从未完成变得更紧急；
- 新增重要公告；
- 快照状态变为 `auth_required`、`tool_missing`、`unavailable`；
- 连续失败或快照明显过期。

## 通知格式

控制在 3-6 条要点：

```text
PKU 课程快照有重要变化：
1. 数据库概论：作业 X 24h 内截止
2. 算法设计：新增公告 Y
建议：今天优先处理数据库概论作业。
```

不要输出凭据、完整日志、内部长路径或无关调试信息。

## 可选：接入 live collector

只有当用户明确要求“配置/调试教学网抓取”时，才读取 `pku3b/usage.md`。理想路径不是让 Agent 每次 loop 里手动跑 pku3b，而是实现一个独立、可测试、非交互的 collector，负责：

- 统一 timeout/retry；
- 处理登录状态和错误分类；
- 清理 ANSI/进度条；
- 输出上述 `latest.json`；
- 不把凭据写入日志或仓库。
