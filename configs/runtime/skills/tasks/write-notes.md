---
name: pkuclaw-task-write-notes
description: 完整课程笔记生产线；命中本 skill 时必须显式 spawn 同等级 subagents/workers，阶段 1 只做 PDF 机械识别与动画页合并，阶段 2 只做保留页码溯源的 source_md 结构化，严禁提前摘要化写笔记。
---

# 任务：课程笔记生成

这个 task 是 PkuClaw 的课程笔记生产线。它的默认完成定义不是“交付一份汇总 Markdown”，而是产出可编译的 LaTeX 讲义工程和 `note.pdf`。如果用户只明确要求 quick summary，才可以降级；降级时仍不能冒充完整 write-notes 交付。

本任务默认采用 **Main Agent + sub-agent/worker** 的编排模型：Main Agent 主要负责监督、分派、验收、风险确认和最终交付；各阶段 sub-agent/worker 负责实际资料整理、阅读、写作、构建、补图和 QA。

## Agent 编排模型

Main Agent 是 Coordinator / Supervisor，职责是：

- 理解用户目标和输入线索；
- 确定或批准本次课程工作区 `{course_dir}`；
- 按阶段派发同等级 sub-agent/worker；
- 为每个 worker 指定清晰的读写边界；
- 审查阶段输出，发现冲突或缺失时要求返工；
- 处理登录、验证码、覆盖、删除、重命名、下载超大附件、安装依赖等需要用户确认的风险；
- 汇总最终交付报告。

各阶段 sub-agent/worker 是实际执行者。默认情况下，sub-agent/worker 应继承 Main Agent 的模型、reasoning effort、工具能力、sandbox 和必要上下文；不得为了速度或成本自动降级。只有宿主环境不支持 sub-agent，或用户/runtime 明确要求串行执行时，Main Agent 才可以自行串行完成这些阶段，并必须在最终报告中说明。

并行执行时必须指定互不冲突的写入范围；一个 worker 不得修改其他 worker 负责的文件，除非 Main Agent 明确批准。

完整 write-notes 任务中，sub-agent/worker 不是文案角色，而是必须显式触发的 Codex subagent workflow。Main Agent 在进入阶段 1 前必须 spawn 对应 worker，并在阶段报告中写明 worker 分工、写入边界和是否已等待/验收结果；不得只用单个主 agent 写脚本一次性生成所有正文。若当前宿主确实无法 spawn subagents，必须在开始正文生成前声明串行 fallback、说明影响，并在最终报告中保留该限制。

## 输入与课程工作区

用户输入可以是课程名、课程目录、教学网页面、课程平台入口、附件线索或已有课件路径。不要假设调用方已经传入整理好的课件目录。

`{course_dir}` 是 Main Agent 在阶段 0 确认或创建出来的课程工作区；它不必须由用户预先提供，也可以是本次任务的临时工作区：

- 如果用户提供了现成课程目录，阶段 0 在该目录内整理或建立映射；
- 如果用户只提供课程名或课程平台入口，阶段 0 负责创建或确认课程工作区；
- 如果用户没有指定目录，Main Agent 可以选择一个安全的默认/临时工作区，例如当前运行允许写入的位置下的 `pkuclaw-notes/<course_slug>/`，并在阶段 0 报告中写明；
- 如果只是快速试跑、资料尚未完全确认或持久保存位置未知，可以先使用临时 `{course_dir}`，后续需要长期保存时再由 Main Agent 迁移或复制到用户确认的位置；
- 只有在需要写入受限目录、覆盖已有成果、迁移/移动用户原文件，或无法确定课程身份时，才需要停下向用户确认；
- 如果课程目录已有不同结构，阶段 0 只整理本次工作所需的副本或映射，不擅自移动、删除或覆盖用户原文件。

目标结构是阶段输出目标，不是调用方必须预先准备的结构：

```text
{course_dir}/
├── lectures/                      # 阶段 0 整理出的原始 PDF 副本或工作副本
├── course-note/                   # 阶段 0 从 runtime skill 复制的 LaTeX 模板副本
│   ├── README.md
│   ├── note.tex                   # 模板文件，不是最终主入口
│   └── chapter.tex                # chapter 模板文件
├── extracted/                     # 阶段 1：逐页机械识别与动画页合并结果
├── source_md/                     # 阶段 2：保留页码溯源的结构化原始材料
├── notes_md/                      # 后续正式中文 Markdown 讲义
├── chapters/                      # 每个 Lecture 对应一份 LaTeX chapter
├── figures/                       # 裁图或重绘图片
│   └── FIGURES.md                 # 图片来源表
├── SOURCE_SUMMARY.md              # 阶段 2 source 总表
├── SUMMARY.md                     # 正式 Markdown 笔记总表
├── README.md                      # LaTeX 工程说明
├── note.tex                       # LaTeX 主入口，由模板渲染得到
├── note.pdf                       # 编译产物
└── {course_name}_汇总笔记.md       # Notion 用汇总 Markdown
```

`course-note/` 的源模板位于：

```text
configs/runtime/skills/tasks/course-note/
```

阶段 0 应把该模板目录复制到 `{course_dir}/course-note/`，后续阶段再从课程目录中的模板副本渲染 `note.tex` 和 `chapters/*.tex`。不要 `mv`、删除或修改 runtime skill 中的源模板。

## 阶段报告与可恢复

每个阶段完成后，worker 向 Main Agent 返回阶段报告。Main Agent 负责保留阶段进度、输出清单、风险和遗留问题。

不要把阶段状态写成 PkuClaw Core 的固定契约；当前 workflow 不要求 CoreRuntime 自动维护课程目录内的阶段状态 JSON。如果某次运行确实需要可恢复状态，可以由 Agent 自己维护轻量工作记录，或只在最终报告中说明阶段进度。

## 总原则

1. **Main Agent 监督**：Main Agent 主要做规划、分派、审查和交付，不直接承担大量正文生产。
2. **同等级 worker**：各阶段 sub-agent/worker 默认继承 Main Agent 的模型、reasoning effort、工具能力和必要上下文，不自动降级。
3. **阶段隔离**：每个阶段只做本阶段允许的事情，不提前生成后续产物。
4. **资料先整理**：阶段 0 负责获取、下载、去重、整理课件和复制模板，不只是盘点。
5. **Markdown 与 LaTeX 分离**：先生成中文 Markdown 讲义，再搭建 LaTeX 工程。
6. **LaTeX 精修与补图分离**：章节文字/结构精修和图片补齐分阶段执行。
7. **来源可追溯**：每份笔记、每张图、每个章节都保留来源 PDF 文件名；正文中不保留页码噪声。
8. **内容不幻觉**：不要凭空添加原讲义没有的定理、结论、例子；必要补充必须标注“补充理解”。
9. **高风险确认**：覆盖、删除、移动用户原文件，安装依赖，凭据/验证码，课程回放或超大附件下载等必须交回 Main Agent 请求确认。
10. **可恢复**：每阶段都要有报告；串行 fallback 或失败中断时要说明已完成阶段和可继续入口。

## 阶段 0：资料获取、整理与模板落位

负责 worker：Material Organizer。

阶段 0 的目标不是“只盘点不动文件”，而是为后续生产线准备可靠输入和课程工作区。

输入可以是：

- 课程名；
- 已有课程目录；
- 教学网 / 课程平台页面；
- 用户提供的 PDF、压缩包或附件线索；
- 相邻课程目录或历史笔记作为模板参考。

必须完成：

1. 确定或创建 `{course_dir}`；如果用户未指定目录，优先创建安全的默认/临时工作区，不要仅因缺少目录就阻塞。
2. 如果使用临时 `{course_dir}`，必须在阶段 0 报告和最终交付报告中标明，并说明后续如何迁移到用户指定位置。
3. 定位课程课件来源；如果资料来自 PKU 教学网，先参考 `pku3b/usage.md` 的只读课程/课件索引与下载边界。
4. 在课程已确认，且 Main Agent 已确认或创建 `{course_dir}` 后，普通讲义 PDF 附件可以作为本阶段职责下载或收集；下载结果必须落在课程工作区或 pku3b 返回的可追踪本地路径中。
5. 遇到登录失效、验证码、OTP、凭据缺失、权限不足时，立即交回 Main Agent，不能伪造已下载结果。
6. 将讲义 PDF 整理到 `{course_dir}/lectures/`，优先复制或保存工作副本；不要擅自移动、删除、重命名用户原文件。
7. 对课件去重，识别疑似重复版本、缺失 lecture、扫描版 PDF、无文本层 PDF、损坏文件和异常大小文件。
8. 统一工作副本命名，命名应稳定、可读，并尽量保留 lecture 顺序，例如 `lecture01_intro.pdf`。
9. 创建后续阶段需要的基础目录：`extracted/`、`source_md/`、`notes_md/`、`chapters/`、`figures/`。
10. 从 `configs/runtime/skills/tasks/course-note/` 复制模板目录到 `{course_dir}/course-note/`；如果目标模板副本已存在，只能在确认它是本次运行生成或获得 Main Agent 批准后覆盖。
11. 检查是否已有 `note.tex`、`chapters/*.tex`、`extracted/*`、`source_md/*.md`、`notes_md/*.md`、`README.md`、`SOURCE_SUMMARY.md`、`SUMMARY.md` 等用户成果；不得覆盖，必须记录并交给 Main Agent 决策。
12. 生成阶段 0 报告，列出课程工作区、课件清单、模板副本、已有成果、异常和风险。

阶段 0 报告格式：

```markdown
## 阶段 0 资料整理报告

- 课程工作区：
- 工作区类型：用户指定 / 默认创建 / 临时
- 如为临时工作区，后续迁移方式：
- 资料来源：
- 已下载/收集 PDF：
- lectures/ 工作副本：
- course-note 模板副本：
- 已有用户成果：
- 缺失或疑似重复课件：
- 扫描版/无文本层/损坏 PDF：
- 后续阶段写入边界：
- 需要用户确认的风险：
```

阶段 0 允许：

- 创建 `{course_dir}` 和本任务需要的子目录；
- 在课程和 `{course_dir}` 已确认或已创建后，下载或收集普通讲义 PDF；
- 复制用户原始 PDF 到 `lectures/` 作为工作副本；
- 复制 `course-note` 模板目录到课程工作区；
- 写阶段报告或清单。

阶段 0 禁止：

- 生成讲义正文；
- 转换 PDF 内容为 Markdown 或 LaTeX；
- 裁图、补图或重绘；
- 覆盖用户已有笔记、LaTeX、图片或 README；
- 移动、删除、重命名用户原始文件；
- 修改 runtime skill 源模板。

阶段 0 后默认继续到阶段 1；只有发现高风险动作或无法获取课件时才暂停等待用户。

## 阶段 1：PDF 机械识别与动画页合并

负责 worker：PDF Reader / Page Extractor。

读取 `{course_dir}/lectures/` 下的讲义 PDF；如果阶段 0 只建立了外部映射，也可以读取阶段 0 报告中确认的 PDF 路径。

阶段 1 的目标是做忠实的机器识别和页级清洗，不写笔记、不做解释性改写、不提前总结。它要把 PDF 里每一页或每组动画页“到底出现了什么”保存下来，作为后续结构化和写笔记的原始中间表示。

很多课件会因为动画逐步出现文字、公式或图形而把同一张 slide 展开成多页。阶段 1 必须识别这种连续动画页，合并为一个页组；合并时保留原始页码范围，并使用该页组的最大信息集合（通常接近最后一页，但也要保留中途出现后又消失的重要内容）。

输出：

```text
{course_dir}/extracted/{pdf_stem}_pages.md
{course_dir}/extracted/{pdf_stem}_pages.json
{course_dir}/extracted/EXTRACTION_SUMMARY.md
```

要求：

1. 必须逐页读取每个 PDF；不得只读首页、目录、页标题或 PDF 摘要。
2. 每个原始页面必须进入一个 page unit 或 merged page group；不得无记录地丢页。
3. 识别并合并连续动画页：同一标题/版式/图形背景高度相似、只是逐步增加文字/项目符号/公式/标注的连续页，应合并为 `pages: x-y`。
4. 非动画的连续页面不得因为主题相同而合并；主题合并留到阶段 2。
5. 对每个 page unit / page group 记录：原始页码或页码范围、页标题或可识别标题、本页/页组作用、识别出的正文、项目符号、公式、表格、图示、脚注/引用、明显 OCR/提取异常。
6. “本页/页组作用”只描述它在讲义中的功能，例如“引入本讲问题”“给出定义”“展示趋势图”“列出政策时间线”“推导公式”；不要写成复习笔记或观点总结。
7. 表格尽量机械转写为 Markdown 表格；无法可靠转写时保留 `[表：xxx，需回看原图]`。
8. 图示先记录内容性占位和来源页码/页组，例如 `[图：城乡收入差距趋势，来源 pages 12-13]`；阶段 1 不裁图、不重绘。
9. 公式尽量保持 LaTeX 或可读文本；不确定的符号必须标注不确定，不能猜。
10. 扫描版、无文本层、乱码页、空白页、疑似重复页、动画合并页都必须在 `EXTRACTION_SUMMARY.md` 中列出。
11. 阶段 1 输出可以保留页码，而且必须保留页码/页组，因为这是后续溯源和去重依据；页码噪声只应在最终课堂笔记正文中去掉。
12. 阶段 1 禁止生成 `notes_md/*.md`、LaTeX、汇总笔记或任何润色后的课堂笔记。

阶段 1 的 page group 建议格式：

```markdown
## Page Group 4-6：财政分权的基本问题

- 类型：动画合并页 / 普通单页 / 表格页 / 图示页 / 公式页
- 本页/页组作用：引入中央与地方财政关系的核心问题。
- 识别内容：
  - ...
  - ...
- 公式：
  - `$...$`
- 表格：
  | ... |
- 图示：
  [图：关于 xxx 的示意图，来源 pages 4-6]
- 提取异常：无 / OCR 不确定 / 图中文字需回看
```

PDF 读取参考：

```python
import fitz

doc = fitz.open(pdf_path)
texts = []
for page in doc:
    texts.append(page.get_text())
doc.close()
```

表格多的 PDF 可补充使用 `pdfplumber`。扫描版 PDF 需要 OCR；需要安装系统依赖或调用外部服务时，必须交回 Main Agent 确认。

## 阶段 2：结构化整理 PDF 原始材料

负责 worker：Source Structurer。

根据阶段 1 的 page units / merged page groups，把每个 PDF 的机械识别结果整理成可读的中文结构化材料。阶段 2 仍然不是正式课堂笔记：它只是把阶段 1 的文字按讲义逻辑重新排列、去除动画重复、整理层级，并保留“第几页/页组在讲什么、起什么作用”的溯源信息。

输出：

```text
{course_dir}/source_md/{pdf_stem}.md
{course_dir}/SOURCE_SUMMARY.md
```

要求：

1. 每个 PDF 单独生成一个结构化 source Markdown 文件，文件名与 PDF 对应。
2. 只使用阶段 1 识别结果和必要的 PDF 回看；不得凭空补入原讲义没有的结论、数据、例子或政策判断。
3. 可以按讲义逻辑重排和合并相邻 page groups，但必须保留来源页码/页组，例如 `来源：pages 4-6`。
4. 阶段 2 的语言目标是“结构化表述原材料”，不是“写成最终课堂笔记”；可以比原文更清楚，但不能省略实质内容。
5. 对每个主题保留页面功能说明，例如“pages 8-10 用一个趋势图说明人口结构变化”，方便后续 Note Writer 决定是否写入正文或补图。
6. 定义、结论、例子、证明思路、政策背景、制度说明等可以先按原文类型标注为“原文定义/原文结论/原文例子/原文材料”，不要过早改造成彩色框或教材化笔记。
7. 图和表继续保留内容性占位，并带来源页码/页组；阶段 2 不裁图、不重绘。
8. 公式使用 LaTeX；无法确认的公式保留原识别结果并标注“需回看”。
9. 必须覆盖阶段 1 的每个 page unit / page group；如果某页/页组被判断为封面、目录、纯过渡页、重复动画页或无实质内容，也要在覆盖表中说明。
10. 不生成 `notes_md/*.md`，不生成 Notion 汇总，不生成 LaTeX；正式课堂笔记由后续 Note Writer 基于 `source_md/` 再写。

结构化 source Markdown 建议格式：

```markdown
# Lecture 标题：结构化原始材料

## 本讲页面地图

| 页码/页组 | 页面作用 | 主要内容 | 后续处理建议 |
|---|---|---|---|
| pages 1-1 | 封面 | 课程、讲次、教师 | 最终笔记只保留来源信息 |
| pages 4-6 | 动画合并页：定义 | xxx | 写入定义框 |
| pages 12-13 | 图示页 | xxx 趋势图 | 阶段 7 补图 |

## 1. 主题标题（来源：pages x-y）

### 1.1 原文材料整理

- ...
- ...

> **原文定义（来源：pages x-y）：**
> ...

> **原文结论/观点（来源：pages x-y）：**
> ...

> **原文例子（来源：pages x-y）：**
> ...

[图：关于 xxx 的示意图，来源 pages x-y]

## 覆盖检查

- 已覆盖 page groups：1, 2-3, 4-6, ...
- 无实质内容/仅动画重复：...
- 仍需回看：...
```

`SOURCE_SUMMARY.md` 列出：

- Lecture 标题；
- 原 PDF 文件名；
- 阶段 1 extracted 文件名；
- 阶段 2 source Markdown 文件名；
- 原 PDF 页数；
- 合并后的 page group 数；
- 动画合并页组；
- 图表/公式/表格数量；
- 提取异常；
- 是否有未覆盖 page group。

阶段 2 只生成 `source_md/*.md` 和 `SOURCE_SUMMARY.md`，不要做正式笔记、汇总 Markdown 或 LaTeX。

## 阶段 3：基于 source_md 生成正式中文 Markdown 笔记

负责 worker：Markdown Writer。

根据阶段 2 的 `source_md/*.md` 和必要的 PDF 回看，为每个 PDF 单独生成正式中文课堂笔记。阶段 3 才开始“写笔记”：此时应去掉页码噪声，按讲义逻辑重新组织语言，让内容适合学生复习和后续 LaTeX 化。

输出：

```text
{course_dir}/notes_md/{pdf_stem}.md
{course_dir}/SUMMARY.md
```

要求：

1. 每个 PDF 单独生成一个中文 Markdown 讲义文件，文件名与 PDF/source 对应。
2. 必须以 `source_md/` 的页面地图和结构化原始材料为依据；不能只看标题、目录或几条摘要。
3. 必要时回看原 PDF，尤其是阶段 2 标注“需回看”的图、表、公式、政策表述和数据页。
4. 按讲义逻辑重新组织成中文课堂笔记，而不是逐页机械翻译。
5. 正式笔记正文不保留 `Page 1`、`第 x 页`、`原讲义第 x 页` 之类页码标记；页码只保留在 source/extracted 中。
6. 可以合并连续页面中的同一主题，但不得删除 source 中的实质内容。
7. 中文为主，英文专业名词第一次出现时保留英文。
8. 不凭空添加原讲义没有的定理、结论、数据、政策判断或例子；必要补充必须明确标注“补充理解”。
9. 定义、结论/观点、例子、备注、证明思路、政策背景、制度说明使用统一格式。
10. 数学公式使用 LaTeX：行内 `$...$`，独立公式用 `$$...$$`。
11. 图无法直接转换时，保留内容性占位：`[图：关于 xxx 的示意图]`，不要写页码。
12. 表格尽量转为 Markdown 表格。
13. 必须覆盖 `source_md/` 中标记为“后续写入笔记”的实质内容；跳过的封面、目录、纯过渡页或重复动画页应在 `SUMMARY.md` 中说明。
14. 不得把完整讲义压缩成提纲。对 15 页以上且有文本层的 lecture，如果正式 Markdown 少于约 120 行，必须主动回看 `source_md/` 和 PDF 判断是否漏写；只有讲义本身高度图像化/文字极少时才可例外，并须在 `SUMMARY.md` 标明。

Markdown 结构：

```markdown
# Lecture 标题

## 本讲概览

## 1. ...

### 1.1 ...

> **定义：**
> ...

> **结论/观点：**
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
- source Markdown 文件名；
- 输出 Markdown 文件名；
- 简短主题说明；
- 源 PDF 页数、source page group 数、正式 Markdown 行数/字符数；
- 是否含图占位；
- 是否存在 PDF/source 提取异常；
- 是否有 source 实质内容未写入正式笔记。

阶段 3 只生成 `notes_md/*.md` 和 `SUMMARY.md`，不要做 LaTeX。

## 阶段 4：生成汇总 Markdown

负责 worker：Markdown Merger。

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
7. 合并后检查总行数/字符数应接近各 `notes_md/*.md` 之和；不得在阶段 4 做摘要化瘦身。

阶段 4 报告：

- 合并了多少个文件；
- 输出文件路径；
- 是否发现标题重复；
- 是否发现顺序异常；
- 是否有缺失 Lecture。

## 阶段 5：搭建 LaTeX 讲义工程

负责 worker：LaTeX Builder。

优先使用阶段 0 已复制到课程目录中的模板副本：

```text
{course_dir}/course-note/note.tex
{course_dir}/course-note/chapter.tex
```

如果课程目录没有模板副本，才回退读取 runtime skill 源模板：

```text
configs/runtime/skills/tasks/course-note/note.tex
configs/runtime/skills/tasks/course-note/chapter.tex
```

如果用户指定模板，则优先使用用户模板；否则可参考同一 Notes 根目录下已有课程模板。

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
2. `note.tex` 必须由课程目录中的模板副本或用户模板渲染得到，替换课程名、作者、学期、章节 `\input{...}` 等占位信息；不要直接把模板文件当成最终 `note.tex` 编译。
3. 不做双重标题：`chapter` 标题可以写 Lecture 编号和主题；`section` 不要机械重复 Markdown 原编号。
4. 每章开头只保留来源信息：原 PDF 文件名、Lecture 编号；不写完整路径，不写页码。
5. 不额外生成复杂封面，除非模板已有简洁封面。
6. 使用适合教材讲义的彩色框：定义、结论/定理、例子、备注、证明思路。
7. 不完全套数学笔记模板里不适合的 theorem 风格；课程概念、机制、算法、例子更重要。
8. 图暂时可以继续保留占位，统一为：

   ```latex
   \begin{figuredesc}
   ...
   \end{figuredesc}
   ```

9. 公式必须能被 `xelatex` 编译。
10. 中文排版自然，不像自动翻译。
11. 不能覆盖用户已有 `note.tex`、`chapters/*.tex`、`README.md`，除非 Main Agent 已确认这是本次运行产物或用户同意覆盖。

LaTeX 主文件建议包含或继承这些能力：

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

阶段 5 必须尝试编译 `note.tex` 并记录报告，但不需要等待用户验收：

- 生成了哪些文件；
- 是否成功编译；
- PDF 页数；
- LaTeX log 中是否有 `Overfull`、`Underfull`、`Undefined`、`Missing`、`LaTeX Warning`。

## 阶段 6：逐章精修 LaTeX

负责 worker：Chapter Refiner。

阶段 6 不补图，不裁图，不重绘图。只精修 LaTeX 结构、文字、公式、表格。

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

阶段 6 报告是内部检查点，不需要等待用户验收：

- 改了哪些 chapter；
- 修复了哪些主要问题；
- 编译是否通过；
- 还有哪些遗留问题。

## 阶段 7：一张一张看原 PDF，补齐有用图片

负责 worker：Figure Curator。

阶段 7 专门处理图片。它必须在阶段 6 完成之后执行。

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

阶段 7 完成后重新编译 `note.tex`，并抽样渲染检查 PDF 页面，确认图片不糊、不超宽、不遮挡文字。

阶段 7 报告：

- 共补了多少张图；
- 其中多少张截图自原 PDF；
- 多少张重绘；
- `FIGURES.md` 路径；
- `note.pdf` 是否重新编译成功。

## 阶段 8：最终 QA

负责 worker：QA Runner。

阶段 8 不新增内容，除非发现明显错误需要修复。

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
11. 汇总 Markdown 是否存在且覆盖全部 Lecture。
12. `course-note/` 模板副本是否仍是模板副本，最终主入口是否为根目录 `note.tex`。

最终交付报告：

```markdown
## 笔记交付报告

- 课程工作区：
- 工作区类型：用户指定 / 默认创建 / 临时
- 如为临时工作区，迁移建议：
- lectures/：
- course-note 模板副本：
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

## 阶段 worker 写入边界

默认目标是完整跑通阶段 0-8。阶段是内部生产检查点，不要求用户逐阶段验收；只有遇到高风险动作、无法获取资料、登录/凭据阻塞、覆盖已有成果、安装依赖或删除/移动文件时才暂停确认。

并行时必须指定互不冲突的写入范围：

- Material Organizer 负责 `{course_dir}`、`lectures/`、`course-note/` 模板副本和阶段 0 报告；不得生成正文。
- PDF Reader / Page Extractor 只读 PDF，写 `extracted/` 下逐页识别与动画页合并结果；不得写正式笔记正文。
- Source Structurer 只写 `source_md/*.md` 和 `SOURCE_SUMMARY.md`，保留页码/页组溯源；不得写正式笔记正文。
- Markdown Writer 只基于 `source_md/` 写阶段 3 正式 `notes_md/*.md` 和 `SUMMARY.md`。
- Markdown Merger 只写 `{course_name}_汇总笔记.md`。
- LaTeX Builder 只写根目录 `note.tex`、`README.md`、初版 `chapters/*.tex` 和初版 `note.pdf`。
- Chapter Refiner 按 Main Agent 分配的 chapter 分片修改；不得跨片覆盖。
- Figure Curator 只写 `figures/`、`FIGURES.md`，并替换对应章节图占位。
- QA Runner 做检查和最小修复；如需大改，必须交回 Main Agent 重新分派。

### Material Organizer

负责阶段 0，获取课程资料、整理讲义 PDF、建立课程工作区、复制 `course-note` 模板副本并报告异常。在课程和 `{course_dir}` 已确认或已创建后，下载普通讲义附件属于本阶段职责；课程回放、超大附件、凭据/验证码和远端写操作必须交回 Main Agent。

### PDF Reader / Page Extractor

负责阶段 1，逐页机械识别 PDF、合并动画展开页、记录页码/页组、正文、表格、公式、图示位置和异常页。扫描版或无法提取文本的 PDF 必须报告。

### Source Structurer

负责阶段 2，把阶段 1 的 page units / merged page groups 整理成 `source_md/` 结构化原始材料。它可以调整层级和合并相邻主题，但必须保留页码/页组溯源，不写正式课堂笔记。

### Markdown Writer

负责阶段 3 的正式中文 Markdown 讲义。每个 PDF 可以一个 writer，但必须以 `source_md/` 为依据，并由 Main Agent 汇总检查标题、顺序、覆盖率和风格。

### Markdown Merger

负责阶段 4，把 `notes_md/` 合并成汇总 Markdown，不改写正文内容。

### LaTeX Builder

负责阶段 5，把 Markdown 转为 `chapters/*.tex`，从课程目录的 `course-note/` 模板副本渲染根目录 `note.tex`，并搭建基础宏包和 README。

### Chapter Refiner

负责阶段 6，逐章精修。每次只处理 2-3 个 chapter，处理后编译。

### Figure Curator

负责阶段 7，看原 PDF、裁图、重绘、写 `FIGURES.md`、插入 `\notefigure`。

### QA Runner

负责阶段 8，做最终编译、引用检查、占位符检查、页码残留检查和交付报告。
