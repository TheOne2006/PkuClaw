# PkuClaw Codex Instructions

本文件是 PkuClaw 仓库内 Codex/Agent 的项目级操作规范。除非用户明确给出更高优先级指令，所有仓库维护、开发、发布工作都应遵守本文。

## 项目上下文

- PkuClaw 是面向 PKU 工作流的 daemon-centered study-agent runtime。
- 代码改动优先保持小步、可审查、可回滚。
- 涉及 runtime prompt、通知策略、channel outbox、loop/realtime 行为时，必须先阅读相关文档与测试，避免破坏现有契约。

## GitHub 产品发布工作流

本仓库采用 `main + develop + topic branch + PR` 的产品发布模型，不再采用 raw push 模型。

### 分支职责

- `main`
  - 稳定发布分支。
  - 始终代表可发布/已发布状态。
  - 不直接承接日常功能开发。
  - 只通过 release PR 或 hotfix PR 更新。
- `develop`
  - 日常集成分支。
  - 所有普通功能、重构、文档改进、非紧急修复先合并到这里。
  - 发布前从这里切出 release，或由这里发起到 `main` 的发布 PR。
- `codex/*` / `feat/*` / `fix/*` / `docs/*` / `refactor/*`
  - 具体功能或修复分支。
  - 默认从最新 `develop` 切出。
  - 完成后通过 PR 合并回 `develop`。
- `release/*`
  - 可选的发布冻结分支。
  - 从 `develop` 切出，只接受发布准备、版本号、文档、回归修复。
  - 最终 PR 到 `main`，发布后再同步回 `develop`。
- `hotfix/*`
  - 线上/正式版本紧急修复分支。
  - 从 `main` 切出。
  - 修复完成后 PR 到 `main`，并将同一修复同步回 `develop`。

### Codex 默认开发规则

1. 开始改代码前先运行：

   ```bash
   git status --short --branch
   git branch --show-current
   ```

2. 如果当前在 `main` 或 `develop`，不要直接开发；应从 `develop` 创建 topic branch。Codex 默认分支名前缀使用 `codex/`，例如：

   ```bash
   git checkout develop
   git pull origin develop
   git checkout -b codex/short-description
   ```

3. 如果用户明确要求特定分支名或前缀，按用户要求执行。
4. 不直接 push 到 `main` 或 `develop`，除非用户明确要求进行一次性 bootstrap/管理员操作。
5. 普通开发完成后：
   - commit 到 topic branch；
   - push topic branch；
   - 创建 PR，base branch 默认为 `develop`。
6. PR 进入 `develop` 前必须说明：
   - 改了什么；
   - 为什么改；
   - 风险和回滚方式；
   - 运行了哪些验证。

### 发布流程

简单发布：

```text
topic branch -> PR -> develop -> release PR -> main -> tag
```

需要冻结测试时：

```text
develop -> release/vX.Y.Z -> PR -> main -> tag
                         \-> back merge/cherry-pick -> develop
```

发布规则：

- `main` 合并发布 PR 后再打 tag。
- tag 使用语义化版本，例如 `v0.1.0`、`v0.1.1`。
- 发布 PR 只应包含已经在 `develop` 集成过的内容，避免临时塞入未验证功能。

### Hotfix 流程

```text
main -> hotfix/critical-fix -> PR -> main
                              \-> PR/cherry-pick -> develop
```

Hotfix 合并到 `main` 后必须同步到 `develop`，避免下一次发布回退修复。

### 推荐 GitHub 保护规则

仓库管理员应在 GitHub 上保护 `main` 和 `develop`：

- 禁止直接 push。
- 禁止 force push。
- 禁止删除分支。
- 合并前必须通过 PR。
- 合并前必须通过 CI。
- `main` 建议要求至少 1 个 approval；单人项目可在 bootstrap 阶段暂不强制，但发布前应开启。
- `develop` 至少要求 CI 通过；是否要求 review 可按阶段决定。

## 验证要求

Python/runtime 改动至少运行：

```bash
python -m compileall pkuclaw scripts
python -m unittest discover
```

文档站改动还应运行：

```bash
cd docs-site
npm install
npm run build
```

如果因为环境、凭据、网络或平台限制无法运行验证，最终回复和 PR 描述里必须明确说明。

## PR 内容规范

PR 应保持小而聚焦，避免混入无关格式化或临时文件。

PR 描述建议包含：

- Summary
- Why
- Changes
- Validation
- Risk / Rollback

提交前确认不会提交：

- `.env`、token、密钥、cookie；
- runtime data、logs、tmp；
- `node_modules/`、`.venv/`、构建产物；
- 与任务无关的大文件。

## PkuClaw 通知策略

- PkuClaw runtime 的 realtime run 默认只在当前对话中回复，不调用 Bark，也不发送 Channel Outbox 文本；只有需要交付本轮生成的图片或文件时，才按 channel outbox 规则发送 image/file。
- PkuClaw runtime 的 loop run 按 runtime Notification Policy 判断是否通知；需要通知时使用 Channel Outbox，由 daemon 按目标投递；不要额外使用 Bark。
- 普通 Codex 仓库维护/开发任务如不属于 PkuClaw realtime/loop runtime，应遵守当前会话更高优先级的通知要求。

