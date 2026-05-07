---
name: pkuclaw-pku3b-usage
description: pku3b raw-only JSON CLI 的常用命令、输出结构和高风险边界
---

# pku3b 使用方法

本 skill 只说明 pku3b 的命令使用、live/cache 语义和风险边界。业务任务仍由 `tasks/*` 决定；PkuClaw 可以在 Realtime 和 loop 中直接调用 pku3b 只读命令，pku3b 自行决定是走网络、typed cache，还是 artifact cache。

## PkuClaw 调用模型

- 对 PkuClaw 来说，`pku3b <read-only command>` 表示“获取当前可用教学网数据”；不要在 PkuClaw 侧臆测数据来自网络还是 cache。
- pku3b 负责底层 cache：metadata/typed cache、cookie、附件/回放 artifact cache，以及下载后返回本地路径的稳定 JSON contract。
- PkuClaw 只维护业务状态：例如课程通知 diff、摘要和 `data/pkuclaw/course-sync` 下的 latest/state 文件。
- 如需强制绕过 pku3b typed cache，只有在用户明确要求刷新时使用 `--refresh`。
- loop 可以使用只读命令；不要在 loop 中自动安装、登录、登出、写配置、清缓存、提交作业或下载大附件/回放。

## 授权与提权

只读 pku3b 命令常需要访问 PKU 教学网。若命令因 sandbox/network 被阻塞，可以用 `require_escalated` 重新请求一次，justification 必须说明**精确命令**和**只读目的**。不要绕过审批；如果授权被拒，停止 live 步骤并报告需要用户授权或手动处理。

登录、登出、写配置、清缓存、提交作业、大附件/回放下载不应自动提权；这些动作需要用户明确触发，并在目标核对后执行。

## 输出约定

新版 pku3b 是 raw-only CLI：

- stdout 永远输出 JSON envelope；
- stderr 只用于日志；
- 无彩色、无 spinner、无交互选择；
- 缺少 `--id`、`--file`、`--out-dir` 等参数时直接返回 JSON 错误；
- 旧短别名和旧命令已删除：`a`、`ann`、`ct`、`v`、`s`、`b`、`tt`、`th`、`init` 不再使用。

成功 envelope：

```json
{"ok": true, "data": {}, "warnings": [], "errors": [], "meta": {"schema_version": 1, "generated_at": "..."}}
```

失败 envelope：

```json
{"ok": false, "data": null, "warnings": [], "errors": [{"code": "auth_required", "message": "...", "recoverable": true}], "meta": {"schema_version": 1, "generated_at": "..."}}
```

全局参数：

```bash
pku3b --pretty <command>       # pretty JSON
pku3b --refresh <command>      # 绕过 pku3b typed cache（支持的抓取命令）
```

## 只读命令

```bash
# 登录状态
pku3b auth status

# 配置查看
pku3b config get
pku3b config get username
pku3b config get password

# 缓存状态
pku3b cache status

# 作业
pku3b assignments list --term current
pku3b assignments list --term all

# 公告
pku3b announcements list --term current
pku3b announcements list --term all
pku3b announcements get --id <announcement_id> --term current
pku3b announcements get --id <announcement_id> --term all

# 课表
pku3b timetable get

# 课程回放
pku3b videos list --term current
pku3b videos list --term all
```

## 会写本地文件或改变远端状态的命令

以下命令只有在用户明确要求并确认目标后才能执行；loop 不得自动执行：

```bash
# 登录/配置/cookie
pku3b auth login --username <id> --password <password> [--otp <code>]
pku3b auth logout
pku3b config set username <id>
pku3b config set password <password>
pku3b cache clean

# 下载附件到本地目录
pku3b assignments download --id <assignment_id> --out-dir <dir> --term current
pku3b assignments download --id <assignment_id> --out-dir <dir> --term all

# 提交作业到教学网（高风险）
pku3b assignments submit --id <assignment_id> --file <path>

# 下载课程回放到本地目录，要求系统 PATH 中有 ffmpeg
pku3b videos download --id <video_id> --out-dir <dir> --term current
pku3b videos download --id <video_id> --out-dir <dir> --term all
```

下载类命令的期望 contract 是：若 pku3b 已有可用 artifact cache，可直接返回本地路径；否则下载完成后返回本地路径。PkuClaw 不应重新实现这一层 cache，只消费 pku3b JSON 中的 `path`/`files`。

作业提交必须同时满足：用户明确确认、作业 ID 与文件路径已核对、最终文件已通过本地检查。不要在 loop、自动监控或未确认场景中提交。

## 已删除能力

不要再建议或调用以下旧能力：

```text
syllabus / 选课
autoelect
ttshitu
bark
thesislib
人类交互选择
旧短别名 a / ann / ct / v / s / b / tt / th
```

## 和 tasks 的关系

- `tasks/sync-notices.md` 默认 live 调 pku3b 只读命令获取当前可用数据，并把结果归一化为 PkuClaw 业务 snapshot/state。
- `tasks/do-homework.md` 默认处理本地材料；用户要求查询、下载或提交教学网作业时，参考本 skill。
- `tasks/write-notes.md` 通常不需要 pku3b，除非用户要求从教学网拉取课程资料或回放。
