# PkuClaw Runtime Files

`configs/runtime/` is the editable runtime surface for Agents and operators.
Agents should read or modify these files directly when the task requires it:

```text
configs/runtime/
  runtime.json          # hot-loaded agent/loop/notification runtime config
  events.json           # realtime quick action catalog
  prompts.json          # hot-loaded realtime/loop prompt templates
  skills.json           # skill catalog metadata and dependency graph
  skills/               # runtime skill markdown files
    runtime/            # PkuClaw runtime/config/skill authoring rules
    pku3b/              # pku3b install and usage docs
    tasks/              # user-facing study/course tasks
    tools/              # shared non-pku3b helpers
```

## Run sources

PkuClaw has only two Agent run sources:

- `realtime`: a user message or configured quick action that should receive a direct streaming reply.
- `loop`: a scheduled background task that stays silent unless it finds something important.

There is no natural-language routing field. Ordinary realtime messages use `suggested_skills = ()` by default. Realtime quick actions use `configs/runtime/events.json`. Loop runs use the explicit `skill_names` configured on the loop entry in `runtime.json`; these are rendered as suggested skills, not injected as full markdown bodies.

## Realtime quick actions

`events.json` defines PkuClaw-owned quick action ids such as `course_updates` or `weekly_deadlines`:

- `id`
- `title`
- `description`
- `task`
- `skill_names`
- `ack`
- `enabled`

Channel adapters may map raw platform menu/button keys to these ids, or pass them through when the platform key is already a PkuClaw event id. Platform-specific noise and UI-only actions should stay in the channel adapter and should not enter CoreRuntime.

A configured quick action creates a normal streaming realtime run:

```text
source = realtime
task = events.json[].task
suggested_skills = events.json[].skill_names
```

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

## Prompt templates

`prompts.json` defines the Agent-facing text for the two supported sources:

- `realtime.template`
- `realtime.suggested_skills_template`
- `loop.template`

AgentWrapper hot-loads this file for each prompt build and fills named variables.
Use doubled braces (`{{` and `}}`) if a template needs literal braces.
Keep realtime templates user-facing and avoid MCP tool text there; keep loop
templates silent-by-default and use only channel notification tool wording.

## Notifications

Loop prompts expose only channel notification tools:

- `channel_send_text`
- `channel_send_card`
- `channel_send_image`
- `channel_update_card`

Use them only for important loop findings. Realtime prompts do not include MCP tools.

Configure the shared loop notification target once under `notifications`:

```json
{
  "notifications": {
    "policy": "important_only",
    "default_channel": "feishu",
    "default_target_type": "open_id",
    "default_target_id": "ou_xxx"
  }
}
```

Individual loops may set the same three target fields to override the shared
target for that loop. MCP send tools do not accept `channel`, `target_type`,
`target_id`, or `loop_id` arguments from the Agent; the daemon scopes each loop
run and resolves the override automatically.
