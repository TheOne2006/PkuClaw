# PkuClaw Agent Notes

## Current Architecture Intent

PkuClaw is a daemon-centered, multi-channel, self-configurable study-agent
runtime. The central abstraction is `CoreRuntime`.

- `CoreRuntime` is the daemon control plane. All channel ingress, loop ticks,
  daemon MCP tool calls, runtime config changes, run creation, channel sends,
  and state writes should pass through it.
- `channels/` contains user-facing transport adapters only. Feishu/Web/WeChat
  own platform presentation and transport, but they must not own business logic,
  runtime config, loop management, or agent provider selection.
- `mcp/` contains the Agent -> CoreRuntime protocol layer. MCP is not a channel.
  Tool handlers should validate protocol input and delegate real behavior to
  CoreRuntime methods.
- `LoopManager` is a CoreRuntime-owned scheduler. It hot-loads loop specs and
  asks CoreRuntime to create loop runs. It must not implement course/business
  logic itself.
- `AgentWrapper` is the run compiler. It builds prompts, hot-loads runtime
  snapshots, injects prompt fragments/sub-skills/tool docs, selects the concrete
  agent provider, normalizes events, and writes run artifacts.
- Agent providers are replaceable. Codex is first; Claude/Kimi should fit the
  same `execute(context, prompt, sink) -> AgentResult` boundary.
- Skills carry business intelligence. Daemon/core should not hard-code homework,
  notes, notification sync, PDF parsing, or pku3b workflows.

## Engineering Rules

- Prefer one explicit interface over duplicated fallback paths. If an old path
  conflicts with the CoreRuntime model, migrate call sites instead of preserving
  parallel semantics.
- Keep CoreRuntime as the only layer that mutates runtime state, loop specs,
  channel outbox operations, and run lifecycle state.
- Keep channel adapters thin. They should convert platform events to runtime
  messages and render runtime events back to the platform.
- Keep MCP protocol code thin. MCP tools expose capabilities; CoreRuntime owns
  the capabilities.
- Agents emit structured events through `AgentEventSink`; channels must not parse
  raw provider stdout directly.
- Runtime settings are hot-read at run boundaries. Settings changed during a run
  apply to the next run unless a tool explicitly documents immediate behavior.
- Runtime config is file-backed. Agent edits must be validated, backed up,
  auditable, and safe to fall back from.
- Boot config is not live runtime config. Agents should not modify boot secrets,
  bind hosts, or credential settings unless a high-risk policy explicitly allows
  it and the user confirms.
- pku3b is exposed to Agents through skill documentation by default, not as a
  daemon MCP tool. Introduce a daemon-level pku3b layer only if it is designed as
  a deterministic, audited snapshot service.
- Homework submission, destructive config changes, mass notifications, and other
  high-risk operations require explicit user confirmation.
