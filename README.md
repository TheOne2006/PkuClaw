# PkuClaw

PkuClaw is a backend service for a PKU study assistant. It is no longer a
prompt/skill repository. The service is organized around three runtime layers:

- Channel adapters: Feishu now, web and WeChat later. Feishu renders bot
  responses as interactive cards.
- Core loop: conversation state, local controls, routing, task queue, and code-agent
  dispatch.
- Teaching backbone: deterministic course-data collection through the in-tree
  `crates/pku3b` connector.

Codex is the first code-agent adapter inside the backend, not the backend
itself. Local controls such as mode switching and status checks are handled
directly by Python. Heavy reasoning tasks such as note drafting, homework
planning, and notice summaries are sent through the code-agent interface; today
that implementation is `codex exec --json`, streamed into structured events.

Runtime behavior is split from boot secrets. `configs/config.toml` is loaded at
startup for credentials and paths; `configs/runtime/agent.toml` is read before
each message, code-agent run, and daemon scan so a running agent can adjust its
own behavior without restarting the bot.

## Layout

```text
pkuclaw/
  channels/       # Feishu card adapter now; web/WeChat can be added here
  core/           # CoreLoop, state, control commands, routing
  backbone/       # Teaching-network collection via pku3b
  code_agents/    # Codex now; Claude Code/Kimi Code can be added here
  connectors/     # External/local tool adapters
  capabilities/   # Capability contracts exposed to code agents
crates/pku3b/     # Teaching-network engine, kept in-tree
configs/          # Local service config
configs/runtime/  # Agent-editable live config
tests/            # Backend tests
```

## Local Run

```bash
uv sync
uv run pkuclaw doctor
uv run pkuclaw bot feishu
```

Collect one teaching-network snapshot:

```bash
uv run pkuclaw sync
```

Run the teaching backbone loop:

```bash
uv run pkuclaw daemon
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

These do not call a code agent. Normal chat messages enter the core loop and may
start a Codex-backed code-agent run.

Feishu run output is card-first: the adapter sends one interactive card, patches
that card with throttled progress updates, and replaces it with a final summary
card when the code-agent run finishes.

Feishu app events should include `im.message.receive_v1`,
`application.bot.menu_v6`, and `card.action.trigger`.
