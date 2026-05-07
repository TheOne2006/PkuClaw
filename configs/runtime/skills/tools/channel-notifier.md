---
name: pkuclaw-channel-notifier
description: loop 通知文件队列用法；脚本只写入本地队列文件，由 daemon 扫描后通过 CoreRuntime/Feishu backend 发送
---

# Channel Notifier Skill

本 skill 只用于 `loop`。需要把 loop 结果展示给用户时，调用项目根目录下的单一通知队列脚本：

```bash
python scripts/pkuclaw_notify.py text --message "通知内容"
```

脚本不会联网、不会访问 localhost HTTP、不会直连飞书、不会解析 runtime target，也不会渲染卡片。它只在共享队列目录中创建一个随机文件名的 JSON job。daemon 每隔约 5 秒扫描队列，读取新 job，并由 CoreRuntime/Feishu backend 负责目标解析和发送。

## 环境变量

loop 进程会设置：

- `PKUCLAW_NOTIFY_QUEUE_DIR`：daemon 与脚本共享的通知队列目录；
- `PKUCLAW_LOOP_ID`：当前 loop id，用于 daemon 解析 loop-specific target override。

也可以在脚本参数中显式传 `--queue-dir` 和 `--loop-id` 覆盖。

## 发送文本

```bash
python scripts/pkuclaw_notify.py text --message "通知内容"
```

脚本默认会等待 daemon ack。stdout 输出 JSON；`ok=true` 表示 daemon 已确认发送成功。

## 发送结构化卡片

先把卡片 JSON 写入临时文件，再调用：

```bash
python scripts/pkuclaw_notify.py card --card-file /tmp/pkuclaw-card.json
```

## 发送图片

图片发送 v1 暂未实现。脚本会写入队列，daemon ack 会返回明确的 `ok=false` / `unsupported`：

```bash
python scripts/pkuclaw_notify.py image --image-path /path/to/image.png
```

## 更新卡片

```bash
python scripts/pkuclaw_notify.py update-card \
  --card-id <card_id> \
  --card-file /tmp/pkuclaw-card.json \
  --sequence 1
```

## 不等待 ack

只想确认 job 已写入队列时，可加：

```bash
python scripts/pkuclaw_notify.py --no-wait text --message "通知内容"
```

## 返回值

成功发送后的 stdout 示例：

```json
{"ok": true, "message": "text sent", "data": {"job_id": "..."}, "target": {}}
```

如果 `ok=false`，不要假设用户已收到通知；按 loop task 的失败策略记录或汇报。
