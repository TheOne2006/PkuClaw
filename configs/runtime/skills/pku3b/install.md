---
name: pkuclaw-pku3b-install
description: pku3b 的安装、构建、登录初始化和环境排障
---

# pku3b 安装与初始化

本 skill 只在用户明确要求安装、构建、登录或排障 pku3b 时使用。不要在 loop 中自动安装或自动登录。

## 可用性检查

```bash
command -v pku3b || true
[ -x crates/pku3b/target/debug/pku3b ] && crates/pku3b/target/debug/pku3b --version || true
```

优先使用 PATH 中的 `pku3b`；如果仓库内构建产物存在，也可以用于本仓库调试。

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

首次使用需要用户在可信交互终端中运行：

```bash
pku3b init
```

不要把账号、密码、OTP 写进脚本、日志、runtime 文件或 skill 文件。遇到 TTY/OTP/验证码问题时，停止自动流程并提示用户手动完成。

## 验证

初始化后可运行只读命令确认：

```bash
pku3b --version
pku3b a ls
pku3b ann ls
pku3b ct --raw
```

如果这些命令失败，将错误归类为 tool_missing、auth_required、network_error 或 upstream_error，交给 task 层解释给用户。
