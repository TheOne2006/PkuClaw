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
    tools/              # shared helpers, including loop notification scripts
```

## Run sources

PkuClaw has only two Agent run sources:

- `realtime`: a user message or configured quick action that should receive a direct streaming reply.
- `loop`: a scheduled background task that stays silent unless it finds something important.

There is no natural-language routing field. Ordinary realtime messages use `suggested_skills = ()` by default. Realtime quick actions use `configs/runtime/events.json`. Loop runs use the explicit `skill_names` configured on the loop entry in `runtime.json`; the daemon also suggests `tools/channel-notifier.md` for every loop run. Suggested skills are metadata, not injected full markdown bodies.

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
Keep realtime templates user-facing and avoid notification script text there; keep loop templates silent-by-default and point to the Notification Script Skill.

## Notifications

Loop prompts point to the loop-only Notification Script Skill:

- `configs/runtime/skills/tools/channel-notifier.md`

The documented script writes file-queue jobs for the daemon:

- `python scripts/pkuclaw_notify.py text --message "..."`
- `python scripts/pkuclaw_notify.py card --card-file card.json`
- `python scripts/pkuclaw_notify.py image --image-path image.png` (currently unsupported by daemon)
- `python scripts/pkuclaw_notify.py update-card --card-id ... --card-file card.json --sequence N`

Use it only for important loop findings. Realtime prompts do not include notification scripts.

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

Individual loops may set the same three target fields to override the shared target for that loop. The provider sets `PKUCLAW_LOOP_ID` and `PKUCLAW_NOTIFY_QUEUE_DIR` for loop runs, scripts write jobs to that queue, and CoreRuntime resolves the loop override or shared default target.
