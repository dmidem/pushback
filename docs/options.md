# Configuration Reference

Complete reference for pushback configuration files and options.

---

## Quick Start

**Create default configuration:**
```bash
pushback --init-config
```

**Configuration files:**
- Main config: `~/.config/pushback/config.toml`
- Profiles: `~/.config/pushback/profiles.toml`

---

## Configuration File Structure

### Minimal Example

```toml
[options]
delete_remote = false
profiles_file = "~/.config/pushback/profiles.toml"
snapshot_mode = "none"
snapshot_custom_hours = 24
include_backupignore = true
include_gitignore = false
autodetect_profiles = true

[[server]]
name = "main"
user = "your_user"
host = "backup.example.com"
port = 22
base = "~/pushback"
default = true
```

### Complete Example

```toml
[options]
delete_remote = false
profiles_file = "~/.config/pushback/profiles.toml"
snapshot_mode = "daily"
snapshot_custom_hours = 24
include_backupignore = true
include_gitignore = false
autodetect_profiles = true

[[server]]
name = "primary"
user = "backup_user"
host = "backup1.example.com"
port = 22
base = "~/backups"
default = true

[[server]]
name = "offsite"
user = "offsite_user"
host = "backup2.example.com"
port = 2222
base = "~/archive"
default = false
```

---

## Options Reference

### Global Options (`[options]` section)

#### `delete_remote`
- **Type:** boolean
- **Default:** `false`
- **CLI override:** `--delete` or `--no-delete`

When `true`, deletes remote files not present locally (rsync's `--delete`).

⚠️ **Warning:** Always test with `--dry-run` first!

**Example:**
```toml
delete_remote = false  # Safe default
```

#### `profiles_file`
- **Type:** path
- **Default:** `"~/.config/pushback/profiles.toml"`

Path to profiles configuration file. Supports `~` expansion.

**Example:**
```toml
profiles_file = "~/my-profiles.toml"
```

#### `snapshot_mode`
- **Type:** string
- **Default:** `"none"`
- **Values:** `none`, `hourly`, `daily`, `weekly`, `monthly`, `yearly`, `custom`
- **CLI override:** `--snapshot-mode MODE`

Controls time-based snapshot directories:

| Mode      | Directory Suffix | Description                    | Example              |
|-----------|------------------|--------------------------------|----------------------|
| `none`    | `_hash`          | Single directory, update only  | `myproject_a1b2c3d4` |
| `hourly`  | `_YYYY-MM-DDHHH` | One snapshot per hour          | `myproject_2025-01-15H14` |
| `daily`   | `_YYYY-MM-DD`    | One snapshot per day           | `myproject_2025-01-15` |
| `weekly`  | `_YYYYWWW`       | One snapshot per ISO week      | `myproject_2025W03`  |
| `monthly` | `_YYYY-MM`       | One snapshot per month         | `myproject_2025-01`  |
| `yearly`  | `_YYYY`          | One snapshot per year          | `myproject_2025`     |
| `custom`  | `_Innnnn`        | Custom interval buckets        | `myproject_I12345`   |

**Behavior:**
- Same time bucket → updates existing directory
- New time bucket → creates new directory

**Example:**
```toml
snapshot_mode = "daily"
```

#### `snapshot_custom_hours`
- **Type:** integer
- **Default:** `24`
- **CLI override:** `--snapshot-custom-hours N`

Hours per snapshot bucket when using `snapshot_mode = "custom"`.

**Example:**
```toml
snapshot_mode = "custom"
snapshot_custom_hours = 6  # 6-hour intervals
```

#### `include_backupignore`
- **Type:** boolean
- **Default:** `true`
- **CLI override:** `--include-backupignore` or `--no-backupignore`

Include `.backupignore` file from project root (gitignore syntax).

**Example:**
```toml
include_backupignore = true
```

#### `include_gitignore`
- **Type:** boolean
- **Default:** `false`
- **CLI override:** `--include-gitignore` or `--no-gitignore`

Include `.gitignore` file from project root.

**Example:**
```toml
include_gitignore = true  # Use .gitignore instead of .backupignore
```

#### `autodetect_profiles`
- **Type:** boolean
- **Default:** `true`
- **CLI override:** `--autodetect-profiles` or `--no-autodetect`

Auto-detect project type and activate matching profiles.

**Example:**
```toml
autodetect_profiles = false  # Disable auto-detection
```

---

### Server Configuration (`[[server]]` sections)

Each `[[server]]` block defines one backup destination.

#### `name` (required)
- **Type:** string

Unique identifier for this server.

**Example:**
```toml
name = "primary"
```

#### `user` (required)
- **Type:** string

SSH username.

**Example:**
```toml
user = "backup_user"
```

#### `host` (required)
- **Type:** string

SSH hostname or IP address.

**Example:**
```toml
host = "backup.example.com"
```

#### `port`
- **Type:** integer
- **Default:** `22`

SSH port number.

**Example:**
```toml
port = 2222
```

#### `base` (required)
- **Type:** string

Remote base directory. Must exist before first backup.

**Example:**
```toml
base = "~/backups"
```

#### `default`
- **Type:** boolean
- **Default:** `false`

When `true`, this server is used when no `--server` flag is specified.

⚠️ **At least one server must have `default = true`.**

**Example:**
```toml
default = true
```

---

## Server Selection

**Use all default servers:**
```bash
pushback .
```

**Use specific server:**
```bash
pushback --server offsite .
```

**Use multiple servers:**
```bash
pushback --server primary,offsite .
```

**List configured servers:**
```bash
pushback --list-servers
```

---

## Profiles Configuration

File: `~/.config/pushback/profiles.toml`

Defines reusable filter profiles that can be auto-detected or always applied.

### Profile Structure

```toml
[profile.name]
always = false          # Optional: always activate
notes = "Description"   # Optional: human-readable notes

# Optional: activation conditions
[profile.name.detect]
any_of = ["pattern1", "pattern2"]  # Match any
all_of = ["pattern1", "pattern2"]  # Match all

# Optional: exclusion patterns
[profile.name]
ignore = [
    "pattern1",
    "pattern2",
]
```

### Example Profiles

```toml
[profile.safe_defaults]
always = true
notes = "Safe defaults - always active"
ignore = [
    ".git/",
    ".svn/",
    ".DS_Store",
    "Thumbs.db",
    ".idea/",
    ".vscode/",
]

[profile.python]
notes = "Python projects"
detect.any_of = ["*.py", "pyproject.toml", "requirements.txt", "setup.py"]
ignore = [
    "__pycache__/",
    "*.pyc",
    "*.pyo",
    ".pytest_cache/",
    ".venv/",
    "venv/",
    "*.egg-info/",
    "dist/",
    "build/",
    ".mypy_cache/",
    ".ruff_cache/",
]

[profile.node]
notes = "Node.js/JavaScript projects"
detect.any_of = ["package.json", "yarn.lock", "pnpm-lock.yaml"]
ignore = [
    "node_modules/",
    ".npm/",
    ".yarn/",
    "dist/",
    "build/",
]

[profile.rust]
notes = "Rust projects"
detect.any_of = ["Cargo.toml", "Cargo.lock"]
ignore = [
    "target/",
    "Cargo.lock",  # Usually regenerated
]

[profile.go]
notes = "Go projects"
detect.any_of = ["go.mod", "go.sum"]
ignore = [
    "vendor/",
]

[profile.build_artifacts]
notes = "Common build outputs"
always = true
ignore = [
    "*.o",
    "*.a",
    "*.so",
    "*.dll",
    "*.exe",
    "*.out",
]
```

### Profile Fields Reference

#### `always`
- **Type:** boolean
- **Default:** `false`

If `true`, profile is always active regardless of detection.

#### `notes`
- **Type:** string
- **Optional**

Human-readable description. Shown in verbose output.

#### `detect.any_of`
- **Type:** array of glob patterns
- **Optional**

Profile activates if **any** pattern matches a file in project root.

**Example:**
```toml
detect.any_of = ["*.py", "pyproject.toml"]
```

#### `detect.all_of`
- **Type:** array of glob patterns
- **Optional**

Profile activates only if **all** patterns match files in project root.

**Example:**
```toml
detect.all_of = ["Cargo.toml", "Cargo.lock"]
```

#### `ignore`
- **Type:** array of gitignore-style patterns
- **Optional**

Files/directories to exclude. Uses gitignore syntax.

**Pattern syntax:**
```toml
ignore = [
    "logs/",           # Directory (trailing slash)
    "*.log",           # All .log files
    "/build/",         # Only at root
    "!important.log",  # Exception (re-include)
]
```

---

## Per-Project Overrides

Create `.backupignore` in project root (gitignore syntax):

```gitignore
# Exclude
build/
*.tmp
*.log

# Re-include
!important.log
!build/README.txt
```

**Filter precedence (highest to lowest):**
1. CLI flags (`--include-*`, `--no-*`)
2. `.backupignore` in project root
3. `.gitignore` in project root (if enabled)
4. Active profiles from `profiles.toml`

---

## Command-Line Reference

### Basic Syntax

```bash
pushback [OPTIONS] [PROJECT_PATH]
```

### Common Options

| Option | Description |
|--------|-------------|
| `--dry-run` | Preview changes without writing |
| `--verbose` | Detailed output |
| `--stats` | Show rsync statistics |
| `-d, --delete` | Delete remote files not present locally |
| `--no-delete` | Disable deletion (override config) |
| `--max-size SIZE` | Skip files larger than SIZE (e.g., `500M`, `2G`) |
| `--min-size SIZE` | Skip files smaller than SIZE (e.g., `1K`) |
| `--server NAME` | Use specific server(s), comma-separated |
| `--list-servers` | List configured servers |
| `--list-remote [NAME]` | List remote backups |
| `--snapshot-mode MODE` | Override snapshot mode |
| `--config PATH` | Use alternate config file |
| `--init-config` | Create default config files |

### Filter Options

| Option | Description |
|--------|-------------|
| `--include-backupignore` | Include `.backupignore` (override config) |
| `--no-backupignore` | Exclude `.backupignore` |
| `--include-gitignore` | Include `.gitignore` (override config) |
| `--no-gitignore` | Exclude `.gitignore` |
| `--autodetect-profiles` | Enable profile auto-detection (override config) |
| `--no-autodetect` | Disable profile auto-detection |

### Force Options

| Option | Description |
|--------|-------------|
| `--force-all` | Enable all force behaviors (non-interactive) |
| `--force-collision-new` | Auto-create new on name collision |
| `--force-collision-update` | Auto-update existing on collision |
