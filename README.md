# PkuClaw

PkuClaw is a backend service for a PKU study assistant. It is no longer a
prompt/skill repository. The service is organized around three runtime layers:

- Channel adapters: Feishu now, web and WeChat later.
- Core loop: conversation state, local controls, routing, task queue, and Codex
  worker dispatch.
- Teaching backbone: deterministic course-data collection through the in-tree
  `crates/pku3b` connector.

Codex is a worker inside the backend, not the backend itself. Local controls
such as mode switching and status checks are handled directly by Python. Heavy
reasoning tasks such as note drafting, homework planning, and notice summaries
are sent to `codex exec` with backend capability contracts.

## Layout

```text
pkuclaw/
  channels/       # Feishu now; web/WeChat can be added here
  core/           # CoreLoop, state, control commands, routing
  backbone/       # Teaching-network collection via pku3b
  connectors/     # External/local tool adapters
  capabilities/   # Codex worker capability contracts
  workers/        # Codex CLI worker
crates/pku3b/     # Teaching-network engine, kept in-tree
configs/          # Local service config
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
- `status:current`
- `runs:recent`

These do not call Codex. Normal chat messages enter the core loop and may start
a Codex worker run.
