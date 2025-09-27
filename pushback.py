#!/usr/bin/env python3

"""
pushback — SSH/rsync-based backup tool.

Copyright (c) 2025 Dmitry Demin, https://github.com/dmidem
Licensed under Apache-2.0 OR MIT
"""

import argparse
import configparser
import hashlib
import os
import shlex
import subprocess
import sys
import tempfile
from datetime import datetime
from fnmatch import fnmatch
from pathlib import Path
from shutil import which

PROG_NAME = "pushback"

DEFAULTS = {
    "REMOTE_USER": "your_user",
    "REMOTE_HOST": "your.host.example",
    "REMOTE_PORT": "22",
    "REMOTE_BASE": "~/pushback",
    "LARGE_FILE_MB": "200",
    "DELETE_REMOTE": "0",
    "GLOBAL_IGNORE": "~/.config/pushback/global-ignore.txt",
    "SNAPSHOT_MODE": "none",  # none, yearly, monthly, weekly, daily, hourly, custom
    "SNAPSHOT_CUSTOM_HOURS": "24",  # For custom mode
}

DEFAULT_CONFIG_PATH = (
    Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / PROG_NAME / "config.ini"
)

CONFIG_TEMPLATE = f"""\
[remote]
user = {DEFAULTS["REMOTE_USER"]}
host = {DEFAULTS["REMOTE_HOST"]}
port = {DEFAULTS["REMOTE_PORT"]}
base = {DEFAULTS["REMOTE_BASE"]}
default = true

# Example of additional remote servers:
# [remote.backup]
# user = backup_user
# host = backup.example.com
# port = 22
# base = ~/backups
# default = false
#
# [remote.offsite]
# user = offsite_user
# host = offsite.example.com
# port = 2222
# base = ~/pushback
# default = true

[options]
large_file_mb = {DEFAULTS["LARGE_FILE_MB"]}
delete_remote = {DEFAULTS["DELETE_REMOTE"]}
global_ignore = {DEFAULTS["GLOBAL_IGNORE"]}

# Time-based snapshots (optional)
# none=single backup dir, yearly/monthly/weekly/daily/hourly=time intervals, custom=use snapshot_custom_hours
snapshot_mode = {DEFAULTS["SNAPSHOT_MODE"]}
# For custom mode: create new snapshot every N hours
snapshot_custom_hours = {DEFAULTS["SNAPSHOT_CUSTOM_HOURS"]}
"""

HELP_EPILOG = f"""
REQUIREMENTS
  Local:  rsync, ssh  (install via your distro package manager)
  Remote: standard POSIX tools (ls, xargs, basename)

CONFIG
  Default path: {DEFAULT_CONFIG_PATH}
  Create one:   {PROG_NAME} --init-config
  Format: see the generated file

MULTIPLE REMOTE SERVERS
  Configure multiple servers in config.ini:
    [remote]           # Main server
    [remote.backup]    # Named server
    [remote.offsite]   # Another named server
    
  Each remote section can have "default = true" (multiple defaults allowed).
  
  Usage:
  • pushback .                    # Uses all default servers
  • pushback --server backup .    # Uses only 'backup' server  
  • pushback --server backup,offsite .  # Uses multiple specific servers
  • pushback --list-servers       # Show configured servers

TIME SNAPSHOTS
  • none: Single backup directory (default behavior)
  • yearly: New backup per year (2025, 2026, ...)  
  • monthly: New backup per month (2025-01, 2025-02, ...)
  • weekly: New backup per week (2025W01, 2025W02, ...)
  • daily: New backup per day (2025-01-15, 2025-01-16, ...)
  • hourly: New backup per hour (2025-01-15H14, 2025-01-15H15, ...)
  • custom: New backup every N hours, aligned to fixed boundaries
    Example: 6-hour intervals create buckets at 00:00, 06:00, 12:00, 18:00 UTC
    All backups within the same N-hour window update the same directory

  Example with daily snapshots:
    myproject_a1b2c3d4_2025-01-15/  (today's backup)
    myproject_a1b2c3d4_2025-01-14/  (yesterday's backup)

COMMON USE CASES
  • Simple backup of the current folder:
    pushback .

  • Daily project backup:
    pushback --force-all ~/projects/myapp
    
  • Development backup with dry-run preview:
    pushback --dry-run --verbose .
    
  • Selective backup excluding build artifacts:
    echo "build/" >> .backupignore && pushback .
    
  • Multiple projects batch backup:
    for dir in ~/projects/*/; do pushback --force-all "$dir"; done
 
  • Weekly snapshots with auto-cleanup of large files:
    pushback --snapshot-mode weekly ~/projects/webapp
       
  • Monthly archive with large file review:
    pushback --snapshot-mode monthly --verbose ~/important-project
  
  • Backup to specific server:
    pushback --server backup ~/important-docs
    
  • Backup to multiple servers:
    pushback --server primary,offsite --force-all ~/critical-project

IGNORE & PATTERN RULES
  Merge order (last wins on conflicts):
    1) built-in excludes (safe defaults: node_modules, target, __pycache__, etc.)
    2) global ignore file: ~/.config/pushback/global-ignore.txt
    3) per-project: .backupignore (in project root)
    4) auto-ignores from the large-file prompt (optional)

  .backupignore supports:
    • Exclude patterns (rsync-style), e.g. "foo", "/bar", "bar/", "*.log"
    • Re-include with "!" (gitignore style), e.g. "!/bar/keep.txt"

LARGE FILE SCAN
  • Files >= large_file_mb are listed before sync (keep all / ignore all / select).
  • You can append ignores to .backupignore (or use --force-backupignore / --force-all).

REMOTE PATH & COLLISIONS
  • Basic: <base>/<folder_name>_<hash(abs_path)>
  • With snapshots: <base>/<folder_name>_<hash>_<time_suffix>
  • If EXACT path exists -> update it (no prompt).
  • If same name but different suffix/time exists: collision handling applies

SSH CONNECTION
  • Multiplexing is enabled by default. Use --no-multiplex to disable.

OTHER OPTIONS
  • --dry-run          Preview changes
  • --stats            Show rsync stats summary
  • --rsync-extra "…"  Pass additional rsync flags
  • --list-remote [NAME]  List existing backups in <base>
  • --server NAME      Use specific server(s), comma-separated
  • --list-servers     Show configured servers
"""

DEFAULT_EXCLUDES = [
    "/.git/",
    "/.hg/",
    "/.svn/",
    "/.DS_Store",
    "/.idea/",
    "/.vscode/",
    "/.cache/",
    "/.mypy_cache/",
    "/.pytest_cache/",
    "/__pycache__/",
    "/*.pyc",
    "/.tox/",
    "/.venv/",
    "/venv/",
    "/env/",
    "/.poetry/",
    "/.poetry-cache/",
    "/*.egg-info/",
    "/dist/",
    "/build/",
    "/coverage/",
    "/node_modules/",
    "/.pnpm-store/",
    "/.yarn/*",
    "/.eslintcache",
    "/.turbo/",
    "/.next/",
    "/.vercel/",
    "/.out/",
    "/target/",
    "/Cargo.lock",
    "/*.log",
]


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def short_fingerprint(text: str, n: int = 8) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:n]


def check_bins():
    for binary in ["rsync", "ssh"]:
        if which(binary) is None:
            eprint(f"Error: required binary not found: {binary}")
            sys.exit(2)


def load_ignore_file(path: Path) -> list[str]:
    if not path.exists():
        return []

    patterns = []
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
        for line in content.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                patterns.append(stripped)
    except OSError as e:
        eprint(f"Warning: could not read {path}: {e}")

    return patterns


def load_backupignore_split(root: Path) -> tuple[list[str], list[str]]:
    """Returns (exclude_patterns, include_patterns) from .backupignore"""
    path = root / ".backupignore"
    excludes = []
    includes = []

    if not path.exists():
        return excludes, includes

    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("!"):
                pattern = stripped[1:].strip()
                if pattern:
                    includes.append(pattern)
            else:
                excludes.append(stripped)
    except OSError as e:
        eprint(f"Warning: could not read {path}: {e}")

    return excludes, includes


def matches_any(patterns: list[str], relpath: str) -> bool:
    norm = relpath.replace(os.sep, "/")
    for pat in patterns:
        pat_norm = pat.replace(os.sep, "/")
        if fnmatch(norm, pat_norm) or fnmatch("/" + norm, pat_norm):
            return True
    return False


def iter_large_files(
    root: Path, min_bytes: int, exclude_patterns: list[str], include_patterns: list[str]
):
    """Walks tree, honoring excludes first, then re-includes"""

    def is_included(rel: str) -> bool:
        rel_norm = rel.replace(os.sep, "/")
        for pat in include_patterns:
            pn = pat.replace(os.sep, "/")
            if fnmatch(rel_norm, pn) or fnmatch("/" + rel_norm, pn):
                return True
        return False

    for dirpath, dirnames, filenames in os.walk(root, topdown=True):
        rel_dir = os.path.relpath(dirpath, root)
        if rel_dir == ".":
            rel_dir = ""

        # Prune excluded dirs unless re-included
        for dirname in list(dirnames):
            rel = (os.path.join(rel_dir, dirname) if rel_dir else dirname) + "/"
            if matches_any(exclude_patterns, rel) and not is_included(rel.rstrip("/")):
                dirnames.remove(dirname)

        for filename in filenames:
            rel = os.path.join(rel_dir, filename) if rel_dir else filename
            if matches_any(exclude_patterns, rel) and not is_included(rel):
                continue

            full_path = os.path.join(dirpath, filename)
            try:
                size = os.path.getsize(full_path)
            except OSError:
                continue

            if size >= min_bytes:
                yield rel, full_path, size


def sizeof_fmt(num: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    size = float(num)
    for unit in units:
        if size < 1024.0 or unit == units[-1]:
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} {unit}"
        size /= 1024.0
    return f"{size:.1f} {units[-1]}"


def prompt_yes_no(msg: str, default=False) -> bool:
    default_str = "Y/n" if default else "y/N"
    answer = input(f"{msg} [{default_str}]: ").strip().lower()
    if not answer:
        return default
    return answer in ("y", "yes")


def load_remotes_from_config(path: Path) -> dict[str, dict]:
    """Load all remote server configurations from config file"""
    remotes = {}
    if not path.exists():
        return remotes

    parser = configparser.ConfigParser()
    try:
        parser.read(path)
    except configparser.Error as e:
        eprint(f"Error reading config file {path}: {e}")
        return remotes

    # Load main [remote] section
    if parser.has_section("remote"):
        sec = parser["remote"]
        remote_cfg = {}
        for key in ["user", "host", "port", "base"]:
            if key in sec:
                remote_cfg[f"REMOTE_{key.upper()}"] = sec[key]
        # Check for default flag
        remote_cfg["DEFAULT"] = sec.get("default", "true").lower() in ("1", "true", "yes", "on")
        remotes["main"] = remote_cfg

    # Load named [remote.NAME] sections
    for section_name in parser.sections():
        if section_name.startswith("remote."):
            server_name = section_name[7:]  # Remove "remote." prefix
            sec = parser[section_name]
            remote_cfg = {}
            for key in ["user", "host", "port", "base"]:
                if key in sec:
                    remote_cfg[f"REMOTE_{key.upper()}"] = sec[key]
            # Check for default flag
            remote_cfg["DEFAULT"] = sec.get("default", "false").lower() in (
                "1",
                "true",
                "yes",
                "on",
            )
            remotes[server_name] = remote_cfg

    return remotes


def load_config_file(path: Path) -> dict:
    """Load options section from config file"""
    cfg = {}
    if not path.exists():
        return cfg

    parser = configparser.ConfigParser()
    try:
        parser.read(path)
    except configparser.Error as e:
        eprint(f"Error reading config file {path}: {e}")
        return cfg

    if parser.has_section("options"):
        sec = parser["options"]
        option_map = {
            "large_file_mb": "LARGE_FILE_MB",
            "delete_remote": "DELETE_REMOTE",
            "global_ignore": "GLOBAL_IGNORE",
            "snapshot_mode": "SNAPSHOT_MODE",
            "snapshot_custom_hours": "SNAPSHOT_CUSTOM_HOURS",
        }
        for key, config_key in option_map.items():
            if key in sec:
                cfg[config_key] = sec[key]

    return cfg


def load_env() -> dict:
    envmap = {}
    env_keys = [
        "REMOTE_USER",
        "REMOTE_HOST",
        "REMOTE_PORT",
        "REMOTE_BASE",
        "LARGE_FILE_MB",
        "DELETE_REMOTE",
        "GLOBAL_IGNORE",
        "SNAPSHOT_MODE",
        "SNAPSHOT_CUSTOM_HOURS",
    ]
    for key in env_keys:
        value = os.environ.get("BK_" + key)
        if value is not None:
            envmap[key] = value
    return envmap


def split_remote_base(base: str) -> tuple[bool, str]:
    """Returns (is_tilde_path, rest_of_path)"""
    if base == "~":
        return True, ""
    if base.startswith("~/"):
        return True, base[2:]
    return False, base


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG_NAME,
        description="Backup/sync a project folder to remote server(s) using rsync over SSH.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=HELP_EPILOG,
    )

    # Configuration
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help=f"Path to config file (default: {DEFAULT_CONFIG_PATH})",
    )
    parser.add_argument(
        "--init-config", action="store_true", help="Create a template config + global-ignore.txt"
    )

    # Server selection
    parser.add_argument(
        "--server",
        type=str,
        help="Use specific server(s), comma-separated (default: use all default servers)",
    )
    parser.add_argument(
        "--list-servers", action="store_true", help="List configured servers and exit"
    )

    # Behavior
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    parser.add_argument(
        "--no-multiplex", action="store_true", help="Disable SSH ControlMaster/ControlPersist"
    )

    # Preview & stats
    parser.add_argument("--dry-run", action="store_true", help="Preview changes only")
    parser.add_argument("--stats", action="store_true", help="Show rsync stats summary")
    parser.add_argument("--rsync-extra", type=str, default="", help="Extra rsync flags")
    parser.add_argument(
        "--list-remote",
        nargs="?",
        const="",
        metavar="NAME",
        help="List remote backups; optional NAME filters by prefix",
    )

    # Force flags
    parser.add_argument("--force-all", action="store_true", help="Enable all force behaviors")
    parser.add_argument(
        "--force-collision-new",
        action="store_true",
        help="On name collision, auto-choose CREATE NEW",
    )
    parser.add_argument(
        "--force-collision-update",
        action="store_true",
        help="On name collision, auto-choose UPDATE EXISTING",
    )
    parser.add_argument(
        "--force-backupignore",
        action="store_true",
        help="Append large-file ignores to .backupignore without prompting",
    )

    # Snapshot options
    parser.add_argument(
        "--snapshot-mode",
        choices=["none", "yearly", "monthly", "weekly", "daily", "hourly", "custom"],
        help="Override config snapshot mode",
    )
    parser.add_argument(
        "--snapshot-custom-hours", type=int, help="Override custom snapshot interval (hours)"
    )

    parser.add_argument(
        "PROJECT_PATH", nargs="?", help="Folder to backup (use '.' for current directory)"
    )

    return parser


def ensure_config_and_global_ignore(cfg_path: Path, force_all: bool):
    # Write config.ini
    if cfg_path.exists() and not force_all:
        eprint(f"Refusing to overwrite existing config: {cfg_path}")
        eprint("(use --force-all to overwrite)")
        sys.exit(2)

    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        cfg_path.write_text(CONFIG_TEMPLATE, encoding="utf-8")
        print(f"Wrote template config to: {cfg_path}")
    except OSError as e:
        eprint(f"Error writing config file: {e}")
        sys.exit(2)

    # Write global-ignore.txt
    global_ignore_path = Path(os.path.expanduser(DEFAULTS["GLOBAL_IGNORE"]))
    if global_ignore_path.exists() and not force_all:
        print(f"Global ignore already exists: {global_ignore_path} (kept)")
    else:
        global_ignore_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            content = "\n".join(DEFAULT_EXCLUDES) + "\n"
            global_ignore_path.write_text(content, encoding="utf-8")
            print(f"Wrote global ignore to: {global_ignore_path}")
        except OSError as e:
            eprint(f"Warning: could not write global ignore file: {e}")


def ssh_base_opts(port: int, multiplex: bool) -> list:
    if not multiplex:
        return ["-p", str(port)]

    control_path = str(Path.home() / f".ssh/{PROG_NAME}-%r@%h-%p")
    return [
        "-p",
        str(port),
        "-o",
        "ControlMaster=auto",
        "-o",
        f"ControlPath={control_path}",
        "-o",
        "ControlPersist=60",
    ]


def ssh_run(
    user: str, host: str, port: int, script: str, multiplex: bool
) -> subprocess.CompletedProcess:
    cmd = ["ssh", *ssh_base_opts(port, multiplex), f"{user}@{host}", script]
    return subprocess.run(cmd, check=False, capture_output=True, text=True)


def _q(s: str) -> str:
    """Shell-quote strings for remote SSH commands"""
    return shlex.quote(s)


def ssh_test_dir(user: str, host: str, port: int, base: str, multiplex: bool) -> bool:
    is_tilde, rest = split_remote_base(base)
    if is_tilde:
        target = rest if rest else "."
        script = f"cd ~ && test -d {_q(target)} && echo OK || echo MISSING"
    else:
        script = f"test -d {_q(base)} && echo OK || echo MISSING"

    try:
        result = ssh_run(user, host, port, script, multiplex)
        return "OK" in (result.stdout or "")
    except Exception:
        return False


def ssh_list_siblings(
    user: str, host: str, port: int, base: str, prefix: str, multiplex: bool
) -> list[str]:
    is_tilde, rest = split_remote_base(base)
    if is_tilde:
        base_dir = (rest.rstrip("/") + "/") if rest else ""
        script = f"cd ~ && ls -1d {_q(base_dir + prefix + '_')}* 2>/dev/null | xargs -n1 basename 2>/dev/null || true"
    else:
        script = f"ls -1d {_q(base.rstrip('/') + '/' + prefix + '_')}* 2>/dev/null | xargs -n1 basename 2>/dev/null || true"

    try:
        result = ssh_run(user, host, port, script, multiplex)
        if result.returncode != 0 and not (result.stdout or "").strip():
            return []
        return [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
    except Exception:
        return []


def ssh_list_all(user: str, host: str, port: int, base: str, multiplex: bool) -> list[str]:
    is_tilde, rest = split_remote_base(base)
    if is_tilde:
        target = rest.rstrip("/") if rest else "."
        script = f"cd ~ && ls -1 {_q(target)} 2>/dev/null || true"
    else:
        script = f"ls -1 {_q(base.rstrip('/'))} 2>/dev/null || true"

    try:
        result = ssh_run(user, host, port, script, multiplex)
        if result.returncode != 0 and not (result.stdout or "").strip():
            return []
        return [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
    except Exception:
        return []


def do_list_servers(remotes: dict[str, dict]) -> int:
    """List configured servers"""
    if not remotes:
        print("No servers configured.")
        return 0

    print("Configured servers (pass with --server NAME):")
    for name, config in remotes.items():
        host = config.get("REMOTE_HOST", "?")
        user = config.get("REMOTE_USER", "?")
        port = config.get("REMOTE_PORT", "22")
        base = config.get("REMOTE_BASE", "?")
        is_default = config.get("DEFAULT", False)
        default_str = " (default)" if is_default else ""

        display_name = "main" if name == "main" else name
        print(f"  {display_name}: {user}@{host}:{port} -> {base}{default_str}")

    return 0


def do_list_remote(name_filter: str, server_name: str, server_config: dict, multiplex: bool) -> int:
    user = server_config["REMOTE_USER"]
    host = server_config["REMOTE_HOST"]
    base = server_config["REMOTE_BASE"]
    port = int(server_config["REMOTE_PORT"])

    if not ssh_test_dir(user, host, port, base, multiplex):
        eprint(f"Error: remote base does not exist on {server_name}: {base}")
        return 2

    if name_filter:
        items = ssh_list_siblings(user, host, port, base, name_filter, multiplex)
    else:
        items = ssh_list_all(user, host, port, base, multiplex)
        items = [x for x in items if "_" in x]

    if not items:
        print(f"(no backups found on {server_name})")
        return 0

    filter_text = f" (filtered by {name_filter})" if name_filter else ""
    print(f"Backups on {server_name} ({user}@{host}:{base}){filter_text}:")
    for item in sorted(items):
        print("  -", item)
    return 0


def parent_dirs_for(pattern: str) -> list[str]:
    """Generate parent directory paths for rsync traversal"""
    path = pattern.lstrip("/") if pattern.startswith("/") else pattern
    parts = [x for x in path.split("/") if x]
    parents = []
    current = ""

    for i in range(len(parts) - 1):  # up to parent of final component
        current = (current + "/" if current else "") + parts[i]
        parents.append(("/" + current) if pattern.startswith("/") else current)

    return [x + "/" for x in parents]  # explicitly directories


def handle_collision(existing: list[str], args) -> str:
    """Handle name collision for backup directories"""
    force_all = args.force_all
    force_new = force_all or args.force_collision_new
    force_update = force_all or args.force_collision_update

    if force_new and not force_update:
        return "create"
    if force_update and not force_new:
        return "update"
    if force_new and force_update:
        return "create"
    print("Found backup(s) with the same name but different suffix:")
    for item in existing:
        print(f"   - {item}")
    print("\nOptions:")
    print("  (u) Update an existing folder")
    print("  (c) Create a new folder and back up there")
    print("  (a) Abort")
    choice = input("Choose [u/c/a] [a]: ").strip().lower() or "a"

    if choice == "u":
        return "update"
    if choice == "c":
        return "create"
    print("Aborted. (Tip: use --force-collision-update or --force-collision-new)")
    return "abort"


def create_rsync_files(
    exclude_patterns: list[str], include_patterns: list[str]
) -> tuple[str | None, str]:
    """Create temporary include/exclude files for rsync"""
    include_path = None

    if include_patterns:
        # Add parent dirs for includes to allow traversal
        expanded_includes = []
        for pat in include_patterns:
            expanded_includes.extend(parent_dirs_for(pat))
            expanded_includes.append(pat)

        try:
            tf_inc = tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8")
            include_path = tf_inc.name
            for pat in expanded_includes:
                tf_inc.write(pat + "\n")
            tf_inc.close()
        except OSError as e:
            eprint(f"Error creating include file: {e}")
            sys.exit(2)

    try:
        tf_exc = tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8")
        exclude_path = tf_exc.name

        tf_exc.write("# Built-in excludes\n")
        for pat in DEFAULT_EXCLUDES:
            tf_exc.write(pat + "\n")

        remaining = [p for p in exclude_patterns if p not in DEFAULT_EXCLUDES]
        if remaining:
            tf_exc.write("\n# Additional excludes\n")
            for pat in remaining:
                tf_exc.write(pat + "\n")

        tf_exc.close()
    except OSError as e:
        eprint(f"Error creating exclude file: {e}")
        if include_path:
            try:
                os.unlink(include_path)
            except OSError:
                pass
        sys.exit(2)

    return include_path, exclude_path


def cleanup_temp_files(*paths):
    """Clean up temporary files"""
    for path in paths:
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass


def get_time_suffix(mode: str, custom_hours: int = 24) -> str:
    """Generate time suffix based on snapshot mode"""
    now = datetime.now()

    if mode == "none":
        return ""
    if mode == "yearly":
        return f"_{now.year}"
    if mode == "monthly":
        return f"_{now.year}-{now.month:02d}"
    if mode == "weekly":
        year, week, _ = now.isocalendar()
        return f"_{year}W{week:02d}"
    if mode == "daily":
        return f"_{now.year}-{now.month:02d}-{now.day:02d}"
    if mode == "hourly":
        return f"_{now.year}-{now.month:02d}-{now.day:02d}H{now.hour:02d}"
    if mode == "custom":
        # Round down to custom_hours intervals
        hours_since_epoch = int(now.timestamp()) // 3600
        interval_number = hours_since_epoch // custom_hours
        return f"_I{interval_number}"
    return ""


def find_existing_snapshot(siblings: list[str], base_name: str, time_suffix: str) -> str | None:
    """Find existing snapshot directory that matches the time suffix"""
    if not time_suffix:
        # No snapshots, look for exact match
        exact = f"{base_name}_"
        for sibling in siblings:
            if sibling.startswith(exact) and len(sibling) > len(exact):
                return sibling
        return None

    # Look for exact time suffix match
    target = f"{base_name}{time_suffix}"
    for sibling in siblings:
        if sibling.startswith(target):
            return sibling
    return None


def backup_to_server(
    server_name: str, server_config: dict, project_info: dict, args, options: dict
) -> int:
    """Backup to a single server"""
    root = project_info["root"]
    canonical_path = project_info["canonical_path"]
    folder_name = project_info["folder_name"]
    suffix = project_info["suffix"]
    time_suffix = project_info["time_suffix"]
    snapshot_mode = project_info["snapshot_mode"]

    # Apply environment overrides to server config
    env_cfg = load_env()
    server_config_merged = dict(server_config)
    for key in ["REMOTE_USER", "REMOTE_HOST", "REMOTE_PORT", "REMOTE_BASE"]:
        if key in env_cfg:
            server_config_merged[key] = env_cfg[key]

    # Then use server_config_merged instead of server_config:
    remote_user = server_config_merged.get("REMOTE_USER") or DEFAULTS["REMOTE_USER"]
    remote_host = server_config_merged.get("REMOTE_HOST") or DEFAULTS["REMOTE_HOST"]
    remote_port = int(server_config_merged.get("REMOTE_PORT") or DEFAULTS["REMOTE_PORT"])
    remote_base = server_config_merged.get("REMOTE_BASE") or DEFAULTS["REMOTE_BASE"]

    # Validate required settings (must be explicitly provided in config or env)
    if not server_config.get("REMOTE_USER") and "REMOTE_USER" not in env_cfg:
        eprint(
            f"Error: server '{server_name}' missing required 'user' (section [remote{'' if server_name == 'main' else '.' + server_name}])"
        )
        return 2
    if not server_config.get("REMOTE_HOST") and "REMOTE_HOST" not in env_cfg:
        eprint(
            f"Error: server '{server_name}' missing required 'host' (section [remote{'' if server_name == 'main' else '.' + server_name}])"
        )
        return 2

    try:
        remote_port = int(server_config_merged.get("REMOTE_PORT") or DEFAULTS["REMOTE_PORT"])
    except (ValueError, TypeError):
        eprint(f"Error: server '{server_name}' has invalid port setting")
        return 2

    multiplex = not args.no_multiplex

    base_remote_name = f"{folder_name}_{suffix}"
    exact_remote_dir = f"{remote_base.rstrip('/')}/{base_remote_name}{time_suffix}"

    if args.verbose:
        print(f"=== Server: {server_name} ===")
        print(f"Remote: {remote_user}@{remote_host}:{remote_port}")
        print(f"Base: {remote_base}")
        print(f"Target: {exact_remote_dir}")

    # Remote base must exist
    if not ssh_test_dir(remote_user, remote_host, remote_port, remote_base, multiplex):
        eprint(f"Error: remote base does not exist on {server_name}: {remote_base}")
        eprint("Create it manually and rerun.")
        eprint(
            f'Example: ssh -p {remote_port} {remote_user}@{remote_host} "mkdir -p {remote_base}"'
        )
        return 2

    # Determine target directory
    if ssh_test_dir(remote_user, remote_host, remote_port, exact_remote_dir, multiplex):
        # Exact match exists (including time suffix)
        target_remote_dir = exact_remote_dir
        if args.verbose:
            print(f"Found existing backup for this time period: {target_remote_dir}")
    else:
        # Check for existing snapshots in this time period
        all_siblings = ssh_list_all(remote_user, remote_host, remote_port, remote_base, multiplex)

        if snapshot_mode != "none":
            # Look for existing backup in current time period
            existing_snapshot = find_existing_snapshot(all_siblings, base_remote_name, time_suffix)
            if existing_snapshot:
                target_remote_dir = f"{remote_base.rstrip('/')}/{existing_snapshot}"
                if args.verbose:
                    print(f"Found existing snapshot for this time period: {target_remote_dir}")
            else:
                # No snapshot for this time period, create new one
                target_remote_dir = exact_remote_dir
                if args.verbose:
                    print(f"Creating new snapshot: {target_remote_dir}")
        else:
            # No snapshot mode - handle traditional collisions
            name_siblings = ssh_list_siblings(
                remote_user, remote_host, remote_port, remote_base, folder_name, multiplex
            )
            other_hash_dirs = [s for s in name_siblings if s != f"{folder_name}_{suffix}"]

            if other_hash_dirs:
                action = handle_collision(other_hash_dirs, args)
                if action == "abort":
                    return 1
                if action == "update":
                    chosen = other_hash_dirs[-1]
                    target_remote_dir = f"{remote_base.rstrip('/')}/{chosen}"
                    if args.verbose:
                        print(f"Collision -> updating: {target_remote_dir}")
                else:  # create
                    target_remote_dir = exact_remote_dir
                    if args.verbose:
                        print(f"Collision -> creating new: {target_remote_dir}")
            else:
                target_remote_dir = exact_remote_dir

    if args.verbose:
        print(f"Final target: {remote_user}@{remote_host}:{target_remote_dir}")

    # Build rsync command
    src = str(root) + "/"
    ssh_opts = " ".join(ssh_base_opts(remote_port, multiplex))
    rsync_cmd = [
        "rsync",
        "-azP",
        "--safe-links",
        "--prune-empty-dirs",
        "-e",
        f"ssh {ssh_opts}",
    ]

    if project_info["include_path"]:
        rsync_cmd.append(f"--include-from={project_info['include_path']}")
    rsync_cmd.append(f"--exclude-from={project_info['exclude_path']}")

    delete_remote = options.get("DELETE_REMOTE", False)
    if delete_remote:
        rsync_cmd.insert(2, "--delete")
    if args.dry_run:
        rsync_cmd.extend(["--dry-run", "--itemize-changes"])
    if args.stats:
        rsync_cmd.append("--stats")

    # Add extra rsync options
    if args.rsync_extra.strip():
        try:
            extra_tokens = [
                t for t in shlex.split(args.rsync_extra) if t != "-e" and not t.startswith("-e")
            ]
            rsync_cmd.extend(extra_tokens)
        except ValueError as e:
            eprint(f"Error parsing rsync-extra options: {e}")
            return 2

    rsync_cmd.extend([src, f"{remote_user}@{remote_host}:{target_remote_dir}/"])

    if args.verbose:
        print(f"Running rsync for {server_name}:")
        print(" ", " ".join(rsync_cmd))
        print(f"SSH multiplexing: {'enabled' if multiplex else 'disabled'}")

    # Execute rsync
    try:
        result = subprocess.run(rsync_cmd, check=False)
        return_code = result.returncode
    except KeyboardInterrupt:
        eprint(f"\nInterrupted by user during {server_name} backup")
        return_code = 130
    except Exception as e:
        eprint(f"Error running rsync for {server_name}: {e}")
        return_code = 1

    # Report results
    if return_code == 0:
        if args.dry_run:
            print(f"\nDry-run complete for {server_name} (no changes made).")
        else:
            print(f"\nBackup complete for {server_name}.")
            print(f"   {remote_user}@{remote_host}:{target_remote_dir}")
        return 0
    eprint(f"\nrsync failed for {server_name} with exit code {return_code}")
    return return_code


def main():
    parser = build_parser()
    if len(sys.argv) == 1:
        parser.print_help(sys.stderr)
        return 2

    args = parser.parse_args()

    # Handle --init-config
    cfg_path = Path(args.config) if args.config else DEFAULT_CONFIG_PATH
    if args.init_config:
        ensure_config_and_global_ignore(cfg_path, force_all=args.force_all)
        return 0

    # Config must exist for all modes except --init-config
    if not cfg_path.exists():
        eprint(f"Error: config file not found: {cfg_path}")
        eprint(f"Run `{PROG_NAME} --init-config` to create one.")
        return 2

    # Load remotes and options
    remotes = load_remotes_from_config(cfg_path)
    if not remotes:
        eprint("Error: no remote servers configured")
        return 2

    # Handle --list-servers
    if args.list_servers:
        return do_list_servers(remotes)

    # Load other config
    file_cfg = load_config_file(cfg_path)
    env_cfg = load_env()
    options = dict(DEFAULTS)
    options.update(file_cfg)
    options.update(env_cfg)

    # Validate numeric settings
    try:
        options["LARGE_FILE_MB"] = str(int(options["LARGE_FILE_MB"]))
    except (ValueError, KeyError):
        eprint("Error: LARGE_FILE_MB must be a valid integer")
        return 2

    # Parse boolean setting
    delete_remote_str = str(options.get("DELETE_REMOTE", "0")).strip().lower()
    options["DELETE_REMOTE"] = delete_remote_str in ("1", "true", "yes", "on")

    check_bins()
    multiplex = not args.no_multiplex

    # Determine which servers to use
    if args.server:
        # Use specific servers (comma-separated, tolerate spaces/empties)
        requested_servers = [s.strip() for s in args.server.split(",") if s.strip()]
        selected_servers = {}
        for server_name in requested_servers:
            if server_name in remotes:
                selected_servers[server_name] = remotes[server_name]
            else:
                eprint(f"Error: server '{server_name}' not found in config")
                return 2
    else:
        # Use default servers
        selected_servers = {
            name: config for name, config in remotes.items() if config.get("DEFAULT", False)
        }
        if not selected_servers:
            eprint("Error: no default servers configured (set 'default = true' in config)")
            return 2

    # Handle --list-remote
    if args.list_remote is not None:
        name_filter = args.list_remote or ""
        first_server = True
        overall_rc = 0
        for server_name, server_config in selected_servers.items():
            if len(selected_servers) > 1 and not first_server:
                print()
            first_server = False
            rc = do_list_remote(name_filter, server_name, server_config, multiplex)
            if rc != 0:
                overall_rc = rc
        return overall_rc

    # Sync mode requires PROJECT_PATH
    if not args.PROJECT_PATH:
        eprint("Error: PROJECT_PATH is required (use '.' for current dir).")
        parser.print_help(sys.stderr)
        return 2

    root = Path(args.PROJECT_PATH).expanduser()
    if not root.exists() or not root.is_dir():
        eprint(f"Error: PROJECT_PATH does not exist or is not a directory: {root}")
        return 2

    # Get canonical path and generate names
    try:
        canonical_path = str(root.resolve())
    except Exception:
        canonical_path = str(root.absolute())

    folder_name = Path(canonical_path).name or root.name or "folder"
    suffix = short_fingerprint(canonical_path, 8)

    snapshot_mode = args.snapshot_mode or options.get("SNAPSHOT_MODE", "none")
    snapshot_custom_hours = args.snapshot_custom_hours or int(
        options.get("SNAPSHOT_CUSTOM_HOURS", "24")
    )
    if snapshot_custom_hours <= 0:
        eprint("Error: snapshot_custom_hours must be a positive integer")
        return 2

    # Validate snapshot mode
    valid_modes = ["none", "yearly", "monthly", "weekly", "daily", "hourly", "custom"]
    if snapshot_mode not in valid_modes:
        eprint(
            f"Error: invalid snapshot_mode: {snapshot_mode}. Must be one of: {', '.join(valid_modes)}"
        )
        return 2

    time_suffix = get_time_suffix(snapshot_mode, snapshot_custom_hours)

    if args.verbose:
        print(f"Config file:    {cfg_path}")
        print(f"Project folder: {folder_name}")
        print(f"Local path:     {canonical_path}")
        print(f"Snapshot mode:  {snapshot_mode}")
        if snapshot_mode == "custom":
            print(f"Custom hours:   {snapshot_custom_hours}")
        print(f"Time suffix:    {time_suffix}")
        print(f"Selected servers: {', '.join(selected_servers.keys())}")
        print()

    # Load ignore patterns
    global_ignore_path = Path(os.path.expanduser(options["GLOBAL_IGNORE"]))
    if not global_ignore_path.exists():
        eprint(f"Warning: global ignore file not found: {global_ignore_path}")
    global_patterns = load_ignore_file(global_ignore_path)
    proj_excludes, proj_includes = load_backupignore_split(root)
    exclude_patterns = DEFAULT_EXCLUDES + global_patterns + proj_excludes
    include_patterns = proj_includes

    # Handle large files (once for all servers)
    large_file_mb = int(options["LARGE_FILE_MB"])
    min_bytes = large_file_mb * 1024 * 1024
    large_files = list(iter_large_files(root, min_bytes, exclude_patterns, include_patterns))
    auto_ignores = []

    if large_files:
        print(f"Found {len(large_files)} large file(s) (>= {large_file_mb} MB):")
        for i, (rel, _full, size) in enumerate(large_files, 1):
            print(f"  {i:>2}. {rel}  ({sizeof_fmt(size)})")
        print()

        if not args.force_all:
            choice = (
                input("Handle large files? (k=keep all / i=ignore all / s=select) [s]: ")
                .strip()
                .lower()
                or "s"
            )
            if choice == "i":
                auto_ignores = [f"/{rel}" for rel, *_ in large_files]
            elif choice == "s":
                for rel, _full, size in large_files:
                    if not prompt_yes_no(f"Keep {rel} ({sizeof_fmt(size)})?", default=False):
                        auto_ignores.append(f"/{rel}")

        if auto_ignores:
            should_append = (
                args.force_all
                or args.force_backupignore
                or prompt_yes_no(
                    "Append ignored ones to .backupignore for next time?", default=True
                )
            )
            if should_append:
                try:
                    with (root / ".backupignore").open("a", encoding="utf-8") as f:
                        f.write(f"\n# Added by {PROG_NAME} (large files)\n")
                        for pat in auto_ignores:
                            f.write(pat + "\n")
                    print(f"Updated {root / '.backupignore'}")
                except OSError as e:
                    eprint(f"Warning: could not update .backupignore: {e}")
            exclude_patterns.extend(auto_ignores)

    # Create rsync include/exclude files (once for all servers)
    include_path, exclude_path = create_rsync_files(exclude_patterns, include_patterns)

    # Prepare project info for servers
    project_info = {
        "root": root,
        "canonical_path": canonical_path,
        "folder_name": folder_name,
        "suffix": suffix,
        "time_suffix": time_suffix,
        "snapshot_mode": snapshot_mode,
        "include_path": include_path,
        "exclude_path": exclude_path,
    }

    # Backup to all selected servers
    overall_success = True
    successes, failures = [], []
    try:
        for server_name, server_config in selected_servers.items():
            if len(selected_servers) > 1 and args.verbose:
                print(f"\n{'=' * 50}")

            result = backup_to_server(server_name, server_config, project_info, args, options)
            if result == 0:
                successes.append(server_name)
            else:
                failures.append(server_name)
                overall_success = False
                if not args.force_all:
                    break
    finally:
        cleanup_temp_files(include_path, exclude_path)

    if overall_success:
        if len(selected_servers) > 1:
            print(
                f"\nAll backups completed successfully ({len(selected_servers)} servers): {', '.join(successes)}"
            )
        return 0
    if len(selected_servers) > 1:
        if successes:
            print(f"\nSucceeded: {', '.join(successes)}")
        if failures:
            eprint(f"Failed: {', '.join(failures)}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
