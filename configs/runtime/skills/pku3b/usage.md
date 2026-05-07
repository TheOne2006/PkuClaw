---
name: pkuclaw-pku3b-usage
description: pku3b raw-only JSON CLI 的常用命令、输出结构和高风险边界
---

# pku3b 使用方法

本 skill 只说明 pku3b 的命令使用和风险边界。业务任务仍由 `tasks/*` 决定；pku3b 可以作为确定性 snapshot collector 的底层工具，但 loop 不应临时处理登录、安装或凭据问题。

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

- `tasks/sync-notices.md` 默认读取稳定快照；需要 live 抓取时，可用本 skill 作为 snapshot collector 的命令参考。
- `tasks/do-homework.md` 默认处理本地材料；只有用户要求查询、下载或提交教学网作业时，才参考本 skill。
- `tasks/write-notes.md` 通常不需要 pku3b，除非用户要求从教学网拉取课程资料或回放。
