# PkuClaw 文档站

本目录是 PkuClaw 的 Next.js + Fumadocs 文档站。站点内容以中文为默认语言，面向使用指南与开发者指南两条平行文档路径。

在线地址：https://theone2006.github.io/PkuClaw/

## 本地预览

```bash
cd docs-site
npm ci
npm run dev
```

本地开发默认使用端口 `4321`；由于 GitHub Pages 配置了 base path，请打开：

```text
http://localhost:4321/PkuClaw/
```

## 构建检查

```bash
cd docs-site
npm ci
npm run build
```

静态导出结果写入 `docs-site/out`。

## 发布

GitHub Pages 部署由 `.github/workflows/deploy-docs.yml` 触发：

- `main` 分支上 `docs-site/**`、根 README、架构/开发文档等变化会构建并发布；
- 手动触发可使用 `workflow_dispatch`；
- Next.js 配置中 `basePath` 固定为 `/PkuClaw`，对应站点路径 `https://theone2006.github.io/PkuClaw/`。

## 维护约定

- 使用者文档放在 `content/docs/user-guide/`，开发者文档放在 `content/docs/developer-guide/`，两条路径保持平行，不混排。
- 根目录 `README.md` 只做快速介绍、快速安装和文档入口，不承载完整开发/审计文档。
- 不再默认使用根目录 `docs/` 作为文档入口；如果未来确实需要临时审计报告，先创建对应文件或迁移进文档站后再链接。
- 示例中不要写真实 app secret、token、cookie、open_id/chat_id。
- 修改文档站后优先使用 `npm ci` 保持 lockfile 可复现。
