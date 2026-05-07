---
name: pkuclaw-task-write-notes
description: 六阶段课程笔记流水线：PDF 讲义读取、Markdown 笔记、Notion 汇总、LaTeX 工程、逐章精修、补图和最终 QA
---

# 任务：课程笔记生成

这个 task 是 PkuClaw 的课程笔记工作流。它不再是一次性“读 PDF 后生成一份摘要”，而是一个可暂停、可恢复、可审计的六阶段笔记生产线。

它可以被三种入口调用：

- CLI：`pkuclaw notes <course>`
- 飞书 Bot：例如“继续生成多智能体基础笔记”
- Codex Worker：后台执行长任务，并把阶段状态写回 PkuClaw job store

旧版 `write-notes.md` 中的 PDF 读取、Markdown 组织、Pandoc/LaTeX 踩坑经验仍然保留为实现参考；新的主流程以“阶段门控”为核心。

## 总原则

1. **阶段隔离**：每个阶段只做本阶段允许的事情，不提前生成后续产物。
2. **先盘点再写入**：阶段 0 只检查结构，不修改文件。
3. **Markdown 与 LaTeX 分离**：先生成中文 Markdown 讲义，再搭建 LaTeX 工程。
4. **LaTeX 精修与补图分离**：阶段 4 只精修章节结构和文字，阶段 5 才补真实图片。
5. **来源可追溯**：每份笔记、每张图、每个章节都保留来源 PDF 文件名；不在正文里保留页码噪声。
6. **内容不幻觉**：不要凭空添加原讲义没有的定理、结论、例子；必要补充必须标注“补充理解”。
7. **可恢复**：每阶段完成后更新阶段报告，后续可从最近完成阶段继续。
8. **用户确认**：从飞书或 CLI 触发时，阶段 0 报告后默认等待确认；后台自动任务只能继续已确认的阶段。

## 推荐目录结构

课程目录由调用方传入，记为 `{course_dir}`。例如：

```text
workspace/Notes/多智能体基础
```

目标结构：

```text
{course_dir}/
├── lectures/                      # 原始 PDF，若已有其他名称，阶段 0 只报告不移动
├── notes_md/                      # 每个 PDF 对应一份中文 Markdown 讲义
├── chapters/                      # 每个 Lecture 对应一份 LaTeX chapter
├── figures/                       # 裁图或重绘图片
│   └── FIGURES.md                 # 图片来源表
├── SUMMARY.md                     # Markdown 阶段总表
├── README.md                      # LaTeX 工程说明
├── note.tex                       # LaTeX 主入口
├── note.pdf                       # 编译产物
├── {course_name}_汇总笔记.md       # Notion 用汇总 Markdown
└── .pkuclaw/
    └── note_job.json              # 阶段状态、输入 hash、输出清单
```

如果课程目录已经有不同结构，阶段 0 只提出映射建议，不擅自移动用户文件。

## 阶段状态

PkuClaw Core 可以把状态写入 `{course_dir}/.pkuclaw/note_job.json`：

```json
{
  "course": "多智能体基础",
  "current_phase": 2,
  "confirmed_until_phase": 2,
  "source_pdfs": [
    {
      "file": "lecture01.pdf",
      "sha256": "...",
      "lecture": "Lecture 1",
      "title": "..."
    }
  ],
  "outputs": {
    "notes_md": [],
    "chapters": [],
    "figures": []
  },
  "last_report": "..."
}
```

这个文件是运行状态，不是正文内容；如果没有 PkuClaw Core，手工执行时可只在最终报告里说明阶段进度。

## 阶段 0：盘点，不动文件

阶段 0 只检查文件结构，不修改任何文件。

必须检查：

1. 原始讲义 PDF 在哪里；
2. 是否已有 Markdown 笔记；
3. 是否已有 LaTeX 模板或 `note.tex`；
4. 是否已有 `chapters/`、`figures/`、`README.md`、`SUMMARY.md`；
5. 是否有可参考模板，例如相邻课程的 LaTeX 工程；
6. 是否已有旧版 PkuClaw 输出；
7. 是否存在疑似重复 PDF、扫描版 PDF、无文本层 PDF；
8. 如果缺少某些结构，只提出建议，不创建。

阶段 0 报告格式：

```markdown
## 阶段 0 盘点报告

- 课程目录：
- 原始 PDF 列表：
- 已有 Markdown：
- 已有 LaTeX 工程：
- 可参考模板：
- 建议输出结构：
- 后续阶段会创建或修改的文件：
- 风险：
```

阶段 0 禁止：

- 转换 PDF；
- 生成笔记；
- 创建目录；
- 写 LaTeX；
- 裁图。

## 阶段 1：逐个 PDF 生成中文 Markdown 讲义

读取 `{course_dir}` 下所有讲义 PDF。PDF 可以来自 `lectures/`，也可以来自阶段 0 确认的其他目录。

输出：

```text
{course_dir}/notes_md/{pdf_stem}.md
{course_dir}/SUMMARY.md
```

要求：

1. 每个 PDF 单独生成一个中文 Markdown 讲义文件。
2. 必须完整阅读每个 PDF，不要只做摘要。
3. 按讲义逻辑重新组织成中文课堂笔记，而不是逐页机械翻译。
4. 不保留 `Page 1`、`第 x 页`、`原讲义第 x 页` 之类页码标记。
5. 可以合并连续页面中的同一主题。
6. 中文为主，英文专业名词第一次出现时保留英文，例如：多智能体系统（Multi-Agent System）。
7. 不凭空添加原讲义没有的定理、结论或例子。
8. 如果需要补充理解，明确标注“补充理解”。
9. 定义、定理、例子、证明、备注使用统一格式。
10. 数学公式使用 LaTeX：行内 `$...$`，独立公式用 `$$...$$`。
11. 图无法直接转换时，保留内容性占位：`[图：关于 xxx 的示意图]`，不要写页码。
12. 表格尽量转为 Markdown 表格。

Markdown 结构：

```markdown
# Lecture 标题

## 本讲概览

## 1. ...

### 1.1 ...

> **定义：**
> ...

> **定理：**
> ...

> **例子：**
> ...

> **证明思路：**
> ...

> **备注：**
> ...
```

`SUMMARY.md` 列出：

- Lecture 标题；
- 原 PDF 文件名；
- 输出 Markdown 文件名；
- 简短主题说明；
- 是否含图占位；
- 是否存在 PDF 提取异常。

阶段 1 只生成 `notes_md/*.md` 和 `SUMMARY.md`，不要做 LaTeX。

### PDF 读取参考

优先使用 PyMuPDF 快速读取文本：

```python
import fitz

doc = fitz.open(pdf_path)
texts = []
for page in doc:
    texts.append(page.get_text())
doc.close()
```

表格多的 PDF 可补充使用 `pdfplumber`。扫描版 PDF 需要 OCR，不能假装已经完整读取。

## 阶段 2：生成 Notion 用汇总 Markdown

把 `notes_md/` 下所有单独 Markdown 笔记按 Lecture 顺序合并成一个总文件。

输出：

```text
{course_dir}/{course_name}_汇总笔记.md
```

要求：

1. 不改写内容，只做必要的顺序整理和标题层级衔接。
2. 每个 Lecture 之间用清晰分隔：

   ```markdown
   ---

   # Lecture X：标题
   ```

3. 不加入 LaTeX 封面、目录、PDF 专用说明。
4. 保留公式、表格、定义、定理、例子、备注格式。
5. 不保留原 PDF 页码。
6. 检查是否所有 `notes_md/*.md` 都已合并。

阶段 2 报告：

- 合并了多少个文件；
- 输出文件路径；
- 是否发现标题重复；
- 是否发现顺序异常；
- 是否有缺失 Lecture。

## 阶段 3：搭建 LaTeX 讲义工程

参考同一 Notes 根目录下已有课程模板，优先参考用户指定模板。例如：

```text
workspace/Notes/自然语言处理基础
```

输出或整理：

```text
{course_dir}/note.tex
{course_dir}/chapters/*.tex
{course_dir}/figures/
{course_dir}/README.md
{course_dir}/note.pdf
```

要求：

1. 每个 Lecture 单独生成一个 `chapters/*.tex` 文件。
2. 不做双重标题：`chapter` 标题可以写 Lecture 编号和主题；`section` 不要机械重复 Markdown 原编号。
3. 每章开头只保留来源信息：
   - 原 PDF 文件名；
   - Lecture 几；
   - 不写完整路径；
   - 不写页码。
4. 不额外生成复杂封面，除非模板已有简洁封面。
5. 使用适合教材讲义的彩色框：定义、结论/定理、例子、备注、证明思路。
6. 不完全套数学笔记模板里不适合的 theorem 风格；课程概念、机制、算法、例子更重要。
7. 图暂时可以继续保留占位，统一为：

   ```latex
   \begin{figuredesc}
   ...
   \end{figuredesc}
   ```

8. 公式必须能被 `xelatex` 编译。
9. 中文排版自然，不像自动翻译。

LaTeX 主文件建议包含：

```latex
\documentclass[UTF8,openany]{ctexbook}
\usepackage{amsmath,amssymb,mathtools}
\usepackage[most]{tcolorbox}
\usepackage{graphicx}
\usepackage{tabularx}
\usepackage{hyperref}

\newenvironment{figuredesc}
  {\begin{tcolorbox}[colback=gray!5,colframe=gray!50,title={图示占位}]}
  {\end{tcolorbox}}

\newcommand{\notefigure}[3]{%
  \begin{figure}[htbp]
    \centering
    \includegraphics[width=#1\linewidth]{figures/#2}
    \caption{#3}
  \end{figure}
}
```

阶段 3 必须尝试编译 `note.tex` 并报告：

- 生成了哪些文件；
- 是否成功编译；
- PDF 页数；
- LaTeX log 中是否有 `Overfull`、`Underfull`、`Undefined`、`Missing`、`LaTeX Warning`。

## 阶段 4：逐章精修 LaTeX

阶段 4 不补图，不裁图，不重绘图。只精修 LaTeX 结构、文字、公式、表格。

每次精修 2-3 个 chapter，然后编译检查一次。全部完成后，再完整编译 `note.tex`。

重点检查：

1. 是否有双重标题、重复编号、重复 Lecture 名。
2. 每章标题是否自然，例如：`\chapter{Lecture 3：机制设计与博弈均衡}`。
3. 每章开头是否只保留来源和 Lecture 信息。
4. `section` / `subsection` 是否交给 LaTeX 自动编号，不保留 Markdown 的 `1.`、`1.1` 前缀。
5. 定义、结论、例子、备注、证明思路是否用统一彩色框。
6. 公式是否完整，括号是否配平，LaTeX 是否能编译。
7. 表格是否过宽，必要时改成 `tabularx`。
8. 长英文术语是否第一次出现有中英对照。
9. 内容是否像课堂讲义，而不是机械翻译。
10. 不删除实质内容。

阶段 4 报告：

- 改了哪些 chapter；
- 修复了哪些主要问题；
- 编译是否通过；
- 还有哪些遗留问题。

## 阶段 5：一张一张看原 PDF，补齐有用图片

阶段 5 专门处理图片。它必须在阶段 4 完成之后执行。

输出：

```text
{course_dir}/figures/*.png
{course_dir}/figures/FIGURES.md
```

要求：

1. 图片统一放入 `figures/`。
2. PNG 命名统一：

   ```text
   原pdf名_fig三位序号_英文短名.png
   ```

   示例：

   ```text
   lecture03_game_theory_fig001_payoff_matrix.png
   ```

3. 优先使用原 PDF 中的清晰截图或裁图。
4. 如果原图太糊、裁出来很丑、文字太碎，允许重绘。
5. 重绘优先用程序画图、TikZ、Python 或矢量方式。
6. 不让图生成模型生成精确公式、大量文字、复杂表格；这些应手工或程序重绘。
7. 每张图插入对应章节合适位置，替换原来的 `figuredesc` 占位。
8. LaTeX 统一使用：

   ```latex
   \notefigure{0.82}{filename.png}{图注}
   ```

9. 图注使用中文，必要时保留英文术语。
10. 不为凑数加入装饰图。

`FIGURES.md` 格式：

```markdown
# Figures

| PNG 文件名 | 内容说明 | 来源 PDF | 原图来源页码 | 类型 |
|---|---|---|---:|---|
| lecture03_game_theory_fig001_payoff_matrix.png | 收益矩阵示意 | lecture03.pdf | 12 | 截图自 |
```

阶段 5 完成后重新编译 `note.tex`，并抽样渲染检查 PDF 页面，确认图片不糊、不超宽、不遮挡文字。

阶段 5 报告：

- 共补了多少张图；
- 其中多少张截图自原 PDF；
- 多少张重绘；
- `FIGURES.md` 路径；
- `note.pdf` 是否重新编译成功。

## 阶段 6：最终 QA

阶段 6 不新增内容，除非发现明显错误需要修复。

检查项目：

1. `note.pdf` 能否成功编译。
2. 所有 `\includegraphics` 引用的 PNG 是否存在。
3. `chapters/` 中是否还有 `figuredesc` 占位。
4. 是否还有 `Page x`、`第 x 页`、`原讲义第 x 页` 这类页码残留。
5. 是否还有双重标题或标题重复。
6. 目录层级是否自然。
7. LaTeX log 是否有：
   - `Overfull`
   - `Underfull`
   - `Undefined`
   - `Missing`
   - `LaTeX Warning`
8. 图片是否命名统一。
9. `FIGURES.md` 是否覆盖所有图片。
10. `SUMMARY.md` 是否和最终章节一致。
11. Notion 汇总 Markdown 是否存在且覆盖全部 Lecture。

最终交付报告：

```markdown
## 笔记交付报告

- note.pdf：
- note.tex：
- chapters/：
- figures/：
- FIGURES.md：
- Markdown 汇总文件：
- SUMMARY.md：
- 图片数量：
- PDF 页数：
- 编译状态：
- 遗留问题：
```

## 阶段分工建议

默认串行执行并在每个阶段做检查点。只有当用户明确要求并行/分工，且宿主运行时确实提供 sub-agent 能力时，才可以把下列角色拆给子代理；否则这些只是阶段角色，不代表需要自动开启 sub-agent。

### Coordinator

负责阶段门控、状态报告、确认哪些阶段可以执行。Coordinator 不直接写大量正文。

### PDF Reader

负责完整读取 PDF、识别标题、表格、公式、图示位置和异常页。扫描版或无法提取文本的 PDF 必须报告。

### Markdown Writer

负责阶段 1 的中文 Markdown 讲义。每个 PDF 可以一个 writer，但必须由 Coordinator 汇总检查标题、顺序和风格。

### LaTeX Builder

负责阶段 3，把 Markdown 转为 `chapters/*.tex`，搭建 `note.tex` 和基础宏包。

### Chapter Refiner

负责阶段 4，逐章精修。每次只处理 2-3 个 chapter，处理后编译。

### Figure Curator

负责阶段 5，看原 PDF、裁图、重绘、写 `FIGURES.md`、插入 `\notefigure`。

### QA Runner

负责阶段 6，做最终编译、引用检查、占位符检查、页码残留检查和交付报告。

## 飞书 Bot 交互建议

飞书消息应映射到阶段任务，而不是让用户一次性丢长 prompt。

示例：

```text
用户：给多智能体基础生成笔记
Bot：我会先做阶段 0 盘点，不会修改文件。

用户：继续阶段 1
Bot：开始逐个 PDF 生成 Markdown，完成后推送 SUMMARY。

用户：继续到阶段 3
Bot：阶段 2 会先合并 Notion 版 Markdown，阶段 3 再搭 LaTeX 工程。
```

重要确认：

- 阶段 0 后确认是否继续；
- 阶段 3 编译失败时确认是否允许修复模板；
- 阶段 5 如果需要重绘大量图片，应确认范围；
- 任何覆盖已有 `note.tex`、`chapters/*.tex`、`notes_md/*.md` 的操作都要先报告。

## 与旧 Pandoc 流程的关系

旧流程“Markdown + README.md + Pandoc 多文件渲染”仍可作为快速预览或 fallback，但不是主交付路径。

使用 fallback 的条件：

- 用户只需要快速预览 PDF；
- 课程不需要正式 LaTeX 工程；
- 本地没有可用 LaTeX 模板；
- 阶段 3 明确失败，但 Markdown 已完整。

即便使用 fallback，也必须保留 `notes_md/`、`SUMMARY.md` 和阶段报告，不允许绕过阶段 0 和阶段 1。
