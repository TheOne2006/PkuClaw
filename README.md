# PkuClaw

PkuClaw is a lightweight study-agent runtime for PKU workflows. It normalizes user messages and scheduled background checks into Agent runs, keeps runtime configuration in editable files, and uses channel notification tools when background loops need to notify the user.

## Current architecture

PkuClaw has exactly two Agent run sources:

- `realtime`: triggered by a user message or a configured quick action. The Agent receives a minimal prompt and should answer the user directly in natural Chinese.
- `loop`: triggered by `LoopManager`. The Agent runs a configured background task, stays silent by default, and uses channel notification tools only when it finds important changes.

Runtime files are ordinary files under `configs/runtime/`:

```text
configs/runtime/
  runtime.json          # hot-loaded runtime config and loop specs
  events.json           # realtime quick action catalog
  prompts.json          # hot-loaded realtime/loop prompt templates
  skills.json           # skill catalog metadata
  skills/               # runtime skill markdown files
```

Agents may read and edit these files directly when the task calls for it. Runtime config is not managed through MCP tools.

## Realtime quick actions

`configs/runtime/events.json` defines PkuClaw-owned event ids for user-triggered streaming realtime tasks, such as checking course updates or weekly DDLs. Channel adapters may map platform menu keys to these ids, or pass through keys that are already PkuClaw ids. UI-only channel events stay in the channel layer.

A quick action creates `source=realtime` with `task` as the user request and `skill_names` as suggested skills. It does not create a loop and does not use MCP notification tools.

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
loop metadata, and channel notification tool list. To adjust the assistant identity,
rules, objective, suggested skill section, or loop notification wording, edit
`prompts.json` instead of code.

## MCP scope

MCP is reserved for loop-initiated user notifications. The available tools are:

- `channel_send_text`
- `channel_send_card`
- `channel_send_image`
- `channel_update_card`

Realtime prompts do not include MCP tools. Runtime read/write management tools are not exposed.

## Runtime flow

```mermaid
flowchart TD
  User[User message] --> Realtime[CoreRuntime creates source=realtime]
  Scheduler[LoopManager tick] --> Loop[CoreRuntime creates source=loop]
  Realtime --> Wrapper[AgentWrapper]
  Loop --> Wrapper
  RuntimeFiles[configs/runtime/runtime.json + events.json + prompts.json + skills.json + skills/**] --> Wrapper
  Wrapper --> Agent[Codex Agent]
  Agent --> Reply[Realtime reply]
  Agent --> Notify[Loop channel notification tools]
```

## Development

Install the package in editable mode and run checks from the repository root:

```bash
python -m compileall pkuclaw
python -m unittest discover
```

See `ARCHITECTURE.md`, `docs/DEVELOPMENT.zh.md`, and `configs/runtime/README.md` for more details.
