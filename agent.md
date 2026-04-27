# PkuClaw Agent Notes

## Engineering Rules

- Do not preserve backward compatibility when it creates duplicate paths, fallback branches, or unclear semantics. Prefer one explicit interface and update all call sites.
- Keep channel adapters thin: Feishu/Web/WeChat own presentation and transport, while `CoreLoop` owns task routing and code-agent orchestration.
- Code agents emit structured events through `CodeAgentEventSink`; channels must not parse raw Codex stdout directly.
- Runtime settings are hot-read at run boundaries. Settings changed during a run apply to the next run, not the already-running process.
- Prefer readable, composable modules over large mixed files. Split API clients, renderers, sinks, and core orchestration when their responsibilities differ.
