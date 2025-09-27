"""Test rsync filter generation from profiles and gitignore files."""

import random
import shutil
import subprocess
from pathlib import Path

import pytest

from pushback.filter import build_merge_filter


def has_command(cmd: str) -> bool:
    """Check if command is available."""
    return shutil.which(cmd) is not None


def generate_corpus(root: Path, seed: int = 42) -> list[Path]:
    """Generate diverse test files with edge cases."""
    random.seed(seed)

    files = []

    # 1. Normal cases
    normal_names = [
        "normal.txt",
        "README.md",
        "data.json",
    ]

    # 2. Unicode and special chars
    special_names = [
        "café.txt",
        "файл.txt",  # Cyrillic
        "文件.txt",  # Chinese
        "file with spaces.txt",
        "  leading-spaces.txt",
        "trailing-spaces.txt  ",
        "#hashtag.txt",
        "!important.txt",
        "$dollar.txt",
        "&ampersand.txt",
        "semi;colon.txt",
        "pipe|.txt",
        "back`tick.txt",
        "single'.txt",
        'double".txt',
        "file*.glob",  # Actual asterisk
        "file?.question",  # Actual question mark
        "file[].bracket",  # Actual brackets
        "very" + "long" * 50 + ".txt",
    ]

    # 3. Dot files
    dot_files = [
        ".hidden",
        ".gitignore",
        ".env",
        "..double-dot",
        ".dot.in.middle.txt",
    ]

    # 4. Create flat structure
    for name in normal_names + special_names + dot_files:
        try:
            path = root / name
            path.write_text(f"content of {name}")
            files.append(path)
        except (OSError, ValueError):
            # Skip if filesystem doesn't support the name
            pass

    # 5. Deep nesting
    deep = root
    for i in range(15):
        deep = deep / f"level{i}"
        deep.mkdir(exist_ok=True)
        f = deep / f"file{i}.txt"
        f.write_text(f"depth {i}")
        files.append(f)
        # Add hidden file at some levels
        if i % 3 == 0:
            hidden = deep / ".hidden"
            hidden.write_text("hidden")
            files.append(hidden)

    # 6. Many files in one dir (different types)
    many = root / "many"
    many.mkdir()
    for i in range(50):
        # Mix of extensions and patterns
        f = many / f"file{i:03d}.log"
        f.write_text(f"log entry {i}")
        files.append(f)

    for i in range(50):
        f = many / f"data{i:03d}.txt"
        f.write_text(f"data {i}")
        files.append(f)

    # 7. Complex directory structure for negation testing
    build = root / "build"
    build.mkdir()
    (build / "output.txt").write_text("build output")
    files.append(build / "output.txt")

    keep = build / "keep"
    keep.mkdir()
    (keep / "artifact.txt").write_text("important")
    files.append(keep / "artifact.txt")

    nested = keep / "nested"
    nested.mkdir()
    (nested / "deep.txt").write_text("deep artifact")
    files.append(nested / "deep.txt")

    # 8. Empty directory
    empty = root / "empty-dir"
    empty.mkdir()

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
        f = dir_path / "test.txt"
        f.write_text(f"build in {level}")
        files.append(f)

    # 11. Files with unusual sizes
    (root / "empty.txt").write_text("")
    files.append(root / "empty.txt")

    large = root / "large.bin"
    large.write_bytes(b"x" * 100_000)  # 100KB
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
    # Create directory structure
    (tmp_path / "src").mkdir()
    (tmp_path / "build").mkdir()
    (tmp_path / "build/artifacts").mkdir()
    (tmp_path / ".cache").mkdir()
    (tmp_path / "node_modules/pkg").mkdir(parents=True)

    # Create files
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

    for path, content in files.items():
        file_path = tmp_path / path
        file_path.write_text(content)

    # Create .gitignore
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text("""
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
""")

    # Create profiles.toml
    profiles = tmp_path / "profiles.toml"
    profiles.write_text("""
[profile.python]
always = true
ignore = ["*.pyc", "__pycache__/"]

[profile.node]
detect.any_of = ["package.json", "node_modules/"]
ignore = ["node_modules/"]
""")

    return tmp_path, list(files.keys())


def get_rsync_files(source: Path, filter_rules: list[str]) -> set[str]:
    """Run rsync dry-run and return list of files that would be copied."""
    # Write filter rules to temp file
    filter_file = source.parent / "rsync_filter.txt"
    filter_file.write_text("\n".join(filter_rules) + "\n")

    dest = source.parent / "dest"
    dest.mkdir(exist_ok=True)

    result = subprocess.run(
        [
            "rsync",
            "-a",
            "-n",
            "--out-format=%n",
            f"--filter=merge {filter_file}",
            f"{source}/",
            f"{dest}/",
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    files = set()
    for line in result.stdout.split("\n"):
        # Only remove newlines, preserve other whitespace in filenames
        line = line.rstrip("\n\r")

        if not line or line.endswith("/"):
            continue

        # Remove leading ./ prefix if present
        if line.startswith("./"):
            line = line[2:]

        if (source / line).is_file():
            files.add(line)

    return files


def get_git_files(repo: Path, all_files: list[str]) -> set[str]:
    """Get list of files not ignored by git."""
    # Initialize git repo
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)

    # Check which files are ignored
    result = subprocess.run(
        ["git", "check-ignore", "--stdin", "-z"],
        cwd=repo,
        input="\0".join(all_files).encode(),
        capture_output=True,
    )

    ignored = set()
    if result.stdout:
        for path in result.stdout.decode().split("\0"):
            if path:
                ignored.add(path)

    return set(all_files) - ignored


@pytest.mark.skipif(not has_command("rsync"), reason="rsync not available")
@pytest.mark.skipif(not has_command("git"), reason="git not available")
def test_filter_matches_gitignore_behavior(project):
    """Test that generated filters match git's ignore behavior."""
    project_root, all_files = project
    profiles_path = project_root / "profiles.toml"

    # Get expected files from git
    git_files = get_git_files(project_root, all_files)

    # Generate filter and get rsync files
    filter_rules, active_profiles = build_merge_filter(
        project_root,
        profiles_path,
        include_backupignore=False,
        include_gitignore=True,
        autodetect=True,
    )

    rsync_files = get_rsync_files(project_root, filter_rules)

    # Compare
    only_git = git_files - rsync_files
    only_rsync = rsync_files - git_files

    # Filter out .git directory and profiles.toml (created after file list)
    # Meta files created by test/git, not part of the corpus
    meta_files = {".gitignore", "profiles.toml", ".backupignore"}
    only_git = {f for f in only_git if not f.startswith(".git/")}
    only_rsync = {f for f in only_rsync if not f.startswith(".git/") and f not in meta_files}

    assert only_git == set(), f"Files in git but not rsync: {only_git}"
    assert only_rsync == set(), f"Files in rsync but not git: {only_rsync}"

    # Verify specific expected behavior
    assert "src/main.py" in rsync_files
    assert "README.md" in rsync_files
    assert "important.log" in rsync_files  # Negated pattern
    assert "build/artifacts/keep.txt" in rsync_files  # Negated pattern

    assert "build/output.txt" not in rsync_files
    assert "debug.log" not in rsync_files
    assert ".cache/data.db" not in rsync_files
    assert "node_modules/pkg/index.js" not in rsync_files


def test_profile_detection(project):
    """Test that profiles are correctly detected and applied."""
    project_root, _ = project
    profiles_path = project_root / "profiles.toml"

    # Test with autodetect
    _, active = build_merge_filter(
        project_root,
        profiles_path,
        include_backupignore=False,
        include_gitignore=False,
        autodetect=True,
    )

    assert "python" in active  # always=true
    assert "node" in active  # node_modules/ exists


def test_backupignore_integration(tmp_path):
    """Test that .backupignore patterns are included."""
    # Create minimal project
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
        autodetect=False,
    )

    # Check that .key pattern is in rules
    assert any("*.key" in rule for rule in rules)


@pytest.mark.slow
@pytest.mark.skipif(not has_command("rsync"), reason="rsync not available")
@pytest.mark.skipif(not has_command("git"), reason="git not available")
def test_edge_cases_and_scale(tmp_path):
    """Test with unusual filenames and large file counts."""
    all_files = generate_corpus(tmp_path)

    # Create .gitignore with patterns that interact with edge cases
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text("""
*.log
!important.log
many/file5*.log
level*/
!level5/
""")

    # Create minimal profiles
    profiles = tmp_path / "profiles.toml"
    profiles.write_text("")

    # Get all file paths relative to root
    all_file_paths = [str(p.relative_to(tmp_path)) for p in all_files]

    # Get expected files from git
    git_files = get_git_files(tmp_path, all_file_paths)

    # Generate filter and get rsync files
    filter_rules, _ = build_merge_filter(
        tmp_path,
        profiles,
        include_backupignore=False,
        include_gitignore=True,
        autodetect=False,
    )

    rsync_files = get_rsync_files(tmp_path, filter_rules)

    # Compare
    only_git = git_files - rsync_files
    only_rsync = rsync_files - git_files

    # Filter out .git directory and files created after corpus generation
    only_git = {f for f in only_git if not f.startswith(".git/")}
    only_rsync = {
        f
        for f in only_rsync
        if not f.startswith(".git/") and f not in (".gitignore", "profiles.toml")
    }

    assert only_git == set(), f"Files in git but not rsync: {only_git}"
    assert only_rsync == set(), f"Files in rsync but not git: {only_rsync}"


def test_tricky_gitignore_patterns(tmp_path):
    """Test edge cases in gitignore pattern matching."""
    # Create complex structure
    files = generate_corpus(tmp_path)

    # Tricky .gitignore
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text("""
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
""")

    profiles = tmp_path / "profiles.toml"
    profiles.write_text("")

    # Test that conversion handles all these cases
    git_files = get_git_files(tmp_path, [str(p.relative_to(tmp_path)) for p in files])

    filter_rules, _ = build_merge_filter(
        tmp_path,
        profiles,
        include_backupignore=False,
        include_gitignore=True,
        autodetect=False,
    )

    rsync_files = get_rsync_files(tmp_path, filter_rules)

    # Should match git behavior
    only_git = git_files - rsync_files
    only_rsync = rsync_files - git_files

    only_git = {f for f in only_git if not f.startswith(".git/")}
    only_rsync = {
        f
        for f in only_rsync
        if not f.startswith(".git/") and f not in (".gitignore", "profiles.toml")
    }

    assert only_git == set(), f"Files in git but not rsync: {only_git}"
    assert only_rsync == set(), f"Files in rsync but not git: {only_rsync}"
