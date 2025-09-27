# PushBack

A lightweight SSH/rsync-based folder backup tool with multi-server support, collision-safe paths, time-based snapshots, smart ignore patterns, and more.
Simple by default — just run `pushback .` in any folder to back it up. Powerful when you need more — read this `README` or run `pushback -h`
for full options.

## Quick Start

```bash
# 1) Create config (then edit ~/.config/pushback/config.ini)
pushback --init-config

# 2) Use it
pushback .                                        # backup current dir
pushback --snapshot-mode daily ~/projects/app     # daily snapshots
pushback --server primary,offsite ~/critical      # multi-server
pushback --dry-run --verbose .                    # preview + details
pushback --list-servers                           # see configured remotes
pushback --list-remote                            # list existing backups
pushback --stats --rsync-extra "--bwlimit=1000" . # stats + extra rsync flags
```

*Want more scenarios? See [docs/recipes.md](docs/recipes.md). For flags, run `pushback -h`.*

## On this page

- [Installation](#installation) — two copy-paste options
- [Features](#features) — the good bits, quickly
- [How it works](#how-it-works) — path format & snapshots
- [Configuration](#configuration) — tiny sample, link to full doc
- [Troubleshooting](#troubleshooting) — fast fixes

## Installation

**Platforms & OS Support**
- **Linux (Ubuntu)** — developed & tested on Ubuntu; other distros should work with `python3`/`ssh`/`rsync` installed.
- **macOS** — expected to work (same toolchain); default shell/RC paths may differ (e.g., zsh and `~/.zshrc`).
- **Windows** — expected to work; supported via `py pushback.py` / `python pushback.py`, a small `.bat` wrapper, or WSL for Unix‑style `./pushback`.

**Requirements**: `python3`, `ssh`, `rsync` on your machine; standard POSIX tools on the remote.

**User‑local installation (recommended)**
```bash
curl -fsSL https://raw.githubusercontent.com/dmidem/pushback/main/pushback.py \
  -o ~/.local/bin/pushback && chmod +x ~/.local/bin/pushback
```
If `~/.local/bin` isn’t on your `PATH`, add it:
```bash
[[ ":$PATH:" == *":$HOME/.local/bin:"* ]] || {
  echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
  export PATH="$HOME/.local/bin:$PATH"
  hash -r
}
```

**System‑wide installation (optional)**
```bash
sudo curl -fsSL https://raw.githubusercontent.com/dmidem/pushback/main/pushback.py \
  -o /usr/local/bin/pushback && sudo chmod +x /usr/local/bin/pushback
```

## Features
- **Multi‑server backups** — `--server work,offsite`.
- **Collision‑safe paths** — `<base>/<name>_<hash>[_<time>]`.
- **Time‑based snapshots** — `none|hourly|daily|weekly|monthly|yearly|custom`.
- **Smart ignores** — git‑style re‑includes via `.backupignore`.
- **Large‑file triage** — avoid unexpected big transfers.
- **SSH multiplexing** — fewer password prompts.
- **Single‑file install** — just Python + `rsync`/`ssh`.

### Why PushBack (vs. raw rsync?)
You *can* script rsync, but you’ll quickly rebuild:
- Collision handling across same‑named projects
- Snapshot naming/rotation that stays consistent
- Ignore + re‑include semantics (including parent‑dir includes)

## How it works
Backups live under your remote (destination) `base`:
```
<base>/<project>_<hash>          # no snapshots
<base>/<project>_<hash>_2025-01  # snapshot (optional): monthly, for example
```
- `<hash>` = short hash of absolute local (source) path (prevents clashes)
- If snapshots enabled: same time period → update; new period → new snapshot

## Configuration
Create once:
```ini
[remote]
user = you
host = host.example
port = 22
base = ~/backups
default = true

[options]
snapshot_mode = none
large_file_mb = 200
```
For full configuration schema and CLI options, see [`docs/options.md`](docs/options.md).

## Troubleshooting
- **“Remote base does not exist”** → create it (e.g., `ssh user@host "mkdir -p ~/backups"`)
- **“rsync not found”** → install via package manager (`apt`, `brew`, etc.)
- **Permission denied** → verify SSH and remote path permissions

## Copyright & License

Copyright (c) 2025 Dmitry Demin

This project is **dual-licensed** under:
- [Apache License, Version 2.0](LICENSE-APACHE)
- [MIT License](LICENSE-MIT)

You may choose either license for your use.

