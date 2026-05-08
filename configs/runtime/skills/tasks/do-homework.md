---
name: pkuclaw-task-do-homework
description: 处理 PKU 课程作业的解析、解题、渲染和提交前确认；提交必须由用户明确授权
---

# 任务：处理作业

本 skill 只用于 `realtime`。作业提交、覆盖文件、下载大附件、登录/登出等都属于高风险动作，必须先获得用户明确确认。Loop 不得自动执行本 skill。

## 默认目标

默认只完成：

1. 明确课程、作业、截止时间和输入文件；
2. 读取题目/附件/PDF；
3. 生成本地答案草稿或解题计划；
4. 渲染可预览文件；
5. 给出提交前检查清单。

只有用户明确说“提交”并确认课程、作业、文件路径后，才进入提交步骤。

## 阶段 0：确认范围

先用自然语言向用户确认关键信息，不要假装存在宿主提供的 `AskUserQuestion` 或自动选择 API。

需要确认：

- 课程名 / course id；
- 作业标题 / assignment id；
- 截止时间和是否已提交；
- 输入文件位置（题面、附件、已有草稿、参考资料）；
- 输出位置；
- 是否只是生成草稿，还是最终可能提交。

如果用户只说“帮我做作业”，先列出缺失信息并等待回复。

## 阶段 1：获取作业状态

本节中的 `pku3b` 表示已按 `pku3b/usage.md` 解析出的实际可执行文件。优先只读查询：

```bash
pku3b assignments list --term current
pku3b assignments get --id <assignment_id> --term current
```

边界：

- 不自动登录、登出、清缓存；
- 不在 loop 中运行；
- 不自动下载大附件；
- 若缺凭据、OTP 或工具，停止并说明需要用户处理。

如需取回自己已提交的文件，必须由用户明确要求后执行：

```bash
pku3b assignments download-submission --id <submitted_file_id> --out-dir <dir> --term current
```

## 阶段 2：读取题面和附件

引用 `tools/pdf-reader.md`。优先使用当前环境已有库；缺依赖时先说明，不要静默 `pip install`。

基础解析示例：

```python
import json
import re
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ModuleNotFoundError as exc:
    raise SystemExit("缺少 PyMuPDF；请先确认是否允许安装依赖") from exc


def read_pdf_text(pdf_path: str) -> str:
    path = Path(pdf_path)
    with fitz.open(path) as doc:
        return "\n".join(page.get_text() for page in doc)


def split_problems(text: str) -> list[dict[str, str]]:
    pattern = r"(?:^|\n)\s*(?:Problem\s*)?(\d+)[\.、\)]\s*([^\n]+)(.*?)(?=\n\s*(?:\d+[\.、\)]|Problem\s*\d+)|\Z)"
    results = []
    for number, title, body in re.findall(pattern, text, re.S | re.I):
        results.append({
            "number": number.strip(),
            "title": title.strip(),
            "content": body.strip(),
        })
    return results


text = read_pdf_text("/path/to/homework.pdf")
problems = split_problems(text)
Path("/path/to/homework_parsed.json").write_text(
    json.dumps({"problems": problems}, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
```

扫描版 PDF 需要 OCR；不能假装已经完整读取。

## 阶段 3：解题与生成草稿

输出建议：

```text
{course_dir}/作业/{assignment_slug}_answer.md
{course_dir}/作业/{assignment_slug}_answer.pdf   # 如果已渲染
{course_dir}/作业/{assignment_slug}_checklist.md
```

要求：

- 逐题作答，保留必要推导、公式和引用来源；
- 对不确定部分标注“不确定/需要用户确认”；
- 不凭空引用不存在的讲义或资料；
- 写作类作业需核对字数/格式要求；
- 编程类作业需说明运行环境和测试命令；
- 不覆盖用户已有文件，除非用户确认。

只有当用户明确要求并行/分工，且宿主运行时确实提供 sub-agent 能力时，才可以拆分给子代理；否则默认串行完成。

## 阶段 4：质量检查

写作类作业可用脚本统计字数：

```python
import re
from pathlib import Path

text = Path("/path/to/answer.md").read_text(encoding="utf-8")
words = [w for w in text.split() if re.search(r"[A-Za-z0-9]", w)]
print({"word_count": len(words)})
```

数学/代码类作业至少检查：

- 是否漏题；
- 公式是否可渲染；
- 变量和单位是否一致；
- 代码是否可运行；
- 输出文件是否能打开。

## 阶段 5：渲染

优先使用用户项目已有工具链。若无现成工具，可生成 Markdown 并说明用户可选择的渲染方式，例如 Pandoc、Typst、LaTeX、浏览器打印等。不要默认依赖某个本机绝对路径。

示例（仅在环境已有 `pandoc` 时使用）：

```bash
pandoc answer.md -o answer.pdf
```

## 阶段 6：提交前确认

提交前必须给出清单并等待用户明确回复：

```markdown
## 提交前确认

- 课程：
- 作业：
- assignment id：
- 将提交的文件：
- 本地预览/测试：
- 风险：提交后可能覆盖旧 attempt 或触发教学网状态变化。

请明确回复“确认提交 <文件路径> 到 <作业>”。
```

## 阶段 7：提交（默认不执行）

只有同时满足以下条件才可以继续：

1. 用户明确说“提交”并确认课程、作业、文件路径；
2. 已有稳定提交工具或用户指定提交方式；
3. 最终文件已通过本地预览/编译检查；
4. 不需要把账号、密码、OTP 写入脚本、文档或日志。

如果使用 pku3b：

```bash
pku3b assignments submit --id <assignment_id> --file <path>
pku3b assignments get --id <assignment_id> --term current
```

提交后把命令返回 envelope 中的关键状态摘要给用户；不要输出凭据、cookie 或完整敏感日志。
