# PkuClaw course-note LaTeX template

This directory contains the default LaTeX template used by `configs/runtime/skills/tasks/write-notes.md` when generating formal course notes.

Source: extracted from the root `多智能体基础/` completed note draft.

Files:

- `note.tex`: main `ctexbook` template with title page, shared colors, boxed environments, figure macro, TOC, and chapter inputs.
- `chapter.tex`: per-chapter skeleton with `sourcebox` and `overviewbox`.

Render by copying the templates into a course note directory and replacing all `@@PLACEHOLDER@@` tokens. Do not compile these template files directly.

Important placeholders in `note.tex`:

- `@@COURSE_TITLE@@`
- `@@COURSE_SUBTITLE@@`
- `@@AUTHOR@@`
- `@@INSTITUTION@@`
- `@@TERM@@`
- `@@PDF_TITLE@@`
- `@@PDF_AUTHOR@@`
- `@@SOURCE_NOTE@@`
- `@@CHAPTER_INPUTS@@` — newline-separated `\input{chapters/<chapter>.tex}` statements.

Important placeholders in `chapter.tex`:

- `@@CHAPTER_TITLE@@`
- `@@SOURCE_PDF@@`
- `@@LECTURE_ID@@`
- `@@OVERVIEW@@`
- `@@CHAPTER_BODY@@`
