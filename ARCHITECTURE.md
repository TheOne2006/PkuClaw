# PkuClaw Architecture

PkuClaw now uses a small runtime model: two Agent run sources, editable runtime files, catalog-based skills, and channel notification tools for background loops.

## 1. Run sources

Only two Agent run sources exist:

| source | Trigger | Behavior |
| --- | --- | --- |
| `realtime` | User message | Answer the user directly. No preselected skills. |
| `loop` | `LoopManager` scheduled tick | Run a configured background task. Stay silent unless important. |

CoreRuntime does not classify user text into task categories. A realtime message creates `source="realtime"` and `suggested_skills=()`. A loop creates `source="loop"` and uses the loop's configured `skill_names` as suggested skills.

## 2. Runtime files

Runtime state is exposed as editable files:

```text
configs/runtime/
  runtime.json
  skills.json
  skills/
    runtime/
    tasks/
    tools/
```

Agents read or edit these files directly when needed. The runtime configuration is not managed through MCP read/write tools.

## 3. Skill Catalog

`configs/runtime/skills.json` is the catalog source of truth. It points at markdown files under `configs/runtime/skills/**` and contains:

- `name`
- `description`
- `path`
- `dependencies`
- `allowed_sources`
- `requires_confirmation`

AgentWrapper renders the catalog into prompts. Skill bodies are not injected by default. Loop suggestions list relevant skill metadata only; the Agent decides which files to open.

If `skills.json` is missing or invalid, the daemon keeps running with an empty catalog and a warning.

## 4. Prompt builders

AgentWrapper branches by `source`:

- `_build_realtime_prompt(context)` creates `# PkuClaw Realtime Task` with a short identity, reply rules, Skill Catalog, and User Request.
- `_build_loop_prompt(context)` creates `# PkuClaw Loop Task` with loop id, scheduled time, sink mode, notify policy, notification target, notification rules, channel notification tools, Skill Catalog, suggested skills, and Task.

Realtime prompts do not include run ids, source labels, provider settings, repository paths, runtime paths, recent runs, prompt fragments, MCP tools, or full skill markdown bodies.

Loop prompts do not reuse realtime reply rules and do not include runtime management tools.

## 5. MCP scope

MCP is limited to loop notifications. The exposed tools are:

- `channel_send_text`
- `channel_send_card`
- `channel_send_image`
- `channel_update_card`

Runtime status/config/loop management tools are removed from the Agent-facing MCP surface.

## 6. Loop behavior

`LoopManager` hot-loads `configs/runtime/runtime.json`, schedules enabled loops, and asks CoreRuntime to create `source="loop"` runs. Loop prompts tell the Agent:

- no important change: stay silent;
- important change: use channel notification tools;
- final loop answers are for logs/artifacts and are not user-visible.

## 7. Repository layout

```text
pkuclaw/
  agents/             # AgentWrapper and sinks
  code_agents/        # Codex provider and runtime skill catalog loader
  core/               # CoreRuntime, shared models, Store
  mcp/                # channel notification tool schemas/handlers/server
  runtime_config.py   # hot-loads and validates runtime.json
configs/runtime/
  runtime.json
  skills.json
  skills/
```

`sub-skills/` is no longer used as a runtime skill source.
