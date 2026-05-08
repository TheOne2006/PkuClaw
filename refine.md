已盘点需要 refine 的文字入口，排除了 `docs-site/out`、`.next`、`dist`、`.venv`、`data`、`pkuclaw.egg-info` 等生成物。

## 文案 refine 清单

### Release / 项目总说明

- `/home/wtxy/workspace/Project/PkuClaw/README.md`
- `/home/wtxy/workspace/Project/PkuClaw/ARCHITECTURE.md`
- `/home/wtxy/workspace/Project/PkuClaw/agent.md`
- `/home/wtxy/workspace/Project/PkuClaw/AGENTS.md`
- `/home/wtxy/workspace/Project/PkuClaw/.github/pull_request_template.md`

### Runtime 说明与配置文案

- `/home/wtxy/workspace/Project/PkuClaw/configs/runtime/README.md`
- `/home/wtxy/workspace/Project/PkuClaw/configs/runtime/prompts.json`
- `/home/wtxy/workspace/Project/PkuClaw/configs/runtime/skills.json`
- `/home/wtxy/workspace/Project/PkuClaw/configs/runtime/events.json`
- `/home/wtxy/workspace/Project/PkuClaw/configs/runtime/runtime.example.json`

### Runtime skills

- `/home/wtxy/workspace/Project/PkuClaw/configs/runtime/skills/tasks/write-notes.md`
- `/home/wtxy/workspace/Project/PkuClaw/configs/runtime/skills/tasks/do-homework.md`
- `/home/wtxy/workspace/Project/PkuClaw/configs/runtime/skills/tasks/sync-notices.md`
- `/home/wtxy/workspace/Project/PkuClaw/configs/runtime/skills/tools/channel-outbox.md`
- `/home/wtxy/workspace/Project/PkuClaw/configs/runtime/skills/tools/data-parser.md`
- `/home/wtxy/workspace/Project/PkuClaw/configs/runtime/skills/tools/pdf-reader.md`
- `/home/wtxy/workspace/Project/PkuClaw/configs/runtime/skills/runtime/runtime-config.md`
- `/home/wtxy/workspace/Project/PkuClaw/configs/runtime/skills/runtime/skill-authoring.md`
- `/home/wtxy/workspace/Project/PkuClaw/configs/runtime/skills/pku3b/install.md`
- `/home/wtxy/workspace/Project/PkuClaw/configs/runtime/skills/pku3b/usage.md`

### LaTeX note template 文案

- `/home/wtxy/workspace/Project/PkuClaw/configs/runtime/templates/latex/course-note/README.md`
- `/home/wtxy/workspace/Project/PkuClaw/configs/runtime/templates/latex/course-note/note.tex`
- `/home/wtxy/workspace/Project/PkuClaw/configs/runtime/templates/latex/course-note/chapter.tex`

### pku3b 说明

- `/home/wtxy/workspace/Project/PkuClaw/crates/pku3b/README.md`

### docs 目录

- `/home/wtxy/workspace/Project/PkuClaw/docs/README.zh.md`
- `/home/wtxy/workspace/Project/PkuClaw/docs/DEVELOPMENT.zh.md`
- `/home/wtxy/workspace/Project/PkuClaw/docs/DOC_CODE_GAPS.zh.md`

### docs-site 源文档

- `/home/wtxy/workspace/Project/PkuClaw/docs-site/README.md`
- `/home/wtxy/workspace/Project/PkuClaw/docs-site/content/docs/index.mdx`
- `/home/wtxy/workspace/Project/PkuClaw/docs-site/content/docs/architecture.mdx`
- `/home/wtxy/workspace/Project/PkuClaw/docs-site/content/docs/runtime.mdx`
- `/home/wtxy/workspace/Project/PkuClaw/docs-site/content/docs/skills.mdx`
- `/home/wtxy/workspace/Project/PkuClaw/docs-site/content/docs/configuration.mdx`
- `/home/wtxy/workspace/Project/PkuClaw/docs-site/content/docs/quickstart.mdx`
- `/home/wtxy/workspace/Project/PkuClaw/docs-site/content/docs/quick-actions.mdx`
- `/home/wtxy/workspace/Project/PkuClaw/docs-site/content/docs/installation.mdx`
- `/home/wtxy/workspace/Project/PkuClaw/docs-site/content/docs/development.mdx`
- `/home/wtxy/workspace/Project/PkuClaw/docs-site/content/docs/contributing.mdx`
- `/home/wtxy/workspace/Project/PkuClaw/docs-site/content/docs/faq.mdx`
- `/home/wtxy/workspace/Project/PkuClaw/docs-site/content/docs/reference/config-files.mdx`

## 建议 refine 顺序

1. `README.md`：先把产品定位、安装、核心 workflow 统一。
2. `ARCHITECTURE.md` + docs-site `architecture.mdx`：统一架构叙事。
3. Runtime：`configs/runtime/README.md`、`prompts.json`、`skills.json`。
4. Skills：先 `write-notes.md`，再 tasks/tools/pku3b skills。
5. docs-site：按页面同步 root docs 的新叙事。
6. `pku3b/README.md` 和开发文档收尾。

Bark 通知未成功：本地发送因 DNS/network 失败；随后按规则申请网络发送，但该外发通知被安全审查拒绝，所以没有静默重试。

::git-create-pr{cwd="/home/wtxy/workspace/Project/PkuClaw" branch="develop" url="https://github.com/TheOne2006/PkuClaw/pull/9" isDraft=true}