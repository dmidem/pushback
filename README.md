# pushback

A lightweight SSH/rsync-based backup tool with multi-server support, collision-safe paths, time-based snapshots, and smart gitignore-style filtering.

**Simple by default** — just run `pushback .` in any folder to back it up.
**Powerful when needed** — read this README or run `pushback -h` for full options.

## Quick Start

```bash
# Install
pip install --user pushback

# Create config
pushback --init-config

# Edit config at ~/.config/pushback/config.toml
# Add your server details

# Backup current directory
pushback .

# Preview changes
pushback --dry-run --verbose .

# Daily snapshots
pushback --snapshot-mode daily ~/projects/app

# Multi-server backup
pushback --server primary,offsite ~/critical
```

*See [docs/recipes.md](docs/recipes.md) for more examples.*

## Table of Contents

- [Installation](#installation)
- [Features](#features)
- [How It Works](#how-it-works)
- [Configuration](#configuration)
- [Documentation](#documentation)
- [Development](#development)
- [Contributing & Releases](#contributing--releases)
- [Troubleshooting](#troubleshooting)
- [License](#license)

## Installation

### Requirements

- **Local:** Python 3.11+ (for Methods 1–2; see below), `ssh` (proper version is pre-installed on most systems), `rsync` (see below)
  - **macOS:** Install GNU rsync via `brew install rsync` (system `openrsync` has limited functionality)
  - **Windows:** Install rsync via `choco install rsync`, pacman/msys2, use WSL where proper GNU rsync is typically pre-installed,
    or use any alternative method. Ensure rsync is in your PATH.
  - **Linux:** Proper GNU rsync is typically pre-installed
- **Remote:** SSH server (`sshd`) with `rsync` and standard POSIX tools (`ls`, `xargs`, `basename`)

### Method 1: pip

On Linux/macOS:
```bash
pip install --user pushback
```

On Windows:
```powershell
py -m pip install --user pushback
```

If `pip` isn’t available:
```bash
# Ubuntu/Debian
sudo apt install python3-pip

# macOS
python3 -m ensurepip
```

### Method 2: Single-file executable

Run (shown on Linux, macOS and Windows are similar):
```bash
# Download latest pushback.pyz release
wget https://github.com/dmidem/pushback/releases/latest/download/pushback.pyz

# Install
chmod +x pushback.pyz
mkdir -p ~/.local/bin
mv pushback.pyz ~/.local/bin/pushback
```
*Ensure `~/.local/bin` is in your `PATH`*

### Method 3: Prebuilt executables (Linux, macOS, Windows)

Download the archive for your platform from the [Releases](https://github.com/dmidem/pushback/releases) page, extract it,
and place the `pushback` binary somewhere on your `PATH` (for example, `/usr/local/bin` or `~/.local/bin` on Unix,
`%LocalAppData%\Programs\pushback` on Windows). Each bundle includes the CLI and a `docs/` directory for offline reference.

## Features

- **Multi-server backups** — `--server work,offsite`
- **Collision-safe paths** — `<base>/<name>_<hash>[_<time>]`
- **Time-based snapshots** — `none|hourly|daily|weekly|monthly|yearly|custom`
- **Smart filtering** — gitignore-style patterns with re-includes
- **Profile auto-detection** — Python, Node.js, Rust projects recognized automatically
- **SSH multiplexing** — fewer password prompts
- **Single-file install** — just Python + rsync/ssh

### Why pushback vs raw rsync?

You *can* script rsync yourself, but you'll quickly rebuild:
- Collision handling for same-named projects
- Snapshot naming/rotation that stays consistent
- Gitignore-style pattern matching with re-include semantics
- Profile-based filtering (auto-detect Python/Node/Rust/etc. projects)

## How It Works

Backups live under your remote `base` directory:

```
<base>/<project>_<hash>          # no snapshots
<base>/<project>_<hash>_2025-01  # monthly snapshot
```

- `<hash>` = 8-char hash of absolute local path (prevents name collisions)
- Snapshots: same time period → update; new period → create new directory

## Configuration

Create config on first run:

```bash
pushback --init-config
```

This creates:
- `~/.config/pushback/config.toml` — server configuration
- `~/.config/pushback/profiles.toml` — ignore patterns

### Minimal config.toml

```toml
[options]
delete_remote = false
profiles_file = "~/.config/pushback/profiles.toml"
snapshot_mode = "none"

[[server]]
name = "main"
user = "your_user"
host = "backup.example.com"
port = 22
base = "~/pushback"
default = true
```

### Multiple servers

```toml
[[server]]
name = "work"
user = "me"
host = "work.example.com"
port = 22
base = "~/backups"
default = true

[[server]]
name = "offsite"
user = "me"
host = "offsite.example.com"
port = 2222
base = "~/archive"
default = false
```

Usage:
```bash
pushback .                          # all default servers
pushback --server offsite .         # specific server
pushback --server work,offsite .    # multiple servers
```

### Smart Filtering

pushback uses **profiles** that auto-detect project types and apply appropriate ignore patterns.
See the [configuration reference](docs/options.md#profiles-configuration) for full profile details.

**Example profiles.toml:**

```toml
[profile.safe_defaults]
always = true
notes = "Safe defaults - always active"
ignore = [
    ".git/",
    ".svn/",
    ".DS_Store",
]

[profile.python]
notes = "Python projects"
detect.any_of = ["*.py", "pyproject.toml"]
ignore = [
    "__pycache__/",
    "*.pyc",
    ".venv/",
    "venv/",
]

[profile.node]
notes = "Node.js projects"
detect.any_of = ["package.json"]
ignore = [
    "node_modules/",
]
```

**Per-project overrides** with `.backupignore`:

```bash
# Create .backupignore (gitignore syntax)
cat >> .backupignore << 'EOF'
# Exclude build artifacts
build/
dist/

# But keep specific files
!dist/important.txt
EOF
```

### Profile Auto-Detection

Pushback automatically detects your project type and applies appropriate ignore patterns.
See supported project types in `~/.config/pushback/profiles.toml` (you can modify it and add more types if needed).

**How it works:**

1. On first run, `~/.config/pushback/profiles.toml` is created with defaults
2. When backing up a folder, pushback checks for detection patterns
3. Matching profiles are automatically activated
4. You can override per-project with `.backupignore`

**Example auto-detection:**

```bash
# Python project
cd ~/projects/django-app
ls
# pyproject.toml  manage.py  app/  .venv/

pushback .
# ✓ Detected: python profile
# ✓ Ignoring: __pycache__/, *.pyc, .venv/, dist/, build/
```

## Documentation

- [Configuration Options](docs/options.md) — Full config reference
- [Usage Recipes](docs/recipes.md) — Common use cases

## Development

### Setup

```bash
git clone https://github.com/dmidem/pushback.git
cd pushback
uv sync
```

Then use `uv` commands directly or the `dev.py` convenience script:

```
# Option 1: Run tools directly via uv
uv run ruff format src/ tests/
uv run ruff check src/ tests/
uv run mypy src/ tests/
uv run pytest
uv build

# Option 2: Use dev.py (recommended for common workflows)
python dev.py check   # Lint + typecheck + test
python dev.py fix     # Format + auto-fix
python dev.py build   # Build distributions
python dev.py clean   # Remove artifacts
```

### Project Structure

```
pushback/
├── src/pushback/        # Main package
│   ├── cli.py          # CLI entry point
│   ├── config.py       # Configuration handling
│   ├── sync.py         # Rsync operations
│   ├── remote.py       # SSH/remote operations
│   ├── filter.py       # Filter profile handling
│   └── _embedded/      # Embedded configs
│       ├── config.toml
│       └── profiles.toml
├── tests/              # Test suite
└── dev.py              # Development tasks
```

### CI/CD Workflow

pushback uses GitHub Actions for automated testing and releases (see `.github/workflows/ci.yml` and `.github/workflows/release.yml`).

**Continuous Integration (`ci.yml`):**
- Runs on every push and pull request
- Performs linting, type checking, and formatting validation with `ruff`
- Runs test suite with `pytest`
- Verifies builds complete successfully

**Automated Releases (`release.yml`):**
- Triggered when a version tag (e.g., `v0.2.0`) is pushed to the `main` branch
- Runs the same CI checks to ensure quality
- Builds wheel, source distribution, and zipapp
- Creates a GitHub release with all artifacts attached

**Note:** Only tags pushed to `main` trigger releases. Tags on other branches are ignored.

**To create a release:**

```bash
# 1. Update version (e.g., 0.2.0) in pyproject.toml and commit
git add pyproject.toml
git commit -m "Bump version to 0.2.0"

# 2. Create and push tag
git tag v0.2.0
git push origin main
git push origin v0.2.0
```

## License

Dual-licensed under:
- [Apache License 2.0](LICENSE-APACHE)
- [MIT License](LICENSE-MIT)

Choose either license for your use.

Copyright © 2025 Dmitry Demin
