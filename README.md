# PkuClaw

PkuClaw is a daemon-centered agent runtime for PKU study workflows. It is not a
pku3b wrapper, not only a Feishu bot, and not a Codex-only project.

The V1 runtime is organized around:

- `Daemon`: always-online parent process. It starts the realtime thread, loop
  thread, and channel MCP tool server.
- `Realtime Thread`: Feishu now, future Web/WeChat later. It receives user
  messages and renders streaming agent output.
- `Loop Thread`: a timer only. It periodically asks Agent-Wrapper to run the
  configured loop prompt.
- `Agent-Wrapper`: the central orchestration layer. It hot-loads runtime JSON,
  builds prompts, injects prompt fragments and sub-skills, selects the concrete
  agent, and writes artifacts.
- `Agent`: Codex first. Claude Code or Kimi Code can be added later without
  changing daemon-level concepts.
- `MCP Tools`: generic channel action tools. V1 exposes channel send/update
  wrappers; pku3b is not an MCP tool.
- `pku3b`: external CLI tool. Agents learn how to use it through skill docs and
  call it directly when needed.

Runtime behavior is split from boot secrets. `configs/config.toml` is loaded at
startup for credentials and base paths. `configs/runtime/agent.json` is read by
Agent-Wrapper before each run, so agent settings, loop prompt, prompt fragments,
and skills can change without restarting the daemon.

## Layout

```text
pkuclaw/
  agents/          # Agent-Wrapper context, run orchestration, silent sink
  channels/        # Channel adapters
    feishu/        # Gateway, event handlers, CardKit renderer/sink/tools
  core/            # Realtime/control routing and local state
  loop.py          # Periodic loop thread
  mcp/             # Generic channel tool server surface
  code_agents/     # Concrete agent implementation details, Codex first
crates/pku3b/      # External teaching-network CLI tool, kept in-tree
configs/           # Static boot config
configs/runtime/   # Agent-editable live JSON config
sub-skills/         # Task/tool/runtime instructions injected into prompts
tests/             # Backend tests
```

## Local Run

```bash
uv sync
uv run pkuclaw daemon
```

For Feishu realtime-only UI debugging:

```bash
uv run pkuclaw realtime feishu
```

## Feishu Menu Keys

Use bot custom-menu event actions for instant local controls:

- `mode:fast`
- `mode:standard`
- `mode:deep`
- `model:<model-name>`
- `reasoning:low|medium|high|xhigh`
- `status:current`
- `runs:recent`

These controls do not call an agent. Normal chat messages enter the realtime
thread, then Agent-Wrapper, then the concrete agent.

Feishu run output is CardKit-first: the adapter creates one Card JSON 2.0
resource, sends that `card_id` as an interactive message, and updates the same
CardKit card as a ChatGPT-like streaming answer. The main card only shows
status, elapsed time, the assistant answer, and a single run-detail button.

Run cards use Card JSON 2.0 and the `markdown` rich-text component. Avoid
falling back to `im.message.patch`, plain text, or `div.text.lark_md` for long
agent output, because those paths either do not provide native card streaming or
only support a narrower Markdown subset.

Feishu app events should include `im.message.receive_v1` and
`application.bot.menu_v6`. Enable the `card.action.trigger` callback for the
`查看运行详情` button. The callback sends an independent detail card with raw
Codex event pages; it does not mutate the main answer card.

When running the full daemon, Codex is launched with a local MCP server config
pointing at `http://<mcp.host>:<mcp.port>/mcp`, exposing the generic
`channel_*` tools to the agent. `pkuclaw realtime feishu` does not start the
loop or MCP server; use `pkuclaw daemon` for the full V1 topology.
