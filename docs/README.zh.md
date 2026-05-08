# PkuClaw 文档索引

本目录收纳仓库级中文维护文档。用户安装、配置和概念介绍优先写入 `docs-site/`；与代码审计、开发流程、文档维护相关的内容放在这里。

## 文档分工

| 文档 | 主要读者 | 维护重点 |
| --- | --- | --- |
| [`../README.md`](../README.md) | 新用户、贡献者 | 中文默认入口、快速开始、配置地图、文档导航。 |
| [`../ARCHITECTURE.md`](../ARCHITECTURE.md) | 维护者 | 当前 runtime 架构契约；修改 core/runtime/agent/channel 前先读。 |
| [`DEVELOPMENT.zh.md`](DEVELOPMENT.zh.md) | 开发者 | 中文开发约定、prompt/runtime 边界、outbox 行为和验证命令。 |
| [`DOC_CODE_GAPS.zh.md`](DOC_CODE_GAPS.zh.md) | 维护者 | 文档与当前代码之间的差异审计、已修复项和待决策项。 |
| [`../configs/runtime/README.md`](../configs/runtime/README.md) | Runtime operator、Agent | `configs/runtime/**` 的字段、热加载行为和 outbox 用法。 |
| [`../docs-site/README.md`](../docs-site/README.md) | 文档站维护者 | Astro Starlight 站点的本地预览、构建和发布入口。 |
| [`../crates/pku3b/README.md`](../crates/pku3b/README.md) | pku3b 使用者/维护者 | Blackboard / Portal raw JSON CLI 的命令契约。 |

## 更新原则

1. **中文优先**：面向用户和维护者的入口文档默认中文。
2. **代码为准**：命令、配置字段、脚本名、环境变量以当前代码和测试为准。
3. **一处定义，多处链接**：避免在多个文档复制大段同一说明；必要复制时同步更新。
4. **敏感信息只用占位符**：示例统一使用 `cli_xxx`、`ou_xxx`、`oc_xxx`。
5. **文档改动要验证**：至少运行 Python 检查；改 `docs-site/` 时运行文档站 build。
