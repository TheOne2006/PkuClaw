---
name: pkuclaw-tool-pdf-reader
description: 读取、抽取和总结 PDF/讲义内容；优先使用已有依赖，缺依赖时先说明
---

# PDF Reader Skill

本 tool skill 用于读取 PDF 文本、表格和图片线索。它只提供读取方法，不负责安装系统包、不自动 OCR、不提交作业。

## 使用边界

- 优先使用当前环境已有的 PyMuPDF (`fitz`) 或 `pdfplumber`。
- 缺依赖时先向用户说明需要安装什么，不要在未确认时静默 `pip install`。
- 扫描版 PDF 没有文本层，需要 OCR；不能假装已完整读取。
- 密码保护 PDF 需要用户提供解锁方式。
- 超大文件建议分页读取，避免内存占用过高。

## 依赖检查

```bash
python - <<'PY'
for name in ("fitz", "pdfplumber"):
    try:
        __import__(name)
        print(f"{name}: available")
    except ModuleNotFoundError:
        print(f"{name}: missing")
PY
```

如果用户确认安装，可按环境选择：

```bash
python -m pip install pymupdf pdfplumber
```

## PyMuPDF：快速读取文本

```python
from pathlib import Path
import fitz  # PyMuPDF


def read_pdf_pymupdf(pdf_path: str | Path, pages=None) -> dict:
    path = Path(pdf_path)
    result = {"total_pages": 0, "text": {}}
    with fitz.open(path) as doc:
        result["total_pages"] = len(doc)
        page_range = pages if pages is not None else range(len(doc))
        for index in page_range:
            if 0 <= index < len(doc):
                result["text"][index + 1] = doc[index].get_text()
    return result


content = read_pdf_pymupdf("/path/to/course/lectures/lecture-01.pdf")
print(content["total_pages"])
print(content["text"].get(1, ""))
```

## pdfplumber：表格友好读取

```python
from pathlib import Path
import pdfplumber


def read_pdf_pdfplumber(pdf_path: str | Path, pages=None) -> dict:
    path = Path(pdf_path)
    result = {"total_pages": 0, "text": {}, "tables": {}}
    with pdfplumber.open(path) as pdf:
        result["total_pages"] = len(pdf.pages)
        page_range = pages if pages is not None else range(len(pdf.pages))
        for index in page_range:
            if 0 <= index < len(pdf.pages):
                page = pdf.pages[index]
                result["text"][index + 1] = page.extract_text() or ""
                tables = page.extract_tables()
                if tables:
                    result["tables"][index + 1] = tables
    return result


content = read_pdf_pdfplumber("/path/to/course/assignments/homework.pdf", pages=[0, 1])
print(content["tables"].keys())
```

## 图片抽取线索

```python
from pathlib import Path
import fitz


def list_pdf_images(pdf_path: str | Path, page_num: int = 0) -> list[dict]:
    path = Path(pdf_path)
    images = []
    with fitz.open(path) as doc:
        page = doc[page_num]
        for img_index, img in enumerate(page.get_images(), start=1):
            xref = img[0]
            base = doc.extract_image(xref)
            images.append({
                "page": page_num + 1,
                "index": img_index,
                "ext": base.get("ext"),
                "bytes_len": len(base.get("image") or b""),
            })
    return images
```

## 简单工具类

```python
from pathlib import Path
import fitz


class PDFReader:
    def __init__(self, pdf_path: str | Path):
        self.pdf_path = Path(pdf_path)
        if not self.pdf_path.exists():
            raise FileNotFoundError(f"PDF 文件不存在: {self.pdf_path}")

    def info(self) -> dict:
        with fitz.open(self.pdf_path) as doc:
            return {
                "pages": len(doc),
                "title": doc.metadata.get("title", ""),
                "author": doc.metadata.get("author", ""),
            }

    def text_by_page(self, pages=None) -> dict[int, str]:
        with fitz.open(self.pdf_path) as doc:
            page_range = pages if pages is not None else range(len(doc))
            return {
                index + 1: doc[index].get_text()
                for index in page_range
                if 0 <= index < len(doc)
            }

    def search(self, keyword: str) -> list[int]:
        matches = []
        with fitz.open(self.pdf_path) as doc:
            for index, page in enumerate(doc):
                if keyword in page.get_text():
                    matches.append(index + 1)
        return matches
```

## 输出建议

读取后向上层 task 返回结构化摘要：

```json
{
  "file": "/path/to/file.pdf",
  "total_pages": 12,
  "text_pages": [1, 2, 3],
  "tables_pages": [4],
  "warnings": []
}
```

如果文本为空、页数异常或存在扫描页，把问题写入 `warnings`，不要静默忽略。
