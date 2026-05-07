# pku3b

`pku3b` is PkuClaw's raw JSON access layer for PKU Blackboard / Portal course data.
It is intended for PkuClaw, agents, cron jobs, and scripts rather than humans at an
interactive terminal.

This version is intentionally **not** compatible with the previous human-oriented CLI:

- stdout always contains one JSON envelope.
- stderr is reserved for logs.
- no colors, spinners, prompts, aliases, or interactive selection.
- missing arguments fail instead of opening an interactive picker.
- elective / auto-elect / TTShiTu / Bark / thesis library commands are removed.

## Cache-first model

PkuClaw should call read-only commands as if they were live. `pku3b` checks its own
metadata/artifact cache first and reports provenance in `meta.cache`:

1. fresh typed metadata cache exists: return it immediately;
2. cache miss/expired or `--refresh`: attempt network refresh during this CLI run;
3. refresh succeeds: update cache and return new data;
4. refresh fails with old cache: return stale data with a warning;
5. refresh fails without old cache: return `ok=false`.

`--refresh` forces the command to skip the fresh-cache check for supported commands.
`pku3b` does not run a daemon and cannot refresh immediately when Blackboard changes.

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
    "generated_at": "2026-05-08T12:00:00+08:00",
    "cache": {
      "mode": "hit",
      "kind": "metadata",
      "ttl_seconds": 900,
      "expires_at": "2026-05-08T12:15:00+08:00",
      "key": "courses:list:current",
      "stale": false
    }
  }
}
```

For commands touching multiple cache entries, `meta.cache.mode` can be `mixed` with a
`summary`. Non-cached commands report `mode=disabled`, `kind=none`.

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
    "generated_at": "2026-05-08T12:00:00+08:00",
    "cache": {"mode": "disabled", "kind": "none", "stale": false}
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
pku3b cache clean --kind metadata
pku3b cache clean --kind artifact
pku3b cache clean --kind all
```

### Courses and courseware

```bash
pku3b courses list --term current|all
pku3b courses contents --id <course_id> [--root-content-id <content_id>]
pku3b courses grades --id <course_id>

pku3b courseware list --course-id <course_id>
pku3b courseware download --id <file_id> --out-dir <dir>
```

`courses contents` exposes the recursive Blackboard “教学内容” tree with stable item
IDs, item paths, folder child IDs, direct file URLs, attachments, and descriptions.
`courseware list` filters that tree into downloadable files; IDs returned by `list`
are accepted by `courseware download`.

### Explore

```bash
pku3b explore visit --url <relative-or-course-url>
pku3b explore visit --url <relative-or-course-url> --max-chars 20000 --max-links 200 --max-table-rows 100
```

`explore visit` is an authenticated, read-only Blackboard page exploration API for
PkuClaw fallback/extension work. It performs one GET request, follows safe
Blackboard redirects, caches the cleaned metadata for 5 minutes, and returns a
structured page summary: title, main text, headings, links, WebDAV attachments,
tables, forms, Blackboard query hints, final URL, and status.

It is deliberately constrained:

- target URL must be relative or `http(s)://course.pku.edu.cn/...`;
- redirects are revalidated against the same allowlist;
- known state-changing GET targets such as logout, delete/remove/submit/save, and
  assignment `newAttempt` URLs are rejected even on `course.pku.edu.cn`;
- no POST, no form submission, no recursive crawling, and no file download;
- `file:`, `data:`, `javascript:`, external, and fragment links may appear in
  parsed `links`, but are marked `visit_allowed=false` and are not valid visit
  targets;
- hidden/password/token-like form values are redacted.

Prefer typed commands (`assignments get`, `courses contents`, `courseware list`,
`courses grades`, etc.) whenever they exist. Use `explore visit` to inspect pages
that are not yet covered by a typed JSON contract, then promote repeated patterns
into typed commands.

### Assignments

```bash
pku3b assignments list --term current
pku3b assignments list --term all
pku3b assignments get --id <assignment_id> [--term current|all]
pku3b assignments download --id <assignment_id> --out-dir <dir> [--term current|all]
pku3b assignments download-submission --id <submitted_file_id> --out-dir <dir> [--term current|all]
pku3b assignments submit --id <assignment_id> --file <path>
```

`assignments list` includes `submission_summary` for submitted/unsubmitted state, latest attempt, score, file count, and feedback availability. `assignments get` returns full attempt history and submitted file IDs. Use `download-submission` for files returned under `submission.attempts[].files[]`; `assignments download` remains for teacher-provided assignment attachments.
```text
submitted file id: <course_id>:<content_id>:attempt:<attempt_id>:file:<file_id>
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


## Blackboard TLS compatibility

PKU Blackboard has sometimes served `course.pku.edu.cn` with a missing/mismatched
GlobalSign intermediate certificate. `pku3b` keeps certificate validation enabled,
but automatically creates an augmented CA bundle in its cache directory that adds
the required `GlobalSign GCC R6 AlphaSSL CA 2025` intermediate to the system CA
bundle before building the native TLS connector. No `danger_accept_invalid_certs`
mode is used. Set `PKU3B_DISABLE_TLS_CA_BUNDLE=1` only for debugging if you need
to disable this compatibility layer.

## Stable IDs

External IDs never use Rust `DefaultHasher`. When Blackboard exposes an ID, pku3b uses
it directly; otherwise it uses explicit fields and a documented fixed FNV-1a 64-bit
fingerprint. Examples:

- course: `<course_id>`
- content / assignment: `<course_id>:<content_id>`
- courseware attachment: `<course_id>:<content_id>:attachment:<rid-or-fingerprint>`
- assignment attempt: `<course_id>:<content_id>:attempt:<attempt_id>`
- submitted assignment file: `<course_id>:<content_id>:attempt:<attempt_id>:file:<file_id>`
- grade: `<course_id>:<item_id>`
- video: `<course_id>:video:<source-url-fingerprint>`

## Build and check

```bash
cargo build --manifest-path crates/pku3b/Cargo.toml
cargo test --manifest-path crates/pku3b/Cargo.toml
```
