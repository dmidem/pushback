"""Test rsync filter generation from profiles and gitignore files."""

import os
import shutil
import subprocess
from pathlib import Path
from textwrap import dedent

import pytest

from pushback.filter import build_merge_filter
from pushback.sync import rsync_friendly_path


def has_command(cmd: str) -> bool:
    """Check if command is available."""
    return shutil.which(cmd) is not None


def generate_corpus(root: Path, _seed: int = 42) -> list[Path]:
    """Generate diverse test files with edge cases."""
    files: list[Path] = []

    # 1. Normal cases
    normal_names = [
        "normal.txt",
        "README.md",
        "data.json",
    ]

    # 2. Unicode and special chars
    special_names = [
        "café.txt",
        "file with spaces.txt",
        "  leading-spaces.txt",
        "#hashtag.txt",
        "!important.txt",
        "$dollar.txt",
        "&ampersand.txt",
        "semi;colon.txt",
        "pipe|.txt",
        "back`tick.txt",
        "single'.txt",
        'double".txt',
        "file*.glob",
        "file?.question",
        "file[].bracket",
        "very" + "long" * 50 + ".txt",
    ]

    if os.name != "nt":
        special_names.extend(
            [
                "trailing-spaces.txt  ",
                "файл.txt",
                "文件.txt",
            ]
        )

    # 3. Dot files
    dot_files = [
        ".hidden",
        ".gitignore",
        ".env",
        "..double-dot",
        ".dot.in.middle.txt",
    ]

    for name in normal_names + special_names + dot_files:
        try:
            path = root / name
            path.write_text(f"content of {name}")
            files.append(path)
        except (OSError, ValueError):
            pass

    # 5. Deep nesting
    deep = root
    for i in range(15):
        deep = deep / f"level{i}"
        deep.mkdir(exist_ok=True)
        nested_file = deep / f"file{i}.txt"
        nested_file.write_text(f"depth {i}")
        files.append(nested_file)
        if i % 3 == 0:
            hidden = deep / ".hidden"
            hidden.write_text("hidden")
            files.append(hidden)

    # 6. Many files in one dir
    many = root / "many"
    many.mkdir()
    for i in range(50):
        log_file = many / f"file{i:03d}.log"
        log_file.write_text(f"log entry {i}")
        files.append(log_file)

    for i in range(50):
        data_file = many / f"data{i:03d}.txt"
        data_file.write_text(f"data {i}")
        files.append(data_file)

    # 7. Complex directory structure
    build = root / "build"
    build.mkdir()
    output_file = build / "output.txt"
    output_file.write_text("build output")
    files.append(output_file)

    keep = build / "keep"
    keep.mkdir()
    artifact = keep / "artifact.txt"
    artifact.write_text("important")
    files.append(artifact)

    nested = keep / "nested"
    nested.mkdir()
    deep_artifact = nested / "deep.txt"
    deep_artifact.write_text("deep artifact")
    files.append(deep_artifact)

    # 8. Empty directory
    (root / "empty-dir").mkdir()

    # 9. Non-ASCII directory names
    try:
        unicode_dir = root / "中文目录"
        unicode_dir.mkdir()
        unicode_file = unicode_dir / "file.txt"
        unicode_file.write_text("unicode dir content")
        files.append(unicode_file)
    except (OSError, ValueError):
        pass

    # 10. Multiple levels with same name
    for level in ["a", "b", "c"]:
        dir_path = root / level / "build"
        dir_path.mkdir(parents=True)
        test_file = dir_path / "test.txt"
        test_file.write_text(f"build in {level}")
        files.append(test_file)

    # 11. Files with unusual sizes
    empty = root / "empty.txt"
    empty.write_text("")
    files.append(empty)

    large = root / "large.bin"
    large.write_bytes(b"x" * 100_000)
    files.append(large)

    # 12. Files matching common ignore patterns
    cache_dir = root / ".cache"
    cache_dir.mkdir()
    cache_file = cache_dir / "data.db"
    cache_file.write_text("cache")
    files.append(cache_file)

    node_dir = root / "node_modules" / "pkg"
    node_dir.mkdir(parents=True)
    node_file = node_dir / "index.js"
    node_file.write_text("module")
    files.append(node_file)

    return files


@pytest.fixture
def project(tmp_path):
    """Create a test project with files and ignore patterns."""
    (tmp_path / "src").mkdir()
    (tmp_path / "build").mkdir()
    (tmp_path / "build/artifacts").mkdir(parents=True)
    (tmp_path / ".cache").mkdir()
    (tmp_path / "node_modules/pkg").mkdir(parents=True)

    files = {
        "src/main.py": "code",
        "src/test.py": "test",
        "build/output.txt": "build",
        "build/artifacts/keep.txt": "artifact",
        ".cache/data.db": "cache",
        "node_modules/pkg/index.js": "dep",
        "README.md": "docs",
        "debug.log": "log",
        "important.log": "log",
    }

    for relative, content in files.items():
        file_path = tmp_path / relative
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content)

    gitignore = tmp_path / ".gitignore"
    gitignore.write_text(
        dedent(
            """
            # Python
            __pycache__/
            *.pyc

            # Build - use build/* to allow negation to work
            build/*
            !build/artifacts/

            # Deps
            node_modules/

            # Logs
            *.log
            !important.log

            # Cache
            .cache/
            """
        ).strip()
        + "\n"
    )

    profiles = tmp_path / "profiles.toml"
    profiles.write_text(
        dedent(
            """
            [profile.python]
            always = true
            ignore = ["*.pyc", "__pycache__/"]

            [profile.node]
            detect.any_of = ["package.json", "node_modules/"]
            ignore = ["node_modules/"]
            """
        ).strip()
        + "\n"
    )

    return tmp_path, list(files.keys())


def get_rsync_files(source: Path, filter_rules: list[str]) -> set[str]:
    """Run rsync dry-run and return list of files that would be copied."""
    filter_file = source.parent / "rsync_filter.txt"
    filter_file.write_text("\n".join(filter_rules) + "\n")

    try:
        dest = source.parent / "dest"
        dest.mkdir(exist_ok=True)

        src = rsync_friendly_path(source)
        dst = rsync_friendly_path(dest)
        filt = rsync_friendly_path(filter_file)

        result = subprocess.run(
            [
                "rsync",
                "-a",
                "-n",
                "--out-format=%n",
                "--filter",
                f"merge {filt}",
                f"{src}/",
                f"{dst}/",
            ],
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8",
            errors="replace",
        )

        collected: set[str] = set()
        for line in result.stdout.splitlines():
            line = line.rstrip("\n\r")
            if not line or line.endswith("/"):
                continue
            if line.startswith("./"):
                line = line[2:]
            line = line.replace("\\", "/")
            if (source / line).is_file():
                collected.add(line)

        return collected
    finally:
        filter_file.unlink(missing_ok=True)


def get_git_files(repo: Path, all_files: list[str]) -> set[str]:
    """Get list of files not ignored by git."""
    existing = {relative for relative in all_files if (repo / relative).is_file()}
    if os.name == "nt":
        existing = {relative for relative in existing if not relative.endswith(" ")}

    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)

    result = subprocess.run(
        ["git", "check-ignore", "--stdin", "-z"],
        cwd=repo,
        input="\0".join(sorted(existing)).encode(),
        capture_output=True,
    )

    ignored: set[str] = set()
    if result.stdout:
        for path in result.stdout.decode().split("\0"):
            if path:
                ignored.add(path)

    return existing - ignored


@pytest.mark.skipif(not has_command("rsync"), reason="rsync not available")
@pytest.mark.skipif(not has_command("git"), reason="git not available")
def test_filter_matches_gitignore_behavior(project):
    """Test that generated filters match git's ignore behavior."""
    project_root, all_files = project
    profiles_path = project_root / "profiles.toml"

    git_files = get_git_files(project_root, all_files)

    filter_rules, active_profiles = build_merge_filter(
        project_root,
        profiles_path,
        include_backupignore=False,
        include_gitignore=True,
        autodetect_profiles=True,
    )
    assert "python" in active_profiles
    assert "node" in active_profiles

    rsync_files = get_rsync_files(project_root, filter_rules)

    only_git = git_files - rsync_files
    only_rsync = rsync_files - git_files

    meta_files = {".gitignore", "profiles.toml", ".backupignore"}
    only_git = {item for item in only_git if not item.startswith(".git/")}
    only_rsync = {
        item for item in only_rsync if not item.startswith(".git/") and item not in meta_files
    }

    assert only_git == set(), f"Files in git but not rsync: {only_git}"
    assert only_rsync == set(), f"Files in rsync but not git: {only_rsync}"

    assert "src/main.py" in rsync_files
    assert "README.md" in rsync_files
    assert "important.log" in rsync_files
    assert "build/artifacts/keep.txt" in rsync_files

    assert "build/output.txt" not in rsync_files
    assert "debug.log" not in rsync_files
    assert ".cache/data.db" not in rsync_files
    assert "node_modules/pkg/index.js" not in rsync_files


def test_profile_detection(project):
    """Test that profiles are correctly detected and applied."""
    project_root, _ = project
    profiles_path = project_root / "profiles.toml"

    _, active = build_merge_filter(
        project_root,
        profiles_path,
        include_backupignore=False,
        include_gitignore=False,
        autodetect_profiles=True,
    )

    assert "python" in active
    assert "node" in active


def test_backupignore_integration(tmp_path):
    """Test that .backupignore patterns are included."""
    (tmp_path / "data.txt").write_text("data")
    (tmp_path / "secret.key").write_text("secret")

    backupignore = tmp_path / ".backupignore"
    backupignore.write_text("*.key\n")

    profiles = tmp_path / "profiles.toml"
    profiles.write_text("")

    rules, _ = build_merge_filter(
        tmp_path,
        profiles,
        include_backupignore=True,
        include_gitignore=False,
        autodetect_profiles=False,
    )

    assert any("*.key" in rule for rule in rules)


@pytest.mark.skipif(not has_command("rsync"), reason="rsync not available")
@pytest.mark.skipif(not has_command("git"), reason="git not available")
def test_edge_cases_and_scale(tmp_path):
    """Test with unusual filenames and large file counts."""
    all_files = generate_corpus(tmp_path)

    gitignore = tmp_path / ".gitignore"
    gitignore.write_text(
        dedent(
            """
            *.log
            !important.log
            many/file5*.log
            level*/
            !level5/
            """
        ).strip()
        + "\n"
    )

    profiles = tmp_path / "profiles.toml"
    profiles.write_text("")

    git_files = get_git_files(
        tmp_path, [path.relative_to(tmp_path).as_posix() for path in all_files if path.is_file()]
    )

    filter_rules, _ = build_merge_filter(
        tmp_path,
        profiles,
        include_backupignore=False,
        include_gitignore=True,
        autodetect_profiles=False,
    )

    rsync_files = get_rsync_files(tmp_path, filter_rules)

    only_git = git_files - rsync_files
    only_rsync = rsync_files - git_files

    only_git = {item for item in only_git if not item.startswith(".git/")}
    only_rsync = {
        item
        for item in only_rsync
        if not item.startswith(".git/") and item not in (".gitignore", "profiles.toml")
    }

    assert only_git == set(), f"Files in git but not rsync: {only_git}"
    assert only_rsync == set(), f"Files in rsync but not git: {only_rsync}"


def test_tricky_gitignore_patterns(tmp_path):
    """Test edge cases in gitignore pattern matching."""
    files = generate_corpus(tmp_path)

    gitignore = tmp_path / ".gitignore"
    gitignore.write_text(
        dedent(
            """
            # Pattern precedence
            *.log
            !important*.log
            debug-important.log

            # Directory negation
            build/*
            !build/keep/

            # Character classes
            file[0-9]*.log

            # Anchored vs unanchored
            /cache/
            .cache/

            # Escaped characters
            \\#hashtag.txt

            # Trailing spaces (should be ignored by git)
            *.tmp
            """
        ).strip()
        + "\n"
    )

    profiles = tmp_path / "profiles.toml"
    profiles.write_text("")

    git_files = get_git_files(
        tmp_path, [path.relative_to(tmp_path).as_posix() for path in files if path.is_file()]
    )

    filter_rules, _ = build_merge_filter(
        tmp_path,
        profiles,
        include_backupignore=False,
        include_gitignore=True,
        autodetect_profiles=False,
    )

    rsync_files = get_rsync_files(tmp_path, filter_rules)

    only_git = git_files - rsync_files
    only_rsync = rsync_files - git_files

    only_git = {item for item in only_git if not item.startswith(".git/")}
    only_rsync = {
        item
        for item in only_rsync
        if not item.startswith(".git/") and item not in (".gitignore", "profiles.toml")
    }

    assert only_git == set(), f"Files in git but not rsync: {only_git}"
    assert only_rsync == set(), f"Files in rsync but not git: {only_rsync}"
