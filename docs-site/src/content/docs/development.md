---
title: 开发者指南
description: PkuClaw 代码归属、prompt/runtime 变更和测试检查。
---

本页面向准备修改 PkuClaw 代码或 runtime 文件的开发者。

## 代码归属

```text
pkuclaw/
  core/         # run orchestration、LoopManager、Store、共享模型
  runtime/      # runtime 文件 loader：config/events/prompts/skills
  agents/       # AgentWrapper、Codex provider、sink、artifact
  channels/     # 平台 adapter：事件转换、流式展示、卡片详情
  notify_queue/ # daemon 文件通知队列 worker
scripts/        # outbox 脚本 thin clients
```

不要新增顶层 `runtime_*.py`、`code_agents/` 或业务 connector 包。新逻辑应放入对应层。

## Prompt 修改

Prompt 文案优先修改：

```text
configs/runtime/prompts.json
```

而不是硬编码进 `pkuclaw/agents/wrapper.py`。

修改后至少检查：

- realtime prompt 不包含 loop-only 信息；
- realtime prompt 不包含通知脚本；
- loop prompt 不复用 realtime 回复规则；
- loop prompt 指向 Channel Outbox Skill；
- Skill Catalog 来自 `configs/runtime/skills.json`。

## Runtime 修改

Runtime 文件是普通可编辑文件：

```text
configs/runtime/runtime.json
configs/runtime/events.json
configs/runtime/prompts.json
configs/runtime/skills.json
configs/runtime/skills/**
```

修改时建议保持：

- JSON 格式稳定；
- schema_version 不乱改；
- 真实通知目标、凭据和隐私数据不要进入示例或文档；
- loop 行为默认静默，重要变化才通知。

## 文档维护地图

仓库级入口和审计文档在根目录：

- `README.md`：中文默认入口和快速开始；
- `docs/README.zh.md`：仓库内文档索引；
- `docs/DOC_CODE_GAPS.zh.md`：文档与当前代码的差异报告。

## 测试命令

```bash
python -m compileall pkuclaw scripts
python -m unittest discover
```

文档站修改还应运行：

```bash
cd docs-site
npm ci
npm run build
```

## 开发 workflow

<div class="pkuclaw-steps">
  <div class="pkuclaw-step"><strong>1. 明确边界：</strong>判断修改属于 core、runtime、agents、channels 还是 scripts。</div>
  <div class="pkuclaw-step"><strong>2. 小步提交：</strong>先改最小闭环，避免同时重构多个层。</div>
  <div class="pkuclaw-step"><strong>3. 本地验证：</strong>运行 Python 检查，文档改动运行 Astro build。</div>
  <div class="pkuclaw-step"><strong>4. 更新文档：</strong>行为变更同步更新 Starlight 文档和 runtime README。</div>
</div>
