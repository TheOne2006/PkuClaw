# PkuClaw Architecture

PkuClaw uses a daemon-centered runtime model: two Agent run sources, editable runtime files, catalog-based skills, and a local channel outbox queue used by realtime and loop runs through scripts.

## 1. Run sources

Only two Agent run sources exist:

| source | Trigger | Behavior |
| --- | --- | --- |
| `realtime` | User message or configured quick action | Answer the user directly with streaming channel UI. Ordinary messages have no preselected skills; quick actions may have suggested skills. |
| `loop` | `LoopManager` scheduled tick | Run a configured background task. Stay silent unless important. |

CoreRuntime does not classify user text into task categories. An ordinary realtime message creates `source="realtime"` and `suggested_skills=()`. A configured realtime quick action is loaded from `configs/runtime/events.json` and also creates `source="realtime"`. A loop creates `source="loop"` and uses the loop's configured `suggested_skills` plus the channel outbox skill as suggested skills.

## 2. Runtime files

Runtime state is exposed as editable files:

```text
configs/runtime/
  runtime.json
  events.json
  prompts.json
  skills.json
  skills/
    runtime/            # runtime/config/skill authoring rules
    pku3b/              # pku3b install and usage docs
    tasks/              # user-facing study/course tasks
    tools/              # shared helpers, including channel outbox scripts
```

Agents read or edit these files directly when needed. Runtime configuration is not managed through an Agent protocol layer.

## 3. Realtime quick actions

`configs/runtime/events.json` defines user-triggered quick actions. Each event has an `id`, `task`, optional `suggested_skills`, and display metadata. Channel adapters decide whether a platform event is UI-only, ignored/no-op, or a quick action. For quick actions they pass a clean PkuClaw `event_id` to CoreRuntime; raw platform keys may be mapped or passed through only when already equal to a configured PkuClaw id.

CoreRuntime turns a configured event into a normal streaming realtime run. This preserves the two-source model: quick actions are realtime, not a third run type.

## 4. Skill Catalog

`configs/runtime/skills.json` is the catalog source of truth. It points at markdown files under `configs/runtime/skills/**` and contains:

- `name`
- `description`
- `path`
- `dependencies`
- `allowed_sources`
- `requires_confirmation`

AgentWrapper renders the catalog into prompts. Skill bodies are not injected by default. Suggested skills list relevant skill metadata only; the Agent decides which files to open.

If `skills.json` is missing or invalid, the daemon keeps running with an empty catalog and a warning.

## 5. Prompt builders

AgentWrapper branches by `source`:

- `_build_realtime_prompt(context)` creates `# PkuClaw Realtime Task` with a short identity, reply rules, Skill Catalog, Suggested Skills, and User Request. Ordinary realtime messages render Suggested Skills as `- none`; configured quick actions may provide explicit suggestions.
- `_build_loop_prompt(context)` creates `# PkuClaw Loop Task` with loop id, scheduled time, sink mode, notify policy, notification target, notification rules, Skill Catalog, suggested skills, and Task.

The wording/templates for both prompts are not hardcoded in `AgentWrapper`.
They are hot-read from `configs/runtime/prompts.json` on each prompt build.
Code only provides named variables such as `skill_catalog`, `user_request`,
`suggested_skills`, `loop_id`, `scheduled_at`, and `notification_target`.

Realtime prompts do not include run ids, source labels, provider settings, repository paths, runtime paths, recent runs, outbox script bodies, or full skill markdown bodies.

Loop prompts do not reuse realtime reply rules and do not include runtime management tools.

## 6. Channel outbox path

Realtime artifact delivery and loop notifications use the same channel-neutral outbox path:

```text
Agent -> channel-outbox skill -> scripts/pkuclaw_outbox.py -> file queue -> daemon queue worker -> CoreRuntime -> channel backend
```

The model-visible API is only text/image/file. The queue is file-backed under the app data directory by default, using `data/notify_queue/` with subdirectories such as `pending/`, `processing/`, `done/`, `failed/`, and `acks/`. Scripts do not open network sockets, do not call Feishu directly, do not parse runtime targets, and do not render cards. The daemon scans the queue about every 5 seconds and owns target resolution and channel delivery through CoreRuntime.

## 7. Loop behavior

`LoopManager` hot-loads `configs/runtime/runtime.json`, schedules enabled loops, and asks CoreRuntime to create `source="loop"` runs. Loop prompts tell the Agent:

- no important change: stay silent;
- important change: enqueue text/image/file through the Channel Outbox Skill;
- final loop answers are for logs/artifacts and are not user-visible.

Outbox requests contain only text/image/file content plus run context supplied by provider environment variables. The daemon resolves the original run channel target first, then a loop-specific `default_channel/default_target_type/default_target_id` override, then the shared `notifications.default_channel/default_target_type/default_target_id`. If none is configured, sends fail clearly instead of asking the Agent to guess a recipient. Card creation and update-card are channel/runtime internals, not model-visible APIs.

## 8. Repository layout

```text
pkuclaw/
  agents/             # AgentWrapper, sinks, artifacts, provider implementations
    providers/
      codex.py
  core/               # CoreRuntime, LoopManager, shared models, Store
    runtime.py
    loops.py
    models.py
    store.py
  notify_queue/       # daemon file notification queue worker
  runtime/            # hot-loaded editable runtime file readers
    config.py         # configs/runtime/runtime.json
    events.py         # configs/runtime/events.json
    prompts.py        # configs/runtime/prompts.json
    skills.py         # configs/runtime/skills.json + skills/**
scripts/              # channel outbox queue CLI
configs/runtime/
  runtime.json
  events.json
  prompts.json
  skills.json
  skills/
```

`sub-skills/` is no longer used as a runtime skill source.
