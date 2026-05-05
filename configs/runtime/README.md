# PkuClaw Runtime Config

This directory is the live, hot-loaded runtime configuration area. Boot secrets
and bind addresses belong in `configs/config.toml`; live agent behavior belongs
here.

Target files:

```text
runtime.json    # current live runtime snapshot; agent/provider/loops/policy
loops.json      # future optional split for dynamic loop specs
skills.json     # future skill registry
prompts/        # prompt fragments loaded before runs
backups/        # automatic backups before runtime writes
```

Safety model:

1. CoreRuntime reads live config before realtime runs, loop ticks, and runtime MCP
   mutations.
2. Files are parsed, validated, merged with immutable defaults, and normalized
   into a runtime snapshot.
3. If live config is invalid, CoreRuntime falls back to the last valid snapshot;
   if none exists, immutable defaults keep the daemon runnable.
4. Runtime writes should go through daemon MCP where possible so CoreRuntime can
   validate, backup, write atomically, and audit the change.
5. Direct file edits are tolerated, but invalid edits must never crash the daemon.
