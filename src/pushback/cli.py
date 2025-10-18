"""
pushback — SSH/rsync-based backup tool.

Copyright (c) 2025 Dmitry Demin, https://github.com/dmidem
Licensed under Apache-2.0 OR MIT
"""

import argparse
import sys
from pathlib import Path

from pushback.config import Config, ServerEntry, SyncParams
from pushback.remote import RemoteManager
from pushback.sync import sync_to_server

from . import APP_NAME, __version__

HELP_EPILOG = f"""
REQUIREMENTS
  Local:  rsync, ssh
  Remote: standard POSIX tools (ls, xargs, basename)

CONFIG
  Default: ~/.config/{APP_NAME}/config.toml
  Profiles: ~/.config/{APP_NAME}/profiles.toml
  Create:   {APP_NAME} --init-config

MULTIPLE SERVERS
  Define servers in config.toml:

    [[server]]
    name = "main"
    user = "user1"
    host = "host1.example.com"
    port = 22
    base = "~/{APP_NAME}"
    default = true

    [[server]]
    name = "backup"
    user = "user2"
    host = "host2.example.com"
    port = 22
    base = "~/backups"
    default = false

  Usage:
    {APP_NAME} . # Uses all default servers
    {APP_NAME} --server backup . # Uses only 'backup'
    {APP_NAME} --server main,backup . # Uses both

IGNORE RULES
  Uses filters with gitignore semantics:
    • Profile-based rules (auto-detected from profiles.toml)
    • Per-project: .backupignore (gitignore format)

SIZE FILTERING
  Use rsync's native size filters:
    --max-size 100M # Skip files larger than 100M
    --min-size 1K # Skip files smaller than 1K

EXAMPLES
  • Simple backup:         {APP_NAME} .
  • Preview changes:       {APP_NAME} --dry-run .
  • Skip large files:      {APP_NAME} --max-size 500M .
  • Multiple servers:      {APP_NAME} --server main,backup .
  • Daily snapshots:       {APP_NAME} --snapshot-mode daily ~/project
"""


def build_parser() -> argparse.ArgumentParser:
    """Build argument parser"""
    parser = argparse.ArgumentParser(
        prog=APP_NAME,
        description="Backup/sync a project folder to remote server(s) using rsync over SSH.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=HELP_EPILOG,
    )

    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help=f"Path to config file (default: ~/.config/{APP_NAME}/config.toml)",
    )
    parser.add_argument("--init-config", action="store_true", help="Create template config file")
    parser.add_argument(
        "--server",
        type=str,
        help="Use specific server(s), comma-separated",
    )
    parser.add_argument("--list-servers", action="store_true", help="List configured servers")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    parser.add_argument("--version", action="store_true", help="Print version number and exit")
    parser.add_argument(
        "--no-multiplex", action="store_true", help="Disable SSH connection sharing"
    )

    delete_group = parser.add_mutually_exclusive_group()
    delete_group.add_argument(
        "-d",
        "--delete",
        action="store_true",
        help="Delete remote files not present locally",
    )
    delete_group.add_argument("--no-delete", action="store_true", help="Disable deletion")

    backupignore_group = parser.add_mutually_exclusive_group()
    backupignore_group.add_argument(
        "--include-backupignore",
        action="store_true",
        help="Include .backupignore rules (overrides config)",
    )
    backupignore_group.add_argument(
        "--no-backupignore",
        action="store_true",
        help="Exclude .backupignore rules (overrides config)",
    )

    gitignore_group = parser.add_mutually_exclusive_group()
    gitignore_group.add_argument(
        "--include-gitignore",
        action="store_true",
        help="Include .gitignore rules (overrides config)",
    )
    gitignore_group.add_argument(
        "--no-gitignore",
        action="store_true",
        help="Exclude .gitignore rules (overrides config)",
    )

    autodetect_group = parser.add_mutually_exclusive_group()
    autodetect_group.add_argument(
        "--autodetect-profiles",
        action="store_true",
        help="Auto-detect project type (overrides config)",
    )
    autodetect_group.add_argument(
        "--no-autodetect",
        action="store_true",
        help="Disable profile auto-detection (overrides config)",
    )

    # Rsync options
    parser.add_argument("--dry-run", action="store_true", help="Preview changes only")
    parser.add_argument("--stats", action="store_true", help="Show rsync stats")
    parser.add_argument("--max-size", type=str, help="Skip files larger than SIZE (e.g., 100M, 2G)")
    parser.add_argument(
        "--min-size", type=str, help="Skip files smaller than SIZE (e.g., 1K, 100B)"
    )
    parser.add_argument("--rsync-extra", type=str, default="", help="Extra rsync flags")

    # Remote listing
    parser.add_argument(
        "--list-remote",
        nargs="?",
        const="",
        metavar="NAME",
        help="List remote backups",
    )

    # Force options
    parser.add_argument("--force-all", action="store_true", help="Enable all force behaviors")
    parser.add_argument(
        "--force-collision-new", action="store_true", help="Auto-create new on collision"
    )
    parser.add_argument(
        "--force-collision-update", action="store_true", help="Auto-update on collision"
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

    parser.add_argument(
        "PROJECT_PATH", nargs="?", help="Folder to backup (use '.' for current dir)"
    )

    return parser


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
        print(f"{APP_NAME} v{__version__}")
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

    if args.list_servers:
        config.list_servers()
        return 0

    selected_servers = config.select_servers(args.server)
    if not selected_servers:
        return 2

    remote_mgr = RemoteManager(not args.no_multiplex)

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
                rc = 2
            if rc != 0:
                overall_rc = rc
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
