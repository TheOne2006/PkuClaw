---
title: 安装
description: 准备运行 PkuClaw 所需的本地工具和 Python 依赖。
---

## 环境要求

- Python 3.11 或更高版本。
- 推荐安装 `uv` 用于同步 Python 依赖。
- 已安装并可执行的 Codex CLI，供 `provider = "codex"` 使用。
- 如果启用飞书渠道，需要一个飞书应用及其 app id / app secret。
- macOS 或 Linux；Windows 建议使用 WSL。

## 使用 uv 安装

```bash
uv sync
uv run pkuclaw --help
```

`pyproject.toml` 中定义了命令行入口：

```toml
[project.scripts]
pkuclaw = "pkuclaw.cli:app"
```

因此 `uv run pkuclaw daemon` 会进入 `pkuclaw.cli:app`。

## 使用 pip 安装

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
pkuclaw --help
```

## Codex provider

默认配置使用 Codex：

```toml
[agent]
provider = "codex"

[codex]
bin = "codex"
sandbox = "danger-full-access"
model = "gpt-5.5"
timeout_seconds = 1800
max_concurrent_runs = 1
```

当前示例配置会让 PkuClaw 以 Codex full-access/bypass 模式运行，适合可信本地环境和需要访问课程工具/本地文件的后台 loop。若改成更严格 sandbox，请同步评估任务是否会被审批、网络或文件权限阻塞。

请确认本机可以直接运行：

```bash
codex --help
```

## 飞书渠道

`configs/config.example.toml` 中的飞书配置如下：

```toml
[feishu]
app_id = "cli_xxx"
app_secret_env = "FEISHU_APP_SECRET"
event_mode = "websocket"
```

建议把 app secret 放在环境变量中，而不是写进仓库文件：

```bash
export FEISHU_APP_SECRET="..."
```

## 安装后检查

```bash
python -m compileall pkuclaw scripts
python -m unittest discover
```

如果这两条通过，再启动 realtime 或 daemon。
