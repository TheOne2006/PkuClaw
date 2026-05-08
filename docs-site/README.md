# PkuClaw 文档站

这里是 PkuClaw 的 Astro Starlight 文档站。站点内容以中文为默认语言，面向安装、配置、runtime 概念和开发者入门。

## 本地预览

```bash
cd docs-site
npm ci
npm run dev
```

## 构建检查

```bash
cd docs-site
npm ci
npm run build
```

## 发布

GitHub Pages 部署由 `.github/workflows/deploy-docs.yml` 触发：

- `main` 分支上 `docs-site/**`、根 README、架构/开发文档等变化会构建并发布；
- 手动触发可使用 workflow_dispatch；
- Astro 配置中 `base` 固定为 `/PkuClaw`，对应站点路径 `https://theone2006.github.io/PkuClaw/`。

## 维护约定

- 用户向导、安装、配置、概念页放在 `src/content/docs/`。
- 仓库内部审计和维护报告放在根目录 `docs/`，必要时从站点链接过去。
- 示例中不要写真实 app secret、token、cookie、open_id/chat_id。
- 修改文档站后优先使用 `npm ci` 保持 lockfile 可复现。
