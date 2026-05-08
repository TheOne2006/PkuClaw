# PkuClaw Runtime Files

`configs/runtime/` is the editable runtime surface for Agents and operators.
Agents should read or modify these files directly when the task requires it:

```text
configs/runtime/
  runtime.example.json  # tracked template for local runtime config
  runtime.json          # untracked, hot-loaded agent/loop/notification runtime config
  events.json           # realtime quick action catalog
  prompts.json          # hot-loaded realtime/loop prompt templates
  skills.json           # skill catalog metadata and dependency graph
  skills/               # runtime skill markdown files
    runtime/            # PkuClaw runtime/config/skill authoring rules
    pku3b/              # pku3b install and usage docs
    tasks/              # user-facing study/course tasks
    tools/              # shared helpers, including channel outbox scripts
  templates/            # reusable runtime templates such as LaTeX note templates
```

## Run sources

PkuClaw has only two Agent run sources:

- `realtime`: a user message or configured quick action that should receive a direct streaming reply.
- `loop`: a scheduled background task that stays silent unless it finds something important.

There is no natural-language routing field. Ordinary realtime messages use `suggested_skills = ()` by default. Realtime quick actions use `configs/runtime/events.json`. Loop runs use the explicit `skill_names` configured on the loop entry in the local `runtime.json`; the daemon also suggests `tools/channel-outbox.md` for every loop run. Suggested skills are metadata, not injected full markdown bodies.

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

## Templates

Reusable, non-secret generation templates live under `configs/runtime/templates/`.
For course-note generation, `tasks/write-notes.md` uses:

```text
configs/runtime/templates/latex/course-note/note.tex
configs/runtime/templates/latex/course-note/chapter.tex
```

Agents should copy/render these templates into the target course directory and
replace all `@@PLACEHOLDER@@` tokens before compiling. Template files in
`configs/runtime/templates/` are not compiled directly.

## Prompt templates

`prompts.json` defines the Agent-facing text for the two supported sources:

- `realtime.template`
- `realtime.suggested_skills_template`
- `loop.template`

AgentWrapper hot-loads this file for each prompt build and fills named variables.
Use doubled braces (`{{` and `}}`) if a template needs literal braces.
Keep realtime templates user-facing and avoid full outbox script bodies there; keep loop templates silent-by-default and point to the Channel Outbox Skill.

## Channel outbox

Agents can use one channel-neutral outbox skill when they truly need to send a user-visible message outside the normal realtime streaming card:

- `configs/runtime/skills/tools/channel-outbox.md`

The model-visible capabilities are intentionally limited to:

- `python scripts/pkuclaw_outbox.py text --text "..." --title "optional"`
- `python scripts/pkuclaw_outbox.py image --path image.png --caption "optional"`
- `python scripts/pkuclaw_outbox.py file --path result.pdf --caption "optional"`

There is no model-visible card/update-card API. Feishu cards, streaming card updates, Markdown rendering, resource uploads, and target ids are runtime/channel-adapter internals.

Realtime runs may use image/file to deliver generated artifacts, but should not send extra text that merely duplicates the realtime running card. Loop runs use outbox only when the Notification Policy says the user should be notified.

Copy `runtime.example.json` to `runtime.json` for local operation. Configure the shared loop fallback target once under `notifications` in local `runtime.json`:

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

Individual loops may set the same three target fields to override the shared target for that loop. Do not commit `runtime.json`; it may contain local channel identifiers such as Feishu `open_id` or `chat_id`. The provider sets `PKUCLAW_OUTBOX_QUEUE_DIR`, `PKUCLAW_RUN_ID`, and `PKUCLAW_RUN_SOURCE` for every run, plus `PKUCLAW_LOOP_ID` for loop runs. The daemon resolves a run target first, then loop override, then shared default.
