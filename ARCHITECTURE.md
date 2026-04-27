# PkuClaw Architecture

PkuClaw is moving from a prompt/skill repository into a long-running course
agent service. The intended split is:

- Python owns the CLI, scheduler, local state, Feishu gateway, and workflow
  orchestration.
- Rust owns low-level course access through the internal `pku3b` crate.
- Codex workers handle heavy reasoning tasks such as notes, homework review,
  summaries, and document generation.

## Current Folder Layout

```text
PkuClaw/
├── ARCHITECTURE.md
├── README.md
├── skill.md
├── pyproject.toml
├── configs/
│   └── config.example.toml
├── crates/
│   └── pku3b/
│       ├── Cargo.toml
│       ├── Cargo.lock
│       ├── README.md
│       ├── build.rs
│       ├── assets/
│       └── src/
│           ├── config.rs
│           ├── http.rs
│           ├── main.rs
│           ├── multipart.rs
│           ├── pdf.rs
│           ├── qs.rs
│           ├── ttshitu.rs
│           ├── utils.rs
│           └── walkdir.rs
├── pkuclaw/
│   ├── __init__.py
│   ├── cli.py
│   ├── channels/
│   │   ├── __init__.py
│   │   └── feishu.py
│   ├── connectors/
│   │   ├── __init__.py
│   │   └── pku3b.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── events.py
│   │   ├── jobs.py
│   │   └── router.py
│   ├── workflows/
│   │   ├── __init__.py
│   │   ├── notes.py
│   │   └── sync.py
│   └── workers/
│       ├── __init__.py
│       └── codex.py
├── scripts/
│   └── feishu_smoke.py
├── sub-skills/
│   ├── runtime/
│   ├── tasks/
│   └── tools/
```

## Runtime Loops

```text
Monitor loop
  pku3b/course.pku scans -> snapshots -> diff -> events -> notifications

Chat loop
  Feishu message -> router -> course state / workflow / Codex worker -> reply

Agent loop
  queued jobs -> Codex worker -> artifacts -> job state -> Feishu push
```

## Near-Term Commands

```bash
pkuclaw doctor
pkuclaw sync
pkuclaw status
pkuclaw daemon
pkuclaw bot feishu
pkuclaw notes "课程名"
```
