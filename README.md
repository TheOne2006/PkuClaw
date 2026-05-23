<div align="center">

# 🐾 PkuClaw

**将你的一切教学网事项都交给 Agent**

PkuClaw 是一个面向 PKU 学习场景的本地 Agent runtime。它可以检查课程通知、作业 DDL、成绩变化，并通过飞书、网页或其他渠道提醒你需要关注的事项。

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![Docs](https://img.shields.io/badge/Docs-Fumadocs-111827)](https://theone2006.github.io/PkuClaw/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

</div>

---

## ✨ 它是什么？

PkuClaw 把 PKU 学习/课程 workflow 拆成几个可审计的运行边界：

- **Realtime**：用户消息或 quick action 触发，直接用中文流式回复。
- **Loop**：后台周期任务，默认静默，只在重要变化时通知。
- **Runtime Files**：`configs/runtime/**` 热加载，配置、prompt、skills 都可以通过文件 diff review。
- **Channel Outbox**：Agent 只写 text/image/file 队列，daemon 负责目标解析和渠道投递。

完整架构、配置和开发文档发布在 [PkuClaw 文档站](https://theone2006.github.io/PkuClaw/)；根 README 只保留快速介绍和最短安装入口。

## 🚀 快速安装

### 1. 准备环境

```bash
git clone https://github.com/TheOne2006/PkuClaw.git
cd PkuClaw
uv sync
uv run pkuclaw --help
```

也可以使用标准 Python editable install：

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
pkuclaw --help
```

### 2. 创建本地配置

```bash
cp configs/config.example.toml configs/config.toml
cp configs/runtime/runtime.example.json configs/runtime/runtime.json
```

`configs/config.toml` 与 `configs/runtime/runtime.json` 是本地真实配置，默认不应提交。

如果启用飞书渠道，至少需要设置：

```bash
export FEISHU_APP_SECRET="你的飞书 app secret"
```

> 不要提交真实 token、cookie、Open ID、chat id、日志或 `data/` 运行产物。

### 3. 运行基础检查

```bash
python -m compileall pkuclaw scripts
python -m unittest discover
```

### 4. 启动运行时

```bash
# 开发实时入口：只启用 Feishu realtime 路径
uv run pkuclaw realtime feishu

# 完整 daemon：Feishu + CoreRuntime + loop + outbox queue worker
uv run pkuclaw daemon
```

## 📚 下一步

- [在线文档站](https://theone2006.github.io/PkuClaw/)：正式发布的使用指南与开发者指南。
- [快速开始文档](https://theone2006.github.io/PkuClaw/docs/user-guide/quickstart)：更完整的安装路径。
- [配置说明](https://theone2006.github.io/PkuClaw/docs/user-guide/configuration)：启动期配置与 runtime 配置边界。
- [开发者指南](https://theone2006.github.io/PkuClaw/docs/developer-guide)：runtime、Agent、Channel、Loop 和扩展开发。
- [文档站维护说明](docs-site/README.md)：本地预览、构建和发布方式。
- [架构说明](ARCHITECTURE.md)：CoreRuntime、AgentWrapper、LoopManager 和 outbox 的边界。
- [pku3b README](crates/pku3b/README.md)：PKU Blackboard / Portal raw JSON CLI。

## 📄 License

本项目使用 [MIT License](LICENSE)。
