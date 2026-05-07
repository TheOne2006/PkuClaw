# PkuClaw Runtime Files

`configs/runtime/` is the editable runtime surface for Agents and operators.
Agents should read or modify these files directly when the task requires it:

```text
configs/runtime/
  runtime.json          # hot-loaded agent/loop/notification runtime config
  skills.json           # skill catalog metadata and dependency graph
  skills/               # runtime skill markdown files
    runtime/
    tasks/
    tools/
```

## Run sources

PkuClaw has only two Agent run sources:

- `realtime`: a user message that should receive a direct natural-language reply.
- `loop`: a scheduled background task that stays silent unless it finds something important.

There is no natural-language routing field. Realtime runs use `suggested_skills = ()` by default. Loop runs use the explicit `skill_names` configured on the loop entry in `runtime.json`; these are rendered as suggested skills, not injected as full markdown bodies.

## Skills

The source of truth for skills is:

- `configs/runtime/skills.json`
- `configs/runtime/skills/**`

Each catalog entry provides:

- `name`
- `description`
- `path`
- `dependencies`
- `allowed_sources`
- `requires_confirmation`

Prompt builders render only the Skill Catalog. Agents choose relevant skills and read the markdown files by `path` when needed. `configs/runtime/skills/` is writable so Agents can create or update skills during runtime when explicitly appropriate.

`sub-skills/` is no longer a runtime skill source.

## Notifications

Loop prompts expose only channel notification tools:

- `channel_send_text`
- `channel_send_card`
- `channel_send_image`
- `channel_update_card`

Use them only for important loop findings. Realtime prompts do not include MCP tools.
