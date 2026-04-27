# Architecture

PkuClaw is a multi-entry backend with a deterministic data backbone and a
code-agent layer.

## Runtime Boundaries

```text
Feishu / Web / WeChat
        |
        v
Channel adapter
  - platform transport
  - cards / UI rendering
        |
        v
CoreLoop
  - local controls
  - conversation state
  - live runtime config read
  - task routing
  - run records
  - code-agent event dispatch
        |
        +--> TeachingBackbone -> pku3b -> snapshots
        |
        +--> CodeAgent -> CodexAgent -> codex exec/resume --json -> artifacts
                         |
                         v
                 CodeAgentEventSink -> channel UI updates
```

## Design Rules

- Channel adapters translate platform events into `ChannelMessage` and own
  presentation. Feishu uses interactive cards and patches the same card during
  a run instead of streaming raw text messages.
- CoreLoop owns product behavior: modes, status, routing, and run creation.
- CoreLoop stores code-agent settings, but each adapter interprets them. For
  example, `fast` maps to Codex reasoning effort, not to a CoreLoop behavior.
- Runtime behavior lives in `configs/runtime/agent.toml`. The core loop,
  code-agent adapters, and daemon loop read it on demand so running agents can
  safely tune model, mode, reasoning effort, and scan interval.
- TeachingBackbone owns scheduled course-data collection. It is ordinary
  backend code, not an agent.
- CodeAgent adapters handle slow reasoning and artifact generation. They emit
  structured `CodeAgentEvent` objects through a required sink; channel adapters
  consume those events and must not parse raw Codex stdout. The current adapter
  is Codex; Claude Code or Kimi Code can be added by implementing the same
  interface.
- `crates/pku3b` remains the teaching-network engine and can evolve with this
  backend.
