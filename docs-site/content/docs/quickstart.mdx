---
title: 快速开始
description: 在本地准备 PkuClaw，并跑起开发入口。
---

本页给出一条最短路径：拉取仓库、安装依赖、复制配置、运行基础检查，然后启动开发入口。

## 1. 克隆仓库

```bash
git clone https://github.com/TheOne2006/PkuClaw.git
cd PkuClaw
```

## 2. 准备 Python 环境

推荐使用 `uv`：

```bash
uv sync
uv run pkuclaw --help
```

如果暂时不用 `uv`，也可以使用标准 Python editable install：

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
pkuclaw --help
```

## 3. 创建本地启动配置

```bash
cp configs/config.example.toml configs/config.toml
```

然后编辑 `configs/config.toml`。本地真实配置不应提交，仓库 `.gitignore` 已忽略它。

## 4. 配置必要凭据

如果要启用飞书渠道，需要设置飞书 app secret：

```bash
export FEISHU_APP_SECRET="你的飞书 app secret"
```

`FEISHU_APP_ID`、`FEISHU_API_BASE` 也可以通过环境变量覆盖配置文件。

## 5. 运行检查

```bash
python -m compileall pkuclaw scripts
python -m unittest discover
```

## 6. 启动入口

开发实时路径：

```bash
uv run pkuclaw realtime feishu
```

完整 daemon：

```bash
uv run pkuclaw daemon
```

完整 daemon 会启用渠道、`CoreRuntime`、后台 loop 和 outbox queue worker。实时 debug 入口只保留 realtime 路径，便于调试 UI 和消息流。

## 下一步

- 阅读 [安装说明](../installation/) 补齐工具依赖。
- 阅读 [配置说明](../configuration/) 理解启动期配置和 runtime 配置的边界。
- 阅读 [Runtime 设计](../runtime/) 了解 realtime、loop、quick action 和 skill catalog。
