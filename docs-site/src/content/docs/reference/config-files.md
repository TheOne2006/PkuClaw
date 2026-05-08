---
title: 配置文件参考
description: PkuClaw 启动期配置和 runtime 文件速查。
---

## 启动期配置

```text
configs/config.example.toml
configs/config.toml  # 本地真实配置，默认不提交
```

| Section | 作用 |
| --- | --- |
| `[app]` | app 名称、数据目录、runtime 配置目录、时区。 |
| `[feishu]` | 飞书 app id、secret 环境变量名、事件模式。 |
| `[agent]` | 默认 provider。 |
| `[codex]` | Codex CLI 路径、sandbox、model、timeout、并发数；示例默认 `danger-full-access`，仅用于可信本地 daemon。 |
| `[notify_queue]` | outbox queue 目录和扫描间隔。 |

## Runtime 文件

```text
configs/runtime/
  runtime.json
  events.json
  prompts.json
  skills.json
  skills/
```

| 文件 | 作用 |
| --- | --- |
| `runtime.json` | agent/codex/loops/notifications 的热加载配置；可覆盖 Codex sandbox/timeout。 |
| `events.json` | realtime quick action catalog 与 channel mapping。 |
| `prompts.json` | realtime/loop prompt 模板。 |
| `skills.json` | skill catalog 元数据和依赖。 |
| `skills/**` | runtime skill markdown 正文。 |

## 数据目录

默认 `data/` 保存运行态数据，例如：

```text
data/
  pkuclaw.db
  notify_queue/
  agent_runs/
```

`data/` 是本地运行产物，不应提交。

## 常用命令

```bash
# 检查 Python 语法
python -m compileall pkuclaw scripts

# 运行测试
python -m unittest discover

# 启动完整 daemon
uv run pkuclaw daemon

# 启动 realtime debug 入口
uv run pkuclaw realtime feishu
```

## 文档/代码差异报告

维护者可查看仓库根目录的 `docs/DOC_CODE_GAPS.zh.md`，了解当前文档与代码之间仍需决策的 gap。
