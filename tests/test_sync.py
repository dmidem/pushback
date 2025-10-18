"""Integration tests for sync.py - requires rsync"""

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from pushback.sync import (
    _build_filter,
    _handle_collision,
    _to_remote_config,
    rsync_friendly_path,
)


@pytest.fixture
def test_env(tmp_path):
    """Create test environment with source and remote directories"""
    source_dir = tmp_path / "source"
    source_dir.mkdir()

    remote_base = tmp_path / "remote"
    remote_base.mkdir()

    # Create test files
    (source_dir / "file1.txt").write_text("content1")
    (source_dir / "file2.txt").write_text("content2")
    (source_dir / "subdir").mkdir()
    (source_dir / "subdir" / "file3.txt").write_text("content3")

    # Create profiles.toml with proper exclude patterns
    profiles_path = tmp_path / "profiles.toml"
    profiles_path.write_text("""
[profile.safe_defaults]
always = true
ignore = ["*.log", ".git/"]
""")

    # Create .backupignore for additional filtering
    backupignore = source_dir / ".backupignore"
    backupignore.write_text("*.log\n.git/\n")

    # Create config object with new options
    config = SimpleNamespace(
        profiles_path=profiles_path,
        options={
            "delete_remote": False,
            "include_backupignore": True,
            "include_gitignore": False,
            "autodetect_profiles": True,
        },
    )

    # Create args object with filter options
    args = SimpleNamespace(
        verbose=False,
        dry_run=False,
        delete=False,
        no_delete=False,
        max_size=None,
        min_size=None,
        stats=False,
        rsync_extra="",
        no_multiplex=True,
        force_all=False,
        force_collision_new=False,
        force_collision_update=False,
        include_backupignore=False,
        no_backupignore=False,
        include_gitignore=False,
        no_gitignore=False,
        autodetect_profiles=False,
        no_autodetect=False,
    )

    return {
        "source_dir": source_dir,
        "remote_base": remote_base,
        "profiles_path": profiles_path,
        "config": config,
        "args": args,
        "tmp_path": tmp_path,
    }


def test_local_rsync_basic_sync(test_env):
    """Test basic rsync to local directory (simulating remote)"""
    result = _local_rsync_sync(
        test_env["source_dir"],
        test_env["remote_base"] / "testproject_abc123",
        test_env["config"],
        test_env["args"],
    )

    assert result == 0
    target_dir = test_env["remote_base"] / "testproject_abc123"
    assert (target_dir / "file1.txt").read_text() == "content1"
    assert (target_dir / "file2.txt").read_text() == "content2"
    assert (target_dir / "subdir" / "file3.txt").read_text() == "content3"


def test_local_rsync_with_filter(test_env):
    """Test rsync with filter rules"""
    source_dir = test_env["source_dir"]
    remote_base = test_env["remote_base"]

    # Add files that should be filtered
    (source_dir / "test.log").write_text("log content")
    (source_dir / ".git").mkdir()
    (source_dir / ".git" / "config").write_text("git config")

    target_dir = remote_base / "testproject_abc123"

    result = _local_rsync_sync(source_dir, target_dir, test_env["config"], test_env["args"])

    assert result == 0
    assert (target_dir / "file1.txt").exists()
    # These should be filtered out by .backupignore
    assert not (target_dir / "test.log").exists()
    assert not (target_dir / ".git").exists()


def test_local_rsync_delete_mode(test_env):
    """Test rsync with --delete option"""
    source_dir = test_env["source_dir"]
    remote_base = test_env["remote_base"]
    target_dir = remote_base / "testproject_abc123"

    # Initial sync
    _local_rsync_sync(source_dir, target_dir, test_env["config"], test_env["args"])

    # Create extra file in target
    (target_dir / "extra.txt").write_text("should be deleted")

    # Delete file from source
    (source_dir / "file2.txt").unlink()

    # Sync with delete - create modified args
    args_dict = vars(test_env["args"]).copy()
    args_dict["delete"] = True
    args_with_delete = SimpleNamespace(**args_dict)

    result = _local_rsync_sync(source_dir, target_dir, test_env["config"], args_with_delete)

    assert result == 0
    assert (target_dir / "file1.txt").exists()
    assert not (target_dir / "file2.txt").exists()
    assert not (target_dir / "extra.txt").exists()


def test_local_rsync_dry_run(test_env):
    """Test dry-run mode"""
    source_dir = test_env["source_dir"]
    remote_base = test_env["remote_base"]
    target_dir = remote_base / "testproject_abc123"
    target_dir.mkdir(parents=True)

    # Create modified args with dry_run=True
    args_dict = vars(test_env["args"]).copy()
    args_dict["dry_run"] = True
    args_dry_run = SimpleNamespace(**args_dict)

    result = _local_rsync_sync(source_dir, target_dir, test_env["config"], args_dry_run)

    assert result == 0
    # Files should not be created in dry-run
    assert not (target_dir / "file1.txt").exists()


def test_handle_collision_force_new(test_env):
    """Test collision handling with force_collision_new"""
    existing = ["testproject_old123", "testproject_old456"]
    args = SimpleNamespace(force_all=False, force_collision_new=True, force_collision_update=False)

    result = _handle_collision(existing, args)
    assert result == "create"


def test_handle_collision_force_update(test_env):
    """Test collision handling with force_collision_update"""
    existing = ["testproject_old123"]
    args = SimpleNamespace(force_all=False, force_collision_new=False, force_collision_update=True)

    result = _handle_collision(existing, args)
    assert result == "update"


def test_to_remote_config_with_mapping():
    config = {
        "user": "alice",
        "host": "example.com",
        "port": "2200",
        "base": "/data",
    }
    remote = _to_remote_config("main", config)
    assert remote.user == "alice"
    assert remote.host == "example.com"
    assert remote.port == 2200
    assert remote.base == "/data"


def test_to_remote_config_with_namespace():
    config = SimpleNamespace(user="bob", host="srv", port=2022, base="~/backups")
    remote = _to_remote_config("secondary", config)
    assert remote.user == "bob"
    assert remote.port == 2022
    assert remote.base == "~/backups"


def test_to_remote_config_invalid_port():
    config = {"user": "bad", "host": "srv", "port": "nan", "base": "/tmp"}
    with pytest.raises(ValueError):
        _to_remote_config("broken", config)


def _local_rsync_sync(
    source: Path,
    target: Path,
    config,
    args,
    verbose: bool = False,
) -> int:
    """Helper to run rsync locally without SSH"""
    filter_path = _build_filter(source, config, args, verbose)
    if filter_path is None:
        return 2

    try:
        target.mkdir(parents=True, exist_ok=True)

        src_path = rsync_friendly_path(source)
        dst_path = rsync_friendly_path(target)
        filt = rsync_friendly_path(Path(filter_path))

        def with_slash(path: str) -> str:
            return path.rstrip("/") + "/"

        cmd = [
            "rsync",
            "-a",
            "--safe-links",
            "--prune-empty-dirs",
            "--filter",
            f"merge {filt}",
        ]

        if args.delete:
            cmd.append("--delete")
        if args.dry_run:
            cmd.extend(["--dry-run", "--itemize-changes"])

        cmd.extend([with_slash(src_path), with_slash(dst_path)])

        result = subprocess.run(cmd, capture_output=True, text=True)
        return result.returncode
    finally:
        Path(filter_path).unlink(missing_ok=True)
