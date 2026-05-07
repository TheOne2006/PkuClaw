---
name: pkuclaw-runtime-skill-authoring
description: 新增、拆分或修改 PkuClaw runtime skills 的规范
---

# PkuClaw Skill 编写规范

本 skill 只在用户明确要求新增、拆分、重写或整理 runtime skills 时使用。

## 当前分层

```text
configs/runtime/skills/
  runtime/    # PkuClaw 自身运行时/skill/prompt/config 的 meta 说明
  pku3b/      # pku3b 安装和使用说明
  tasks/      # 面向用户的学习/课程任务
  tools/      # 非 pku3b 的通用辅助能力，如 PDF、数据解析
```

## 分层规则

- `runtime/`：只描述如何安全改 PkuClaw 自己；不写课程业务流程。
- `pku3b/`：只描述工具安装和使用；不承载同步通知、做作业、整理笔记的任务逻辑。
- `tasks/`：只描述用户任务目标、输入输出、确认边界和默认数据流。
- `tools/`：通用辅助能力；只有多个 task 共用时才放这里。

## Catalog 规则

每个 skill 必须登记到 `configs/runtime/skills.json`，字段包括：

- `name`：建议等于 markdown path；
- `path`：相对 `configs/runtime/skills/` 的 markdown 路径；
- `description`：一句话说明何时使用；
- `dependencies`：只放真正需要默认读取的 skill；
- `allowed_sources`：默认 task 可是 `realtime`，loop 只允许静默安全任务；
- `requires_confirmation`：修改配置、安装工具、提交作业、删除/覆盖重要数据时设为 true；pku3b 只读 live/cache 查询可不设确认，但要在 skill 中写清授权和失败边界。

## 编写风格

- skill 只写“怎么做”和“边界”，不要塞长篇背景。
- 高风险动作必须明确需要用户确认。
- task 默认不要直接依赖具体 CLI；例外是 pku3b 作为教学网访问层时，task 可调用其 raw JSON 只读命令，并把结果归一化为 PkuClaw 业务 snapshot/state。
- 不把 sub-agent 当作 skill。sub-agent 是宿主/runtime 能力，只有用户明确要求且环境真实提供时才使用。

## 验证

修改 skill 后至少检查：

```bash
python - <<'PY'
from pathlib import Path
from pkuclaw.runtime.skills import load_skill_registry
root = Path('configs/runtime')
reg = load_skill_registry(root / 'skills.json', skills_dir=root / 'skills')
print(reg.warnings)
print(list(reg.skills))
PY
```

并确认 `skills.json` 中所有 path 都存在。
