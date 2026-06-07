"""
Command-line interface and main entry point.
Parses arguments, loads configuration, and runs sync operations.
"""

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

from . import APP_DESCRIPTION, APP_NAME, HOMEPAGE, VERSION
from .config import Config, ServerEntry, SyncParams, default_config_dir
from .remote import RemoteManager
from .sync import sync_to_server


def check_rsync() -> tuple[bool, str]:
    """Check if rsync is available and compatible.

    Returns:
        (is_compatible, message)
    """
    rsync_path = shutil.which("rsync")
    if not rsync_path:
        msg = "rsync not found in PATH.\nInstall instructions:\n"
        system = platform.system()
        if system == "Darwin":
            msg += "  macOS: brew install rsync"
        elif system == "Windows":
            msg += "  Windows: choco install rsync, pacman/msys2, or use WSL"
        elif system == "Linux":
            msg += "  Linux: Install rsync via your package manager"
        else:
            msg += f"  {system}: Install GNU rsync via your package manager"

        return False, msg

    try:
        result = subprocess.run(
            [rsync_path, "--version"], capture_output=True, text=True, timeout=5
        )
        version_line = result.stdout.split("\n")[0] if result.stdout else ""

        # Check for openrsync (limited functionality)
        if "openrsync" in result.stdout.lower():
            return False, (
                f"Incompatible rsync found: {version_line}\n"
                f"macOS ships with openrsync which has limited functionality.\n"
                f"Install GNU rsync: brew install rsync"
            )

        return True, f"rsync OK: {version_line}"

    except Exception as e:
        return False, f"Error checking rsync: {e}"


def check_ssh() -> tuple[bool, str]:
    """Check if SSH client is available.

    Returns:
        (is_available, message)
    """
    ssh_path = shutil.which("ssh")
    if not ssh_path:
        return False, "ssh not found in PATH (should be pre-installed on most systems)"

    try:
        result = subprocess.run([ssh_path, "-V"], capture_output=True, text=True, timeout=5)
        # SSH writes version to stderr
        version_info = (result.stderr or result.stdout).strip().split("\n")[0]
        return True, f"ssh OK: {version_info}"
    except Exception as e:
        return False, f"Error checking ssh: {e}"


def check_dependencies(verbose: bool = False) -> bool:
    """Check all dependencies and report status.

    Args:
        verbose: Show success messages, not just failures

    Returns:
        True if all dependencies are satisfied
    """
    checks = [
        ("rsync", check_rsync()),
        ("ssh", check_ssh()),
    ]

    all_ok = True
    messages: list[str] = []

    for name, (is_ok, message) in checks:
        if not is_ok:
            all_ok = False
            messages.append(f"✗ {name}: {message}")
        elif verbose:
            messages.append(f"✓ {message}")

    if messages:
        print("\n".join(messages))
        if not all_ok:
            print()

    return all_ok


DEFAULT_CONFIG_DIR = default_config_dir()

HELP_EPILOG = dedent(f"""
QUICK START
  1) Run: {APP_NAME} --init-config
  2) Edit {DEFAULT_CONFIG_DIR}/config.toml
  3) {APP_NAME} .              # sync the current directory
     {APP_NAME} /path/to/dir   # sync a specific directory

CONFIG PATHS
  Config:   {DEFAULT_CONFIG_DIR}/config.toml
  Profiles: {DEFAULT_CONFIG_DIR}/profiles.toml

REQUIREMENTS
  Local:  rsync, ssh
  Remote: standard POSIX tools (ls, xargs, basename)

MORE INFO
  See README & docs: {HOMEPAGE}
""").strip()


def build_parser() -> argparse.ArgumentParser:
    """Build argument parser"""
    parser = argparse.ArgumentParser(
        prog=APP_NAME,
        description=APP_DESCRIPTION,
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=HELP_EPILOG,
    )

    # Simple flags (keep as store_true — no need for --no-verbose etc.)
    parser.add_argument("--init-config", action="store_true", help="Create template config file")
    parser.add_argument("--list-servers", action="store_true", help="List configured servers")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    parser.add_argument("--version", action="store_true", help="Print version number and exit")

    # Plain options
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help=f"Path to config file (default: {DEFAULT_CONFIG_DIR}/config.toml)",
    )
    parser.add_argument("--server", type=str, help="Use specific server(s), comma-separated")
    parser.add_argument("--rsync-extra", type=str, default="", help="Extra rsync flags")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes only")
    parser.add_argument("--stats", action="store_true", help="Show rsync stats")
    parser.add_argument("--max-size", type=str, help="Skip files larger than SIZE (e.g., 100M, 2G)")
    parser.add_argument(
        "--min-size", type=str, help="Skip files smaller than SIZE (e.g., 1K, 100B)"
    )

    # BooleanOptionalAction (tri-state via default=None; CLI provides --foo/--no-foo)
    parser.add_argument(
        "-d",
        "--delete",
        dest="delete",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Delete remote files not present locally (use --no-delete to disable).",
    )
    parser.add_argument(
        "-b",
        "--include-backupignore",
        dest="include_backupignore",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Include .backupignore rules (use --no-include-backupignore to disable).",
    )
    parser.add_argument(
        "-g",
        "--include-gitignore",
        dest="include_gitignore",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Include .gitignore rules (use --no-include-gitignore to disable).",
    )
    parser.add_argument(
        "--autodetect-profiles",
        dest="autodetect_profiles",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Auto-detect project type (use --no-autodetect-profiles to disable).",
    )
    parser.add_argument(
        "--ssh-multiplex",
        dest="ssh_multiplex",
        type=int,
        metavar="SECONDS",
        default=None,
        help=(
            "SSH ControlPersist timeout in seconds (0 disables multiplexing). "
            "If omitted, the value from the configuration file is used (or default 3)."
        ),
    )
    parser.add_argument(
        "--check-dependencies",
        dest="check_dependencies",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Check rsync/ssh compatibility (use --no-check-dependencies to skip).",
    )

    # Remote listing
    parser.add_argument(
        "--list-remote",
        nargs="?",
        const="",
        metavar="NAME",
        help="List remote backups",
    )

    # Snapshot options
    parser.add_argument(
        "--snapshot-mode",
        choices=["none", "yearly", "monthly", "weekly", "daily", "hourly", "custom"],
        help="Override snapshot mode",
    )
    parser.add_argument(
        "--snapshot-custom-hours", type=int, help="Custom snapshot interval (hours)"
    )

    # Positional
    parser.add_argument(
        "PROJECT_PATH", nargs="?", help="Folder to backup (use '.' for current dir)"
    )

    # Force options (used by init-config and collision handling)
    parser.add_argument(
        "--force-all", action="store_true", help="Enable all force behaviors (skip prompts)"
    )
    parser.add_argument(
        "--force-collision-new",
        action="store_true",
        help="On name collision: create new backup automatically",
    )
    parser.add_argument(
        "--force-collision-update",
        action="store_true",
        help="On name collision: update the latest existing backup",
    )

    return parser


def resolve_bool(cli_value: bool | None, cfg_value: bool) -> bool:
    return cfg_value if cli_value is None else cli_value


def resolve_int(cli_value: int | None, cfg_value: int) -> int:
    return cfg_value if cli_value is None else cli_value


def main():
    """Main entry point"""
    parser = build_parser()
    if len(sys.argv) == 1:
        parser.print_help(sys.stderr)
        return 2

    try:
        args = parser.parse_args()
    except SystemExit as exc:
        return exc.code

    if args.version:
        print(f"{APP_NAME} v{VERSION}")
        return 0

    # Load/initialise configuration
    config = Config(args.config)

    if args.init_config:
        config.create_default(force=args.force_all)
        return 0

    try:
        config.load()
    except Exception as exc:  # noqa: BLE001
        print(f"Error loading config: {exc}", file=sys.stderr)
        return 2

    args.include_backupignore = resolve_bool(
        args.include_backupignore, config.options["include_backupignore"]
    )
    args.include_gitignore = resolve_bool(
        args.include_gitignore, config.options["include_gitignore"]
    )
    args.autodetect_profiles = resolve_bool(
        args.autodetect_profiles, config.options["autodetect_profiles"]
    )
    args.delete = resolve_bool(args.delete, config.options["delete_remote"])
    args.ssh_multiplex = resolve_int(args.ssh_multiplex, config.options["ssh_multiplex"])
    args.check_dependencies = resolve_bool(
        args.check_dependencies, config.options["check_dependencies"]
    )

    if args.check_dependencies:
        if not check_dependencies(verbose=args.verbose):
            return 2

    if args.list_servers:
        config.list_servers()
        return 0

    selected_servers = config.select_servers(args.server)
    if not selected_servers:
        return 2

    remote_mgr = RemoteManager(args.ssh_multiplex)

    if args.list_remote is not None:
        name_filter = args.list_remote or ""
        overall_rc = 0
        for idx, (server_name, server_config) in enumerate(selected_servers.items()):
            if idx > 0:
                print()
            try:
                items = remote_mgr.list_backups(server_name, server_config, name_filter)
                if not items:
                    print(f"(no backups found on {server_name})")
                else:
                    filter_text = f" (filtered by {name_filter})" if name_filter else ""
                    print(f"Backups on {server_name} {filter_text}:")
                    for item in sorted(items):
                        print("  -", item)
            except Exception as exc:  # noqa: BLE001
                print(f"Error listing backups on {server_name}: {exc}", file=sys.stderr)
                overall_rc = 2
        return overall_rc

    require_project = not args.list_remote
    if require_project and args.PROJECT_PATH is None:
        parser.error("PROJECT_PATH is required unless --list-remote is used")

    root_input = args.PROJECT_PATH or "."
    root = Path(root_input).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        print(f"Error: not a directory: {root}", file=sys.stderr)
        return 2

    sync_params = config.prepare_sync_params(root, args)

    if args.verbose:
        _print_verbose_summary(config, sync_params, selected_servers)

    successes: list[str] = []
    failures: list[str] = []
    overall_success = True

    for idx, (server_name, server_config) in enumerate(selected_servers.items()):
        if idx > 0 and args.verbose:
            print(f"\n{'=' * 50}")
        result = sync_to_server(
            server_name,
            server_config,
            sync_params,
            args,
            config,
            remote_mgr=remote_mgr,
        )
        if result == 0:
            successes.append(server_name)
            continue

        failures.append(server_name)
        overall_success = False
        if not args.force_all:
            break

    if overall_success:
        if len(selected_servers) > 1:
            print(f"\nAll backups completed: {', '.join(successes)}")
        return 0

    if len(selected_servers) > 1 and successes:
        print(f"\nSucceeded: {', '.join(successes)}")
    if failures:
        print(f"Failed: {', '.join(failures)}", file=sys.stderr)

    return 1


def _print_verbose_summary(
    config: Config,
    sync_params: SyncParams,
    selected_servers: dict[str, ServerEntry],
) -> None:
    """Print an overview before syncing."""
    print(f"Config:         {config.path}")
    print(f"Profiles:       {config.profiles_path}")
    print(f"Project:        {sync_params.folder_name}")
    print(f"Path:           {sync_params.canonical_path}")
    print(f"Snapshot mode:  {sync_params.snapshot_mode}")
    if sync_params.snapshot_mode == "custom":
        print(f"Custom hours:   {sync_params.snapshot_custom_hours}")
    print(f"Servers:        {', '.join(selected_servers.keys())}")
    print()
