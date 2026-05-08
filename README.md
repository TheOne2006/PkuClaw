# PkuClaw

PkuClaw is a lightweight study-agent runtime for PKU workflows. It normalizes user messages and scheduled background checks into Agent runs, keeps runtime configuration in editable files, and uses a channel-neutral outbox queue when realtime runs need to deliver artifacts or loops need to notify the user.

## Current architecture

PkuClaw has exactly two Agent run sources:

- `realtime`: triggered by a user message or a configured quick action. The Agent receives a minimal prompt and should answer the user directly in natural Chinese.
- `loop`: triggered by `LoopManager`. The Agent runs a configured background task, stays silent by default, and uses the channel outbox skill only when it needs to notify the user.

Runtime files are ordinary files under `configs/runtime/`:

```text
configs/runtime/
  runtime.example.json  # tracked template for local runtime config
  runtime.json          # untracked, hot-loaded runtime config and loop specs
  events.json           # realtime quick action catalog
  prompts.json          # hot-loaded realtime/loop prompt templates
  skills.json           # skill catalog metadata
  skills/               # runtime skill markdown files
```

Copy `runtime.example.json` to `runtime.json` before setting local loop targets.
`runtime.json` is intentionally ignored because it may contain channel-specific
identifiers such as Feishu `open_id`/`chat_id`. Agents may read and edit these
files directly when the task calls for it, but should not commit `runtime.json`.

## Realtime quick actions

`configs/runtime/events.json` defines PkuClaw-owned event ids for user-triggered streaming realtime tasks, such as checking course updates or weekly DDLs. Channel adapters may map platform menu keys to these ids, or pass through keys that are already PkuClaw ids. UI-only channel events stay in the channel layer.

A quick action creates `source=realtime` with `task` as the user request and `skill_names` as suggested skills. It does not create a loop. If it generates an image or file artifact, it may use the channel outbox skill to deliver that artifact without duplicating the realtime answer card.

## Skills

The skill source of truth is `configs/runtime/skills.json` plus `configs/runtime/skills/**`.

Prompt builders render only the Skill Catalog fields:

- `name`
- `description`
- `path`
- `dependencies`
- `allowed_sources`
- `requires_confirmation`

Skill markdown bodies are not injected by default. Ordinary realtime runs start with no suggested skills. Realtime quick actions and loop runs can list configured `skill_names` as suggested skills, but the Agent still reads the files by path when needed.

`sub-skills/` has been removed as a runtime skill source.

## Prompt templates

Realtime and loop prompt wording is hot-read from `configs/runtime/prompts.json`.
AgentWrapper only supplies runtime variables such as the Skill Catalog, User Request,
loop metadata, and channel outbox skill hint. To adjust the assistant identity,
rules, objective, suggested skill section, or loop notification wording, edit
`prompts.json` instead of code.

## Channel outbox queue

Realtime artifact delivery and loop notifications go through a runtime skill and a file-backed daemon queue:

- `configs/runtime/skills/tools/channel-outbox.md`
- `scripts/pkuclaw_outbox.py`

The model-visible API is limited to `text`, `image`, and `file`. The script writes a random JSON job under the shared queue. The daemon scans the queue about every 5 seconds, resolves targets from run/loop context, and sends through the registered channel backend. Cards and update-card are internal channel/runtime implementation details.

## Runtime flow

```mermaid
flowchart TD
  User[User message] --> Realtime[CoreRuntime creates source=realtime]
  Scheduler[LoopManager tick] --> Loop[CoreRuntime creates source=loop]
  Realtime --> Wrapper[AgentWrapper]
  Loop --> Wrapper
  RuntimeFiles[configs/runtime/runtime.json (local) + events.json + prompts.json + skills.json + skills/**] --> Wrapper
  Wrapper --> Agent[Codex Agent]
  Agent --> Reply[Realtime reply]
  Agent --> Script[Channel outbox queue script]
  Script --> Queue[File outbox queue]
  Queue --> Daemon[Daemon queue worker]
  Daemon --> Channel[Registered channel backend]
```


## Documentation site

PkuClaw ships an Astro Starlight documentation site under `docs-site/`.

```bash
cd docs-site
npm install
npm run dev
npm run build
```

GitHub Pages deployment is configured through `.github/workflows/deploy-docs.yml`.
For the main repository, the site is built with `base: '/PkuClaw'` and deploys to
`https://theone2006.github.io/PkuClaw/` after Pages is set to use GitHub Actions.

## Development

Install the package in editable mode and run checks from the repository root:

```bash
python -m compileall pkuclaw scripts
python -m unittest discover
```

See `ARCHITECTURE.md`, `docs/DEVELOPMENT.zh.md`, and `configs/runtime/README.md` for more details.

Code layout rule of thumb: `pkuclaw/core/` owns run orchestration,
`pkuclaw/runtime/` owns hot-loaded runtime file readers, `pkuclaw/agents/`
owns Agent execution/providers, and `pkuclaw/channels/` owns platform adapters.
