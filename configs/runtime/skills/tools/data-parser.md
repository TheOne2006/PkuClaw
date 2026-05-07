---
name: pkuclaw-tool-data-parser
description: 解析和比较课程快照、作业、公告与 DDL 风险
---

# 课程快照数据解析

本 tool skill 的主职责不是“解析某个 CLI 的花哨输出”，而是把已有数据归一化为 PkuClaw 可稳定消费的课程快照，并比较新旧快照。

## 推荐输入

优先处理结构化 JSON：

```text
data/pkuclaw/course-sync/parsed/latest.json
```

如果上游暂时只能提供文本输出，先由独立 collector/wrapper 清理为 JSON，再交给 `tasks/sync-notices.md` 使用。Agent 不应在 loop 中直接依赖 ANSI/进度条文本。

## 快照 schema

```python
SNAPSHOT_KEYS = {
    "generated_at",
    "source",
    "status",
    "assignments",
    "announcements",
    "errors",
}
```

字段约定：

- `status`: `ok | partial | stale | auth_required | tool_missing | unavailable`
- `assignments[*].urgent_level`: `overdue | due_24h | due_7d | normal | done | unknown`
- `due_at` 优先使用 ISO-8601；无法解析时保留 `due_text`。

## 基础清理函数

仅在必须处理文本时使用：

```python
import re

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
ID_RE = re.compile(r"\b[0-9a-f]{12,32}\b", re.I)


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text).replace("\r", "\n")


def compact_lines(text: str) -> list[str]:
    return [line.strip() for line in strip_ansi(text).splitlines() if line.strip()]
```

## 归一化

```python
def normalize_assignment(item: dict) -> dict:
    return {
        "id": str(item.get("id") or "").strip(),
        "course": str(item.get("course") or "").strip(),
        "title": str(item.get("title") or item.get("assignment") or "").strip(),
        "status": str(item.get("status") or "").strip(),
        "due_at": str(item.get("due_at") or "").strip(),
        "due_text": str(item.get("due_text") or item.get("deadline") or "").strip(),
        "urgent_level": normalize_urgent_level(item.get("urgent_level"), item.get("status"), item.get("due_text")),
    }


def normalize_announcement(item: dict) -> dict:
    return {
        "id": str(item.get("id") or "").strip(),
        "course": str(item.get("course") or "").strip(),
        "title": str(item.get("title") or "").strip(),
        "created_at": str(item.get("created_at") or "").strip(),
    }


def normalize_urgent_level(value, status=None, due_text=None) -> str:
    allowed = {"overdue", "due_24h", "due_7d", "normal", "done", "unknown"}
    raw = str(value or "").strip()
    if raw in allowed:
        return raw
    text = f"{status or ''} {due_text or ''}".lower()
    if "已完成" in text or "done" in text or "submitted" in text:
        return "done"
    if "逾期" in text or "overdue" in text:
        return "overdue"
    m = re.search(r"in\s*(\d+)\s*d", text)
    if m:
        days = int(m.group(1))
        return "due_7d" if days <= 7 else "normal"
    if re.search(r"in\s*(\d+)\s*h", text):
        return "due_24h"
    return "unknown"
```

## 快照读取/写入

```python
import json
from pathlib import Path


def read_json(path: str | Path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: str | Path, data: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
```

## 新旧快照比较

```python
def assignment_key(item: dict) -> str:
    return item.get("id") or f"{item.get('course')}::{item.get('title')}"


def announcement_key(item: dict) -> str:
    return item.get("id") or f"{item.get('course')}::{item.get('title')}"


def diff_snapshot(old: dict | None, new: dict) -> dict:
    old = old or {}
    old_asg = {assignment_key(normalize_assignment(x)): normalize_assignment(x) for x in old.get("assignments", [])}
    new_asg = {assignment_key(normalize_assignment(x)): normalize_assignment(x) for x in new.get("assignments", [])}
    old_ann = {announcement_key(normalize_announcement(x)): normalize_announcement(x) for x in old.get("announcements", [])}
    new_ann = {announcement_key(normalize_announcement(x)): normalize_announcement(x) for x in new.get("announcements", [])}

    changed_assignments = []
    for key, item in new_asg.items():
        before = old_asg.get(key)
        if before is None:
            changed_assignments.append({"change": "new", **item})
        elif (before.get("status"), before.get("due_at"), before.get("due_text")) != (item.get("status"), item.get("due_at"), item.get("due_text")):
            changed_assignments.append({"change": "updated", **item})

    urgent_assignments = [
        item for item in new_asg.values()
        if item.get("urgent_level") in {"overdue", "due_24h"}
    ]
    new_announcements = [
        item for key, item in new_ann.items()
        if key not in old_ann
    ]
    bad_status = new.get("status") in {"auth_required", "tool_missing", "unavailable"}

    return {
        "changed_assignments": changed_assignments,
        "urgent_assignments": urgent_assignments,
        "new_announcements": new_announcements,
        "bad_status": bad_status,
        "important": bool(changed_assignments or urgent_assignments or new_announcements or bad_status),
    }
```

## 摘要原则

- 先列 `overdue/due_24h`，再列 `due_7d`；
- 按课程聚合，避免逐条刷屏；
- 对 `partial/stale/auth_required/tool_missing` 明确标注数据可信度；
- 不输出凭据、完整错误日志或内部长路径。
