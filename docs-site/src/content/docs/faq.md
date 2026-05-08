---
title: FAQ
description: PkuClaw 常见问题。
---

## PkuClaw 是 AutoPku 吗？

不是。PkuClaw 当前目标是一个面向 PKU workflow 的 study-agent runtime，重点是 realtime/loop 运行模型、runtime 文件、skill catalog 和渠道通知链路。

## 为什么不直接把所有 skill 注入 prompt？

因为这会放大上下文、增加误用风险，也会让 prompt 变得难以审计。PkuClaw 只注入 Skill Catalog 元数据，Agent 需要时再读取具体 skill 文件。

## quick action 和 loop 有什么区别？

quick action 是用户主动点击或触发的 realtime task，会流式回复用户。loop 是后台定时任务，默认静默，只在重要变化时通知。

## 为什么 outbox 用文件队列？

文件队列简单、可审计、便于 daemon 统一处理目标解析和 channel backend 投递。Agent 脚本不需要知道飞书 API、target id 或卡片格式。

## 可以不用飞书吗？

架构上可以。飞书是当前 channel adapter 的重点，后续可以增加其他 channel，只要保持 core/runtime 与 channel backend 解耦。

## 文档站怎么本地预览？

```bash
cd docs-site
npm ci
npm run dev
```

构建静态站点：

```bash
npm run build
```
