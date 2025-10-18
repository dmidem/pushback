"""Rsync synchronization operations."""

import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .filter import build_merge_filter
from .remote import RemoteManager

if TYPE_CHECKING:
    from pushback.config import SyncParams


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


_RSYNC_BINARY = None


def find_best_rsync() -> str:
    """
    Find the best rsync binary to use.
    On macOS, prefer Homebrew's GNU rsync over system openrsync.
    """
    candidates = [
        "/opt/homebrew/bin/rsync",
        "/usr/local/bin/rsync",
        shutil.which("rsync"),
    ]

    for exe in candidates:
        if not exe:
            continue
        try:
            out = subprocess.check_output([exe, "--version"], text=True, errors="ignore")
        except Exception:
            continue
        if "openrsync" not in out.lower():
            return exe

    # Fall back to whatever is available (may be openrsync)
    return shutil.which("rsync") or "rsync"


def get_rsync_binary() -> str:
    """Get the rsync binary path to use."""
    global _RSYNC_BINARY
    if _RSYNC_BINARY is None:
        _RSYNC_BINARY = find_best_rsync()
    return _RSYNC_BINARY


def sync_to_server(
    server_name: str,
    server_config,
    sync_params: "SyncParams",
    args,
    config,
    remote_mgr: RemoteManager | None = None,
) -> int:
    """Sync project to a single server"""
    try:
        remote_config = _to_remote_config(server_name, server_config)
    except (TypeError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 2

    remote_mgr = remote_mgr or RemoteManager(not args.no_multiplex)

    ctx = SyncContext(
        root=sync_params.root,
        folder_name=sync_params.folder_name,
        suffix=sync_params.suffix,
        time_suffix=sync_params.time_suffix,
        snapshot_mode=sync_params.snapshot_mode,
        remote=remote_config,
        remote_mgr=remote_mgr,
    )

    if args.verbose:
        print(f"=== Server: {server_name} ===")
        print(f"Remote: {ctx.remote.user}@{ctx.remote.host}:{ctx.remote.port}")
        print(f"Target: {ctx.exact_remote_dir}")

    try:
        if not ctx.remote_mgr.test_dir(
            ctx.remote.user,
            ctx.remote.host,
            ctx.remote.port,
            ctx.remote.base,
        ):
            raise RuntimeError(f"remote base does not exist on {server_name}: {ctx.remote.base}")
    except Exception as exc:
        print(f"Error testing remote directory: {exc}", file=sys.stderr)
        return 2

    try:
        target_remote_dir = _determine_target_dir(ctx, args)
        if target_remote_dir is None:
            return 1
    except Exception as exc:
        print(f"Error determining target directory: {exc}", file=sys.stderr)
        return 2

    filter_path = _build_filter(ctx.root, config, args, args.verbose)
    if filter_path is None:
        return 2

    try:
        return_code = _run_rsync(ctx, target_remote_dir, filter_path, args, config)

        if return_code == 0:
            action = "Dry-run" if args.dry_run else "Backup"
            print(f"\n{action} complete for {server_name}.")
            if not args.dry_run:
                print(f"   {ctx.remote.user}@{ctx.remote.host}:{target_remote_dir.rstrip('/')}/")
        else:
            print(f"\nrsync failed for {server_name} with exit code {return_code}", file=sys.stderr)

        return return_code
    finally:
        Path(filter_path).unlink(missing_ok=True)


def _to_remote_config(server_name: str, server_config) -> RemoteConfig:
    """Normalise various server representations to RemoteConfig."""
    if isinstance(server_config, RemoteConfig):
        return server_config

    if hasattr(server_config, "user"):
        user = getattr(server_config, "user")
        host = getattr(server_config, "host")
        base = getattr(server_config, "base")
        port = getattr(server_config, "port", 22)
    elif isinstance(server_config, Mapping):
        try:
            user = server_config["user"]
            host = server_config["host"]
            base = server_config["base"]
        except KeyError as exc:
            raise ValueError(
                f"Error: server '{server_name}' missing field '{exc.args[0]}'"
            ) from None
        port = server_config.get("port", 22)
    else:
        raise TypeError(
            f"Unsupported server configuration type for '{server_name}': {type(server_config)!r}"
        )

    try:
        port_int = int(port)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Error: invalid port '{port}' for server '{server_name}'") from exc

    return RemoteConfig(
        user=str(user),
        host=str(host),
        port=port_int,
        base=str(base),
    )


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
    except Exception as exc:  # noqa: BLE001
        print(f"Error loading profiles: {exc}", file=sys.stderr)
        return None

    filter_content = "\n".join(filter_rules) + "\n" if filter_rules else ""

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            delete=False,
            suffix=".filter",
            encoding="utf-8",
        ) as handle:
            handle.write(filter_content)
            if verbose:
                print(f"Generated filter: {len(filter_rules)} rules")
            return handle.name
    except OSError as exc:
        print(f"Error creating filter file: {exc}", file=sys.stderr)
        return None


def rsync_friendly_path(path: Path) -> str:
    """Convert a local Path into something rsync on POSIX understands."""
    result = str(path)
    if os.name == "nt":
        result = result.replace("\\", "/")
        match = re.match(r"^([A-Za-z]):/(.*)$", result)
        if match:
            drive = match.group(1).lower()
            result = f"/cygdrive/{drive}/{match.group(2)}"
    return result


def _run_rsync(ctx: SyncContext, target: str, filter_path: str, args, config) -> int:
    """Run rsync command"""
    src = _ensure_trailing_slash(rsync_friendly_path(Path(ctx.root)))
    dest_path = _ensure_trailing_slash(target)
    dest = f"{ctx.remote.user}@{ctx.remote.host}:{dest_path}"
    filt = rsync_friendly_path(Path(filter_path))
    ssh_opts = shlex.join(ctx.remote_mgr.ssh_opts(ctx.remote.port))

    rsync = get_rsync_binary()

    rsync_cmd = [
        rsync,
        "-azP",
        "--safe-links",
        "--prune-empty-dirs",
        "--filter",
        f"merge {filt}",
        "-e",
        f"ssh {ssh_opts}",
    ]

    delete_remote = config.options["delete_remote"]
    if args.delete:
        delete_remote = True
    elif args.no_delete:
        delete_remote = False

    if delete_remote:
        rsync_cmd.insert(1, "--delete")

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
                token
                for token in shlex.split(args.rsync_extra)
                if token != "-e" and not token.startswith("-e")
            ]
            rsync_cmd.extend(extra_tokens)
        except ValueError as exc:
            print(f"Error parsing rsync-extra: {exc}", file=sys.stderr)
            return 2

    rsync_cmd.extend([src, dest])

    if args.verbose:
        print("Running rsync:")
        print(" ", " ".join(rsync_cmd))

    try:
        result = subprocess.run(rsync_cmd, check=False)
        return result.returncode
    except KeyboardInterrupt:
        print("\nInterrupted by user", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001
        print(f"Error running rsync: {exc}", file=sys.stderr)
        return 1


def _ensure_trailing_slash(value: str) -> str:
    """Ensure exactly one trailing slash."""
    return value.rstrip("/") + "/"
