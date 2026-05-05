# PkuClaw Runtime Config

This directory is the live, hot-loaded runtime configuration area. Boot secrets
and bind addresses belong in `configs/config.toml`; live agent behavior belongs
here.

Current source of truth:

```text
runtime.json    # current live runtime snapshot; agent/provider/loops/policy
skills.json     # skill registry: metadata, dependency graph, source policy
backups/        # automatic backups before runtime writes
```

Future optional split:

```text
loops.json      # dynamic loop specs
prompts/        # prompt fragments loaded before runs
```

Safety model:

1. CoreRuntime reads live config before realtime runs, loop ticks, and runtime MCP
   mutations.
2. Files are parsed, validated, merged with immutable defaults, and normalized
   into a runtime snapshot.
3. If live config is invalid, CoreRuntime falls back to the last valid snapshot;
   if none exists, immutable defaults keep the daemon runnable.
4. Runtime writes from Agents go through daemon MCP -> CoreRuntime so CoreRuntime
   can validate, backup the current `runtime.json`, write a `.tmp` file with
   fsync, atomically replace the source file, and audit the change in Store.
5. Direct human file edits are tolerated for operations/debugging, but they are
   validated only on hot-load and do not create Store audit records; invalid
   edits must never crash the daemon.

Write audit:

- The SQLite `runtime_changes` table records actor, optional run_id, file,
  action, old/new hashes, sanitized diff summary, status, and timestamp.
- Backups are written to `backups/runtime.<timestamp>.json` before replacement.

Loop specs:

- Enabled loops are hot-loaded by `LoopManager` and scheduled independently by
  `interval_seconds`.
- Loop runs are silent by default (`sink_mode: "silent"`); important user-visible
  updates should be sent by the Agent through daemon MCP channel tools.
- Optional `default_channel`, `default_target_type`, and `default_target_id`
  provide a default notification target for those MCP channel tools.
- `prevent_overlap` defaults to `true`, so a loop is not scheduled again while
  its previous run is still queued/running. If overlap is deliberately allowed,
  set `prevent_overlap: false` and use `max_concurrent_runs` to cap same-loop
  concurrency.

Skill registry:

- `skills.json` uses `schema_version: 1` and a `skills` array.
- Each skill entry has `name`, `intent`, `dependencies`, `allowed_sources`, and
  `requires_confirmation`.
- Names and dependencies are relative paths under `sub-skills/`; absolute paths
  and `..` escaping are rejected.
- `AgentWrapper` always injects the base runtime skill
  `runtime/codex-subagent.md`, then requested/default task skills, then resolved
  dependencies.
- If `skills.json` is missing or invalid, the loader falls back to an immutable
  default registry and records a runtime warning for the run prompt/metadata.
