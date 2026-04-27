# PkuClaw Agent Notes

## Engineering Rules

- Do not preserve backward compatibility when it creates duplicate paths, fallback branches, or unclear semantics. Prefer one explicit interface and update all call sites.
- Keep channel adapters thin: Feishu/Web/WeChat own presentation and transport. They call Realtime/Core routing, which delegates agent runs to Agent-Wrapper.
- Agent-Wrapper is the only layer that builds run prompts, hot-loads runtime JSON, injects prompt fragments/sub-skills/tool docs, selects the concrete Agent, and writes run artifacts.
- Agents emit structured events through `AgentEventSink`; channels must not parse raw Codex stdout directly.
- Runtime settings are hot-read at run boundaries. Settings changed during a run apply to the next run, not the already-running process.
- pku3b is exposed to Agents through skill documentation, not through daemon/core direct calls and not as an MCP tool.
- MCP tools are generic channel action wrappers. They are not runtime config, run status, run progress, or pku3b management APIs.
- Prefer readable, composable modules over large mixed files. Split API clients, renderers, sinks, and core orchestration when their responsibilities differ.
