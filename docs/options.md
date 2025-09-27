# Configuration

Your config lives at `~/.config/pushback/config.ini` (created by `pushback --init-config`).

## Minimal example
```ini
[remote]
user = you
host = host.example
port = 22
base = ~/backups
default = true

[options]
snapshot_mode = none           # none|hourly|daily|weekly|monthly|yearly|custom
large_file_mb = 200            # prompt on files larger than this (MB)
delete_remote = 0              # 1 to delete remote files not present locally (caution)
global_ignore = ~/.config/pushback/global-ignore.txt
snapshot_custom_hours = 24     # used when snapshot_mode=custom
```

## Multiple remotes
Add sections named `[remote.NAME]`:
```ini
[remote.work]
user = me
host = work.example
port = 22
base = ~/backups
default = true

[remote.offsite]
user = me
host = offsite.example
port = 2222
base = ~/pushback
default = false
```
Usage:
```bash
pushback .                          # use all default=true remotes
pushback --server offsite .         # choose specific remote(s)
pushback --server work,offsite .    # multiple remotes
pushback --list-servers             # print configured remotes
```

## Snapshot modes
| Mode    | Suffix example      | Behavior                                      |
|---------|----------------------|-----------------------------------------------|
| none    | `project_hash`       | Single directory; repeated runs update it     |
| hourly  | `2025-01-15H14`      | One per hour                                  |
| daily   | `2025-01-15`         | One per day                                   |
| weekly  | `2025W03`            | ISO week number                               |
| monthly | `2025-01`            | One per month                                 |
| yearly  | `2025`               | One per year                                  |
| custom  | `I12345`             | Fixed N‑hour buckets (`snapshot_custom_hours`) |

- Same time bucket → update existing snapshot
- New bucket → create new directory

## Options reference
- `remote.*`
  - `user`, `host`, `port`, `base` (must exist), `default` (`true|false`).
- `[options]`
  - `snapshot_mode`: `none|hourly|daily|weekly|monthly|yearly|custom`.
  - `snapshot_custom_hours`: integer > 0; interval for `custom` mode (aligned buckets).
  - `large_file_mb`: integer ≥ 0; threshold for large-file review.
  - `delete_remote`: `0|1`; when 1, rsync deletes remote files not present locally (dangerous; prefer `--dry-run` first).
  - `global_ignore`: path to global ignore file.

## Global ignore defaults
`pushback --init-config` also creates `~/.config/pushback/global-ignore.txt` with safe defaults like:
```
.git/
.svn/
.hg/
__pycache__/
node_modules/
target/
dist/
build/
.idea/
.vscode/
.DS_Store
Thumbs.db
```
Extend as needed.

## Environment overrides
You can override config via environment variables:
```bash
export BK_REMOTE_USER=myuser
export BK_REMOTE_HOST=backup.example.com
export BK_REMOTE_PORT=2222
export BK_SNAPSHOT_MODE=daily
export BK_SNAPSHOT_CUSTOM_HOURS=6
```

## CLI reference
A concise description of all command‑line arguments.

**Synopsis**
```text
pushback [-h] [--config CONFIG] [--init-config] [--server SERVER] [--list-servers] [--verbose]
        [--no-multiplex] [--dry-run] [--stats] [--rsync-extra RSYNC_EXTRA]
        [--list-remote [NAME]] [--force-all] [--force-collision-new]
        [--force-collision-update] [--force-backupignore]
        [--snapshot-mode {none,yearly,monthly,weekly,daily,hourly,custom}]
        [--snapshot-custom-hours SNAPSHOT_CUSTOM_HOURS]
        [PROJECT_PATH]
```

**Positional**
- `PROJECT_PATH` — Folder to back up (use `.` for current directory).

**General**
- `-h, --help` — Show help and exit.
- `--verbose` — Verbose output.
- `--dry-run` — Preview changes only; no writes.
- `--stats` — Show rsync stats summary after the run.
- `--rsync-extra RSYNC_EXTRA` — Extra flags passed to rsync.

**Config**
- `--config CONFIG` — Path to config file (default: `~/.config/pushback/config.ini`).
- `--init-config` — Create a template config and `global-ignore.txt`.

**Remotes**
- `--server SERVER` — Use specific server(s), comma‑separated (default: all `default=true` servers).
- `--list-servers` — List configured servers and exit.
- `--list-remote [NAME]` — List remote backups; optional `NAME` filters by prefix.

**Forcing/automation**
- `--force-all` — Enable all force behaviors (non‑interactive).
- `--force-collision-new` — On name collision, auto‑choose **CREATE NEW**.
- `--force-collision-update` — On name collision, auto‑choose **UPDATE EXISTING**.
- `--force-backupignore` — Append large‑file ignores to `.backupignore` without prompting.

**Snapshots**
- `--snapshot-mode {none,yearly,monthly,weekly,daily,hourly,custom}` — Override snapshot mode.
- `--snapshot-custom-hours N` — For `custom` mode: create new snapshot every `N` hours.

**SSH**
- `--no-multiplex` — Disable SSH ControlMaster/ControlPersist for this run.
