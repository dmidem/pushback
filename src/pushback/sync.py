"""Rsync synchronization operations."""

import shlex
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .filter import build_merge_filter
from .remote import RemoteManager


@dataclass
class RemoteConfig:
    """Remote server configuration"""

    user: str
    host: str
    port: int
    base: str


@dataclass
class SyncContext:
    """Context for sync operation"""

    root: Path
    folder_name: str
    suffix: str
    time_suffix: str
    snapshot_mode: str
    remote: RemoteConfig
    remote_mgr: RemoteManager

    @property
    def base_remote_name(self) -> str:
        return f"{self.folder_name}_{self.suffix}"

    @property
    def exact_remote_dir(self) -> str:
        return f"{self.remote.base.rstrip('/')}/{self.base_remote_name}{self.time_suffix}"


def sync_to_server(server_name: str, server_config: dict, sync_params: dict, args, config) -> int:
    """Sync project to a single server"""
    # Extract and validate remote config
    remote_user = server_config.get("user")
    remote_host = server_config.get("host")
    remote_port = server_config.get("port", 22)
    remote_base = server_config.get("base")

    # Type guard: ensure all values are strings and not None
    if (
        not isinstance(remote_user, str)
        or not isinstance(remote_host, str)
        or not isinstance(remote_base, str)
        or not isinstance(remote_port, int)
    ):
        print(
            f"Error: server '{server_name}' has missing or incorrect base, user, host, or port",
            file=sys.stderr,
        )
        return 2

    try:
        port_int = int(remote_port)
    except ValueError:
        print(f"Error: invalid port '{remote_port}'", file=sys.stderr)
        return 2

    # Build sync context - now type checker knows these are strings
    remote_config = RemoteConfig(
        user=remote_user, host=remote_host, port=port_int, base=remote_base
    )

    remote_mgr = RemoteManager(not args.no_multiplex)

    ctx = SyncContext(
        root=sync_params["root"],
        folder_name=sync_params["folder_name"],
        suffix=sync_params["suffix"],
        time_suffix=sync_params["time_suffix"],
        snapshot_mode=sync_params["snapshot_mode"],
        remote=remote_config,
        remote_mgr=remote_mgr,
    )

    if args.verbose:
        print(f"=== Server: {server_name} ===")
        print(f"Remote: {ctx.remote.user}@{ctx.remote.host}:{ctx.remote.port}")
        print(f"Target: {ctx.exact_remote_dir}")

    if not ctx.remote_mgr.test_dir(
        ctx.remote.user,
        ctx.remote.host,
        ctx.remote.port,
        ctx.remote.base,
    ):
        print(f"Error: remote base does not exist: {ctx.remote.base}", file=sys.stderr)
        return 2

    target_remote_dir = _determine_target_dir(ctx, args)
    if target_remote_dir is None:
        return 1

    filter_path = _build_filter(ctx.root, config, args, args.verbose)
    if filter_path is None:
        return 2

    try:
        return_code = _run_rsync(ctx, target_remote_dir, filter_path, args, config)

        if return_code == 0:
            action = "Dry-run" if args.dry_run else "Backup"
            print(f"\n{action} complete for {server_name}.")
            if not args.dry_run:
                print(f"   {ctx.remote.user}@{ctx.remote.host}:{target_remote_dir}")
        else:
            print(f"\nrsync failed for {server_name} with exit code {return_code}", file=sys.stderr)

        return return_code
    finally:
        Path(filter_path).unlink(missing_ok=True)


def _determine_target_dir(ctx: SyncContext, args) -> str | None:
    """Determine target directory, handling collisions"""
    if ctx.remote_mgr.test_dir(
        ctx.remote.user,
        ctx.remote.host,
        ctx.remote.port,
        ctx.exact_remote_dir,
    ):
        if args.verbose:
            print(f"Updating existing: {ctx.exact_remote_dir}")
        return ctx.exact_remote_dir

    all_siblings = ctx.remote_mgr.list_all(
        ctx.remote.user,
        ctx.remote.host,
        ctx.remote.port,
        ctx.remote.base,
    )

    if ctx.snapshot_mode != "none":
        existing = ctx.remote_mgr.find_existing_snapshot(
            all_siblings,
            ctx.base_remote_name,
            ctx.time_suffix,
        )
        if existing:
            target = f"{ctx.remote.base.rstrip('/')}/{existing}"
            if args.verbose:
                print(f"Updating snapshot: {target}")
            return target
        if args.verbose:
            print(f"Creating snapshot: {ctx.exact_remote_dir}")
        return ctx.exact_remote_dir

    name_siblings = ctx.remote_mgr.list_siblings(
        ctx.remote.user, ctx.remote.host, ctx.remote.port, ctx.remote.base, ctx.folder_name
    )
    other_hash_dirs = [s for s in name_siblings if s != ctx.base_remote_name]

    if other_hash_dirs:
        action = _handle_collision(other_hash_dirs, args)
        if action == "abort":
            return None
        if action == "update":
            return f"{ctx.remote.base.rstrip('/')}/{other_hash_dirs[-1]}"

    return ctx.exact_remote_dir


def _handle_collision(existing: list[str], args) -> str:
    """Handle name collision"""
    force_new = args.force_all or args.force_collision_new
    force_update = args.force_all or args.force_collision_update

    if force_new and not force_update:
        return "create"
    if force_update:
        return "update"

    print("Found backup(s) with same name but different path:")
    for item in existing:
        print(f"   - {item}")
    print("\nOptions:")
    print("  (u) Update existing")
    print("  (c) Create new")
    print("  (a) Abort")
    choice = input("Choose [u/c/a] [a]: ").strip().lower() or "a"

    return {"u": "update", "c": "create"}.get(choice, "abort")


def _build_filter(root: Path, config, args, verbose: bool) -> str | None:
    """Build rsync filter file from profiles and ignore files"""
    profiles_path = config.profiles_path

    if verbose:
        print(f"Loading profiles: {profiles_path}")

    # Determine filter settings (CLI overrides config)
    include_backupignore = config.options["include_backupignore"]
    if args.include_backupignore:
        include_backupignore = True
    elif args.no_backupignore:
        include_backupignore = False

    include_gitignore = config.options["include_gitignore"]
    if args.include_gitignore:
        include_gitignore = True
    elif args.no_gitignore:
        include_gitignore = False

    autodetect = config.options["autodetect_profiles"]
    if args.autodetect_profiles:
        autodetect = True
    elif args.no_autodetect:
        autodetect = False

    try:
        filter_rules, active_profiles = build_merge_filter(
            root,
            profiles_path,
            include_backupignore=include_backupignore,
            include_gitignore=include_gitignore,
            autodetect=autodetect,
        )

        if verbose:
            if active_profiles:
                print(f"Active profiles: {', '.join(active_profiles)}")
            if include_backupignore and (root / ".backupignore").exists():
                print("Including: .backupignore")
            if include_gitignore and (root / ".gitignore").exists():
                print("Including: .gitignore")
    except FileNotFoundError:
        print(f"Error: profiles file not found: {profiles_path}", file=sys.stderr)
        print("Create it or set profiles_file in config", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Error loading profiles: {e}", file=sys.stderr)
        return None

    filter_content = "\n".join(filter_rules) + "\n" if filter_rules else ""

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            delete=False,
            suffix=".filter",
            encoding="utf-8",
        ) as f:
            f.write(filter_content)
            if verbose:
                print(f"Generated filter: {len(filter_rules)} rules")
            return f.name
    except OSError as e:
        print(f"Error creating filter file: {e}", file=sys.stderr)
        return None


def _run_rsync(ctx: SyncContext, target: str, filter_path: str, args, config) -> int:
    """Run rsync command"""
    src = str(ctx.root) + "/"
    ssh_opts = " ".join(ctx.remote_mgr.ssh_opts(ctx.remote.port))

    rsync_cmd = [
        "rsync",
        "-azP",
        "--safe-links",
        "--prune-empty-dirs",
        f"--filter=merge {filter_path}",
        "-e",
        f"ssh {ssh_opts}",
    ]

    delete_remote = config.options["delete_remote"]
    if args.delete:
        delete_remote = True
    elif args.no_delete:
        delete_remote = False

    if delete_remote:
        rsync_cmd.insert(2, "--delete")

    if args.max_size:
        rsync_cmd.append(f"--max-size={args.max_size}")
    if args.min_size:
        rsync_cmd.append(f"--min-size={args.min_size}")

    if args.dry_run:
        rsync_cmd.extend(["--dry-run", "--itemize-changes"])
    if args.stats:
        rsync_cmd.append("--stats")

    if args.rsync_extra.strip():
        try:
            extra_tokens = [
                t for t in shlex.split(args.rsync_extra) if t != "-e" and not t.startswith("-e")
            ]
            rsync_cmd.extend(extra_tokens)
        except ValueError as e:
            print(f"Error parsing rsync-extra: {e}", file=sys.stderr)
            return 2

    rsync_cmd.extend([src, f"{ctx.remote.user}@{ctx.remote.host}:{target}/"])

    if args.verbose:
        print("Running rsync:")
        print(" ", " ".join(rsync_cmd))

    try:
        result = subprocess.run(rsync_cmd, check=False)
        return result.returncode
    except KeyboardInterrupt:
        print("\nInterrupted by user", file=sys.stderr)
        return 130
    except Exception as e:
        print(f"Error running rsync: {e}", file=sys.stderr)
        return 1
