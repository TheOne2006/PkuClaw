# PkuClaw

PkuClaw is a daemon-centered, multi-channel, self-configurable study-agent
runtime for PKU workflows. It is not a Feishu-only bot, not a pku3b wrapper,
and not tied to one agent provider.

The core idea is:

```text
Channels / Schedulers / Agent MCP
        -> CoreRuntime
        -> AgentWrapper
        -> Agent Provider (Codex now; Claude/Kimi later)
        -> Skills, prompt fragments, files, and external tools
```

## Runtime Model

- `CoreRuntime` is the daemon control plane. It accepts messages from channels,
  receives loop ticks, implements daemon MCP tools, creates runs, applies runtime
  policy, and owns access to state/config/channel send operations.
- `Channels` are thin adapters for user-facing transports. Feishu is the first
  implementation; Web and WeChat are planned. Channels convert platform events
  into runtime messages and render `AgentEvent` streams back to users.
- `LoopManager` is CoreRuntime's scheduler component. It hot-loads configured
  loop specs and asks CoreRuntime to create periodic runs. Loop business logic
  belongs to the agent and injected skills, not to the scheduler.
- `AgentWrapper` is the run compiler. Before every run it hot-loads runtime
  configuration, builds the full prompt, injects prompt fragments/sub-skills/tool
  docs, selects the agent provider, and writes run artifacts.
- `Agent Providers` perform the actual work. Codex is implemented first. Claude
  Code, Kimi Code, or other providers should fit the same provider boundary.
- `Daemon MCP` is the internal Agent -> CoreRuntime control surface. MCP protocol
  handling lives in `pkuclaw/mcp`; real tool behavior belongs to CoreRuntime.
- `Skills` are business workflow instructions. They teach agents how to sync
  notices, do homework, write notes, parse PDFs, use pku3b, and coordinate
  subagents.

## Run Sources

All agent executions are normalized as runs. The important source types are:

- `realtime`: a user sends a message through Feishu/Web/WeChat; the channel gets
  a streaming answer.
- `loop`: a configured periodic task fires; the run is silent by default and only
  notifies through daemon MCP when important.
- `mcp` / `manual` / `system`: future sources for agent-created runs, CLI/manual
  triggers, and daemon maintenance tasks.

Control commands such as mode/model/status changes are local runtime operations;
they do not need an agent run unless explicitly converted into one.

## Configuration Model

Runtime behavior is file-backed and hot-loaded. The daemon must remain runnable
when live config is broken.

- `configs/config.toml`: boot config. It contains credentials, base paths, and
  bind addresses. Agents should not modify it by default.
- `configs/runtime/`: live runtime config. Agent settings, loop specs, prompt
  fragments, skill registry, notification policy, and permissions belong here.
- Runtime files are parsed and validated before use. On failure CoreRuntime uses
  the last valid snapshot; if none exists, immutable defaults are used.
- Runtime writes should be atomic, backed up, and audited. The preferred write
  path is daemon MCP -> CoreRuntime -> validated file update. Direct file edits
  are still tolerated because the next hot-load validates and falls back safely.

## Layout

```text
pkuclaw/
  core/             # shared models, store, routing, control parsing
  channels/         # Feishu now; Web/WeChat later
  agents/           # AgentWrapper context, run orchestration, event sinks
  code_agents/      # concrete agent providers; Codex first
  mcp/              # MCP protocol layer and tool schemas -> CoreRuntime
  loop.py           # CoreRuntime-owned LoopManager implementation
  runtime_config.py # hot-loaded live runtime config loader
configs/
  config.toml       # local boot secrets/config, ignored by git
  config.example.toml
  runtime/          # hot-loaded live runtime files
sub-skills/         # task/tool/runtime instructions injected into prompts
crates/pku3b/       # external PKU teaching-network CLI, used by agents via skills
tests/              # backend/runtime tests
```

## Current Implementation Status

Implemented V1 pieces:

- Feishu realtime adapter with CardKit streaming output.
- Codex provider via `codex exec --json`.
- SQLite store for conversations, runs, artifacts, and channel messages.
- Runtime config loader with fallback warnings and hot-loaded loop specs.
- CoreRuntime and LoopManager naming/model in the Python runtime.
- Channel MCP tool server for sending/updating channel messages.

Planned/ongoing architecture work:

- Move runtime orchestration into a dedicated `pkuclaw/runtime/` package.
- Split live runtime files into `runtime.json`, `loops.json`, `skills.json`,
  and `prompts/`.
- Add runtime MCP tools for config/loop/status operations.
- Add audit/backup/atomic-write support for agent-modified runtime files.
- Introduce channel and provider protocols for Web/WeChat and Claude/Kimi.

## Local Run

```bash
uv sync
uv run pkuclaw daemon
```

For Feishu realtime-only UI debugging:

```bash
uv run pkuclaw realtime feishu
```

## Feishu Controls

Feishu custom menu keys and text commands can update local conversation/runtime
settings without calling an agent:

- `mode:fast`
- `mode:standard`
- `mode:deep`
- `model:<model-name>`
- `reasoning:low|medium|high|xhigh`
- `status:current`
- `runs:recent`

Normal chat messages become realtime runs. Periodic work is driven by configured
loop specs. Agents may proactively notify users through daemon MCP tools when
policy allows it.
