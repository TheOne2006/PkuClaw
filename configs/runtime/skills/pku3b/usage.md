---
name: pkuclaw-pku3b-usage
description: pku3b 的常用只读命令、输出注意事项和高风险命令边界
---

# pku3b 使用方法

本 skill 只说明 pku3b 的命令使用和风险边界。业务任务仍由 `tasks/*` 决定；pku3b 不是 loop 默认执行器。

## 只读命令

```bash
# 作业
pku3b a ls
pku3b a ls --all-term
pku3b a -f ls --all-term

# 公告
pku3b ann ls
pku3b ann ls --all-term
pku3b ann show <ID>

# 课表
pku3b ct
pku3b ct --raw

# 选课信息（只读查看）
pku3b s -d major show
```

## 输出注意事项

pku3b 是面向终端的 CLI，输出可能包含：

- ANSI 颜色码；
- 进度条和刷新控制字符；
- 缓存导致的新旧数据差异；
- 登录、OTP、验证码、网络错误等非业务状态。

不要让 task 直接把原始输出当成稳定事实。若要长期使用，应由 collector/wrapper 归一化为：

```text
data/pkuclaw/course-sync/parsed/latest.json
```

## 高风险命令

以下命令必须得到用户明确确认，loop 不得自动执行：

```bash
pku3b a submit <ID> <file>
pku3b a sb <ID> <file>
pku3b a download <ID> -d <dir>
pku3b cache clean
```

## 和 tasks 的关系

- `tasks/sync-notices.md` 默认读取快照；缺少快照或用户要求 live 抓取时，才参考本 skill。
- `tasks/do-homework.md` 默认处理本地材料；只有用户要求查询/提交教学网作业时，才参考本 skill。
- `tasks/write-notes.md` 通常不需要 pku3b，除非用户要求从教学网拉取课程资料。
