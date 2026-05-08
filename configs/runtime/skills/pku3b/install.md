---
name: pkuclaw-pku3b-install
description: pku3b raw-only CLI 的安装、构建、登录和环境排障
---

# pku3b 安装、构建与登录

本 skill 只在用户明确要求安装、构建、登录或排障 pku3b 时使用。不要在 loop 中自动安装、自动登录或写入凭据。

当前 pku3b 是 **raw-only JSON CLI**：不再有旧的人类终端命令、短别名、彩色输出、spinner 或交互式选择。

## 可用性检查

先按 `pku3b/usage.md` 的“pku3b 二进制解析”确定实际命令；这里不重复优先级。快速检查 repo-local 构建产物：

```bash
[ -x crates/pku3b/target/debug/pku3b ] && crates/pku3b/target/debug/pku3b --version || true
```

如果 repo-local 不存在，再按 `usage.md` 继续检查 `$PKU3B_BIN` 和 PATH。不要只因 PATH 中没有 `pku3b` 就报告 pku3b 不可用。

## 从仓库构建

需要用户同意后再执行：

```bash
cargo build --manifest-path crates/pku3b/Cargo.toml
crates/pku3b/target/debug/pku3b --version
```

Linux 若出现 OpenSSL/pkg-config 错误，需要用户安装系统开发包后重试，例如：

```bash
sudo apt-get update
sudo apt-get install -y pkg-config libssl-dev
```

不要在未确认时自动安装系统包。

## 登录初始化

新版不使用 `pku3b init`。首次使用或重置登录时运行：

```bash
pku3b auth login --username <id> --password <password> [--otp <code>]
```

命令会写入 pku3b 本地配置和 cookie。不要把账号、密码、OTP 写入仓库文件、runtime 文件、skill 文件或长日志；如果用户不想在 Codex 中输入凭据，请让用户在可信终端手动运行上述命令。

检查登录状态：

```bash
pku3b auth status
```

登出/清除 cookie：

```bash
pku3b auth logout
```

## 验证

登录后可运行只读命令确认。stdout 应是一条 JSON envelope，`ok=true` 表示命令成功：

```bash
pku3b --pretty auth status
pku3b --pretty assignments list --term current
pku3b --pretty announcements list --term current
pku3b --pretty timetable get
```

如果这些命令失败，读取 JSON envelope 中的 `errors[0].code`，常见分类：

- `invalid_args`：命令参数不符合新版 raw CLI；
- `auth_required` / `otp_required`：需要重新登录或补 OTP；
- `network_error`：网络或上游服务不可达；
- `parse_error`：教学网页面结构变化；
- `general_error`：其他错误，查看 `errors[0].message`。
