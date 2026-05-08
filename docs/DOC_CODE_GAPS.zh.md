# PkuClaw 文档 / 代码差异审计

审计日期：2026-05-08  
审计基线：`develop`，commit `643d8b3`（PR #2 合并后）  
范围：根 README、`ARCHITECTURE.md`、`docs/**`、`docs-site/**`、`configs/runtime/README.md`、runtime skills、`crates/pku3b/README.md` 与当前 Python/Rust 代码、测试、GitHub workflows。

## 本轮已处理的 gap

| 状态 | 差异 | 处理 |
| --- | --- | --- |
| ✅ 已修复 | 根 `README.md` 仍是英文入口，不符合“默认中文”的使用方式。 | 重写为中文默认 README，加入快速开始、架构图、配置地图、文档导航和安全边界。 |
| ✅ 已修复 | `docs/DEVELOPMENT.zh.md` 仍引用旧的 `tools/channel-notifier.md`、`scripts/pkuclaw_notify.py`、`card/update-card` 模型可见 API。 | 改为当前 `tools/channel-outbox.md` + `scripts/pkuclaw_outbox.py`；明确只支持 text/image/file。 |
| ✅ 已修复 | 文档站安装/配置页示例仍写 `sandbox = "workspace-write"`，但当前 `configs/config.example.toml`、`runtime.json` 和 Codex provider 默认契约是 `danger-full-access`。 | 文档站示例更新为 `danger-full-access`，并补充可信本地环境安全提示。 |
| ✅ 已修复 | `docs-site/README.md` 是英文且过短。 | 改为中文文档站维护说明，包含 `npm ci`、build、部署入口。 |
| ✅ 已修复 | `configs/runtime/skills/tasks/do-homework.md` 使用旧式 `AskUserQuestion` / “主 skill 创建 agent” 表达，当前 PkuClaw prompt 并不暴露这些 API。 | 改为自然语言确认、显式用户授权和可选宿主能力边界。 |
| ✅ 已修复 | `configs/runtime/skills/tools/pdf-reader.md` 含本地私有绝对路径示例。 | 改为占位路径，并补充缺依赖时不静默安装的说明。 |
| ✅ 已整理 | 文档入口分散，缺少维护分工说明。 | 新增 `docs/README.zh.md` 作为仓库文档索引。 |

## 当前仍需决策的 gap

| 优先级 | 差异 | 影响 | 建议 |
| --- | --- | --- | --- |
| P1 | `configs/runtime/runtime.json` 中仍包含一个具体 Feishu 默认通知目标；文档和 PR 模板均要求不要提交真实用户 target / 隐私数据。 | 可能泄露个人目标标识，也会让示例配置和生产配置混在一起。 | 若这是生产部署私有仓库可保留；若仓库公开或多人协作，建议把默认目标改为 `ou_xxx`，真实目标放入本地未提交配置或部署注入流程。 |
| P2 | 文档站 `editLink.baseUrl` 指向 `main`，但普通开发 workflow 要求 PR base 为 `develop`。 | 用户从文档站点“编辑此页”可能默认朝 `main` 发起修改。 | 若文档站只从 `main` 发布，这是可接受的；否则改为指向 `develop` 或在贡献文档中说明。 |
| P2 | GitHub CI 当前覆盖 Python 检查和 docs-site build，但未运行 `crates/pku3b` 的 `cargo test`。`crates/pku3b/README.md` 要求维护者手动运行 cargo 检查。 | Rust CLI 变更可能无法在 PR CI 中自动发现回归。 | 若 pku3b 是发布关键路径，建议新增 Rust CI job；否则在 PR 模板中明确 Rust 改动必须手动勾选 cargo 验证。 |
| P3 | 文档链接和 README 命令示例目前没有自动 link-check / smoke-test。 | 文档搬迁时可能出现断链或过期命令。 | 可后续添加 markdown link check，或在 docs build 中加入轻量链接检查。 |

## 当前代码与文档一致的关键契约

- 只有 `realtime` 与 `loop` 两类 Agent run。
- Quick action 来自 `configs/runtime/events.json`，会创建普通 `source = realtime` run。
- Skill source of truth 是 `configs/runtime/skills.json` + `configs/runtime/skills/**`；完整 skill body 不默认注入 prompt。
- Prompt 文案热读自 `configs/runtime/prompts.json`。
- Channel outbox 模型可见 API 只有 `text`、`image`、`file`，入口脚本是 `scripts/pkuclaw_outbox.py`。
- Outbox target 由 daemon 根据 run target、loop override、全局 notifications fallback 解析。
- Feishu card、card update、Markdown 渲染和资源上传是 channel/backend 内部实现，不应作为模型可见 API 写进 runtime prompt。
- 开发验证命令为 `python -m compileall pkuclaw scripts` 与 `python -m unittest discover`；文档站改动还需 `cd docs-site && npm ci && npm run build`。
