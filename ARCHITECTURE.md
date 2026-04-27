# Architecture

PkuClaw is a multi-entry backend with a deterministic data backbone and an
agentic worker layer.

## Runtime Boundaries

```text
Feishu / Web / WeChat
        |
        v
Channel adapter
        |
        v
CoreLoop
  - local controls
  - conversation state
  - task routing
  - run records
  - worker dispatch
        |
        +--> TeachingBackbone -> pku3b -> snapshots
        |
        +--> CodexWorker -> codex exec/resume -> artifacts
```

## Design Rules

- Channel adapters translate platform events into `ChannelMessage` and send
  replies. They do not own business logic.
- CoreLoop owns product behavior: modes, status, routing, and run creation.
- TeachingBackbone owns scheduled course-data collection. It is ordinary
  backend code, not an agent.
- CodexWorker only handles slow reasoning and artifact generation. It receives
  capability contracts from Python, not loose repository skills.
- `crates/pku3b` remains the teaching-network engine and can evolve with this
  backend.
