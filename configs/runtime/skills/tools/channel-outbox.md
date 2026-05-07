---
name: pkuclaw-channel-outbox
description: 通用 channel outbox 文件队列；模型只发送 text/image/file，daemon 解析目标，channel adapter 处理平台渲染
---

# Channel Outbox Skill

本 skill 可用于 `realtime` 和 `loop`，只暴露三个模型可见能力：

- `send_text(title?, text)`
- `send_image(path, caption?)`
- `send_file(path, caption?)`

不要向模型暴露或使用 `send_card`、`update_card`、`card_id`、Feishu CardKit、`open_id`、`chat_id` 或任何 target 参数。卡片创建、卡片更新、Markdown 渲染和平台差异都是 runtime/channel adapter 的内部实现。

## 使用边界

- `realtime` 已经有运行中的飞书流式卡片；不要在用户未要求时额外发送 text 来重复最终回答。
- `realtime` 可以使用 image/file 发送本轮生成的图片、PDF、压缩包、笔记文件等交付产物。
- `loop` 需要通知用户时按 Notification Policy 发送一条简洁、可执行的 text/image/file 消息。
- 发送脚本只写本地 outbox 队列，不联网、不直连飞书、不解析目标、不渲染卡片。

## 环境变量

Agent 进程会设置：

- `PKUCLAW_OUTBOX_QUEUE_DIR`：daemon 与脚本共享的 outbox 队列目录；
- `PKUCLAW_RUN_ID`：当前 run id，用于 daemon 解析 realtime/loop 原始 channel target；
- `PKUCLAW_RUN_SOURCE`：当前 run source，值为 `realtime` 或 `loop`；
- `PKUCLAW_LOOP_ID`：仅 loop 进程设置，用于 loop target override fallback。

脚本也支持 `--queue-dir`、`--run-id`、`--run-source`、`--loop-id` 显式覆盖；不要传 channel/target 参数。

## 发送文本

```bash
python scripts/pkuclaw_outbox.py text --text "**今天有作业**\n- xxx\n- yyy" --title "课程提醒"
```

`--title` 可省略；Feishu adapter 会把文本渲染为 Markdown 卡片，其他 channel 可忽略 title 或把它渲染为第一行。

## 发送图片

```bash
python scripts/pkuclaw_outbox.py image --path /path/to/image.png --caption "生成结果图"
```

`--caption` 可省略；caption 的具体展示方式由 channel adapter 决定。

## 发送文件

```bash
python scripts/pkuclaw_outbox.py file --path /path/to/result.pdf --caption "完整笔记 PDF"
```

`--caption` 可省略。脚本会记录本地文件路径；daemon/channel adapter 负责上传和发送。

## 不等待 ack

只想确认 job 已写入队列时，可加：

```bash
python scripts/pkuclaw_outbox.py --no-wait text --text "通知内容"
```

## 返回值

成功发送后的 stdout 示例：

```json
{"ok": true, "message": "text sent", "data": {"job_id": "..."}, "target": {}}
```

如果 `ok=false`，不要假设用户已收到消息；按当前任务的失败策略记录或汇报。
