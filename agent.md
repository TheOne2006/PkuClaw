# PkuClaw Agent Notes

## Current Architecture Intent

PkuClaw is a daemon-centered, multi-channel, self-configurable study-agent
runtime. The central abstraction is `CoreRuntime`.

- `CoreRuntime` is the daemon control plane. All channel ingress, local
  notification queue jobs, runtime config changes, loop run creation,
  channel sends, and state writes should pass through it.
- `channels/` contains user-facing transport adapters only. Feishu/Web/WeChat
  own platform presentation and transport, but they must not own business logic,
  runtime config, loop management, or agent provider selection.
- `notify_queue/` contains the daemon file-queue notification worker.
  It is PkuClaw's own local file IPC surface, not a channel adapter. Workers
  validate queued JSON jobs and delegate real behavior to CoreRuntime methods.
- `LoopManager` is a CoreRuntime-owned scheduler. It hot-loads loop specs and
  asks CoreRuntime to create loop runs. It must not implement course/business
  logic itself.
- `AgentWrapper` is the run compiler. It builds prompts, hot-loads runtime
  snapshots, injects prompt fragments/skill metadata/notification script docs,
  selects the concrete agent provider, normalizes events, and writes run
  artifacts.
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
- Feishu gateway must be transport-only: runtime bootstrap creates Store,
  RuntimeConfigStore, AgentWrapper, LoopManager, and notification queue worker;
  gateway receives an existing CoreRuntime and registers only channel
  transport/backend pieces.
- Keep notification queue code thin. It exposes loop notification capabilities;
  CoreRuntime owns the capabilities.
- Notification queue workers must not call Feishu backend directly. They delegate
  to CoreRuntime's channel outbox registry.
- Loop notification scripts are thin clients. They only write JSON jobs to the
  shared queue, read `PKUCLAW_NOTIFY_QUEUE_DIR` / `PKUCLAW_LOOP_ID`, and print
  the daemon ack JSON response.
- LoopManager schedules via CoreRuntime only; it must not import or call
  AgentWrapper.
- AgentWrapper may hot-read runtime snapshots for prompt/run compilation, but it
  must not write runtime config, manage loops, start/stop daemons, or own channel
  outbox operations.
- Agents emit structured events through `AgentEventSink`; channels must not parse
  raw provider stdout directly.
- Runtime settings are hot-read at run boundaries. Settings changed during a run
  apply to the next run unless a tool explicitly documents immediate behavior.
- Runtime config is file-backed. Agent edits should be direct, minimal, reviewed
  through loader/schema tests, and never include boot secrets.
- Boot config is not live runtime config. Agents should not modify boot secrets,
  bind hosts, or credential settings unless a high-risk policy explicitly allows
  it and the user confirms.
- pku3b is exposed to Agents through skill documentation by default. Introduce a
  daemon-level pku3b layer only if it is designed as a deterministic, audited
  snapshot service.
- Homework submission, destructive config changes, mass notifications, and other
  high-risk operations require explicit user confirmation.
