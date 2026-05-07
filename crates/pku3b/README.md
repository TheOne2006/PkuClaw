# pku3b

`pku3b` is a raw JSON CLI for PKU Blackboard / course data. It is intended for PkuClaw, agents, cron jobs, and scripts.

This version is intentionally **not** compatible with the previous human-oriented CLI:

- stdout always contains one JSON envelope.
- stderr is reserved for logs.
- no colors, spinners, prompts, or interactive selection.
- missing arguments fail instead of opening an interactive picker.
- elective / auto-elect / TTShiTu / Bark / thesis library commands are removed.

## Output envelope

Success:

```json
{
  "ok": true,
  "data": {},
  "warnings": [],
  "errors": [],
  "meta": {
    "schema_version": 1,
    "generated_at": "2026-05-08T12:00:00+08:00"
  }
}
```

Failure:

```json
{
  "ok": false,
  "data": null,
  "warnings": [],
  "errors": [
    {
      "code": "auth_required",
      "message": "login required",
      "recoverable": true
    }
  ],
  "meta": {
    "schema_version": 1,
    "generated_at": "2026-05-08T12:00:00+08:00"
  }
}
```

Use `--pretty` to pretty-print the envelope.

## Commands

### Auth

```bash
pku3b auth login --username <id> --password <password> [--otp <code>]
pku3b auth status
pku3b auth logout
```

### Config

```bash
pku3b config get [username|password]
pku3b config set username <id>
pku3b config set password <password>
```

### Cache

```bash
pku3b cache status
pku3b cache clean
```

### Assignments

```bash
pku3b assignments list --term current
pku3b assignments list --term all
pku3b assignments download --id <assignment_id> --out-dir <dir> [--term current|all]
pku3b assignments submit --id <assignment_id> --file <path>
```

### Announcements

```bash
pku3b announcements list --term current
pku3b announcements list --term all
pku3b announcements get --id <announcement_id> [--term current|all]
```

### Timetable

```bash
pku3b timetable get
```

### Videos

```bash
pku3b videos list --term current
pku3b videos list --term all
pku3b videos download --id <video_id> --out-dir <dir> [--term current|all]
```

Video download requires `ffmpeg` on PATH.

## Build and check

```bash
cargo build --manifest-path crates/pku3b/Cargo.toml
cargo test --manifest-path crates/pku3b/Cargo.toml
```
