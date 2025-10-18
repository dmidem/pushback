#!/usr/bin/env python3

"""Development task runner for pushback."""

import inspect
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from collections.abc import Callable, Mapping
from pathlib import Path
from textwrap import dedent
from typing import NoReturn

# Expected project name (validated against pyproject.toml on startup)
PROJECT_NAME = "pushback"

DIST = Path("dist")
META_FILE = Path(f"src/{PROJECT_NAME}/_meta.py")
DEV_SCRIPT_FILE = Path(__file__).name if "__file__" in globals() else "python"
DEV_SCRIPT = Path(sys.argv[0]).name if sys.argv[0] else DEV_SCRIPT_FILE
DEV_SCRIPT_REAL_FILE = Path(os.path.realpath(__file__)).name

# Global project config loaded in main()
project_config: dict = {}


def esc(s: str | None) -> str:
    """JSON-escape a string (quotes/newlines, etc.), without the surrounding quotes."""
    return json.dumps(s or "")[1:-1]


def fail(msg: str, code: int = 1) -> NoReturn:
    """Print an error and exit with the given status."""
    print(f"Error: {msg}", file=sys.stderr)
    sys.exit(code)


def load_project_config() -> dict:
    """Load pyproject.toml and validate we're in project root with correct package."""
    if not Path("pyproject.toml").exists():
        fail(
            "pyproject.toml not found in current directory. "
            f"Run {DEV_SCRIPT} from project root only."
        )

    config = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    actual_name = config.get("project", {}).get("name", "")

    if actual_name != PROJECT_NAME:
        fail(f"pyproject.toml defines project.name='{actual_name}' but '{PROJECT_NAME}' expected")

    return config


def run(*args: str, cwd: Path | None = None) -> int:
    """Run a command and return its exit code."""
    print(f"+ {' '.join(args)}", file=sys.stderr)
    return subprocess.run(args, cwd=cwd).returncode


def run_checked(*args: str, cwd: Path | None = None) -> None:
    """Run a command and exits if it fails."""
    rc = run(*args, cwd=cwd)
    if rc != 0:
        fail(f"command failed ({rc}): {' '.join(args)}")


def _get_min_python() -> str:
    """Gets lowest MAJOR.MINOR from a spec like '>=3.11,<4,!=3.12.*' (best effort)."""
    spec = (project_config.get("project") or {}).get("requires-python") or ""
    if spec:
        for clause in (c.strip() for c in spec.split(",")):
            if clause.startswith(">=") or clause.startswith("=="):
                ver = clause[2:].strip()  # drop operator
                parts = ver.split(".")
                if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
                    return f"{parts[0]}.{parts[1]}"
                break
    return "3.8"


def build_meta_content() -> str:
    """Build the content of project metadata file."""
    project = project_config.get("project") or {}
    description = project.get("description") or ""
    version = str(project.get("version") or "")

    license = project.get("license")
    license_text = ""
    if isinstance(license, str):
        license_text = license
    elif isinstance(license, dict):
        if "text" in license:
            license_text = license.get("text") or ""
        elif "file" in license:
            try:
                license_text = Path(license["file"]).read_text(encoding="utf-8")
            except Exception:
                pass

    urls = project.get("urls") or {}
    homepage = urls.get("Homepage") or urls.get("Documentation") or urls.get("Repository") or ""

    return dedent(f"""\
        # Auto-generated from pyproject.toml by `{DEV_SCRIPT_REAL_FILE} emit-meta` - do not edit manually.

        APP_NAME = "{esc(PROJECT_NAME)}"
        APP_DESCRIPTION = "{esc(description)}"
        VERSION = "{esc(version)}"
        LICENSE = "{esc(license_text)}"
        HOMEPAGE = "{esc(homepage)}"
        MIN_PYTHON = "{esc(_get_min_python())}"
        """)  # noqa


def emit_meta():
    """Generate src/pushback/_meta.py from pyproject.toml."""
    content = build_meta_content()
    META_FILE.parent.mkdir(parents=True, exist_ok=True)
    META_FILE.write_text(content, encoding="utf-8")
    print(f"✓ Generated {META_FILE}", file=sys.stderr)
    return 0


def check_meta():
    """Check that _meta.py is in sync with pyproject.toml."""
    if not META_FILE.exists():
        print(f"ERROR: {META_FILE} does not exist. Run `{DEV_SCRIPT} emit-meta`", file=sys.stderr)
        return 1

    expected = build_meta_content()
    actual = META_FILE.read_text(encoding="utf-8")

    if actual != expected:
        print(
            f"ERROR: {META_FILE} is out of sync with pyproject.toml. Run: `{DEV_SCRIPT} emit-meta`",
            file=sys.stderr,
        )
        return 1

    print(f"✓ {META_FILE} is in sync", file=sys.stderr)
    return 0


def fix():
    """Format + auto-fix"""
    return run("uv", "run", "ruff", "format", "src/", "tests/", "scripts/") or run(
        "uv", "run", "ruff", "check", "--fix", "src/", "tests/", "scripts/"
    )


def test_slow() -> int:
    """Run only slow tests"""
    return run("uv", "run", "pytest", f"--cov={PROJECT_NAME}", "--cov-report=xml", "-m", "slow")


def check() -> int:
    """Format check + lint + typecheck + test (exclude slow tests)"""
    hint = ""

    if check_meta() != 0:
        rc = 1
    else:
        mypy_version = _get_min_python()

        rc = run("uv", "run", "ruff", "format", "--check", "src/", "tests/", "scripts/") or run(
            "uv", "run", "ruff", "check", "src/", "tests/", "scripts/"
        )

        if rc != 0:
            hint = f" (try to run `{DEV_SCRIPT} fix`)"
        else:
            rc = run(
                "uv",
                "run",
                "mypy",
                f"--python-version={mypy_version}",
                "src/",
                "tests/",
                "scripts/",
            ) or run(
                "uv",
                "run",
                "pytest",
                f"--cov={PROJECT_NAME}",
                "--cov-report=xml",
                "-m",
                "not slow",
            )

    if rc != 0:
        print(f"\n✗ Checks failed{hint}.", file=sys.stderr)
        return rc

    print("\n✓ All checks passed!", file=sys.stderr)
    return 0


def check_all() -> int:
    """Run full checks (including slow tests)."""
    rc = check()
    if rc != 0:
        return rc
    return test_slow()


def inspect_built_artifacts(
    dist_dir: Path,
    *,
    sdist_glob: str = "*.tar.gz",
    wheel_glob: str = "*.whl",
    sdist_max_files: int = 20,
    wheel_exts: tuple[str, ...] = (".py", ".toml"),
) -> None:
    """Pretty-print a quick listing of sdist and wheel contents (cross-platform)."""
    print("\n--- Inspecting built artifacts ---\n", file=sys.stderr)

    sdist = next(dist_dir.glob(sdist_glob), None)
    if sdist:
        print(f"--- {sdist.name} (first {sdist_max_files} files) ---", file=sys.stderr)
        try:
            with tarfile.open(sdist, "r:gz") as tf:
                for name in tf.getnames()[:sdist_max_files]:
                    print(name)
        except tarfile.TarError as exc:
            print(f"(tar inspect skipped: {exc})", file=sys.stderr)
        print()

    wheel = next(dist_dir.glob(wheel_glob), None)
    if wheel:
        readable_exts = " & ".join(ext.lstrip(".") for ext in wheel_exts)
        print(f"--- {wheel.name} ({readable_exts} files) ---", file=sys.stderr)
        try:
            with zipfile.ZipFile(wheel) as zf:
                for info in zf.infolist():
                    if info.filename.endswith(wheel_exts):
                        print(f"{info.file_size:>8}  {info.filename}")
        except zipfile.BadZipFile as exc:
            print(f"(zip inspect skipped: {exc})", file=sys.stderr)
        print()


def build():
    """Build wheel, sdist, and zipapp"""
    if check_meta() != 0:
        return 1

    if DIST.exists():
        print("Cleaning dist/...", file=sys.stderr)
        shutil.rmtree(DIST)

    DIST.mkdir(parents=True, exist_ok=True)

    try:
        run_checked("uv", "build")
        run_checked(
            "uv",
            "run",
            "python",
            "-m",
            "zipapp",
            "src",
            "-o",
            f"dist/{PROJECT_NAME}.pyz",
            "-m",
            f"{PROJECT_NAME}.cli:main",
            "-p",
            "/usr/bin/env python3",
            "-c",
        )
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1

    (DIST / f"{PROJECT_NAME}.cmd").write_text(
        f'@echo off\r\npy "%~dp0{PROJECT_NAME}.pyz" %*\r\n', encoding="utf-8"
    )

    inspect_built_artifacts(DIST)
    return 0


def _zip_add_dir(z: zipfile.ZipFile, root: Path, arc_prefix: str = "docs") -> None:
    if not root.exists():
        return
    for path in root.rglob("*"):
        if path.is_file():
            z.write(path, f"{arc_prefix}/{path.relative_to(root).as_posix()}")


def package_binary(dist: Path, version: str) -> list[Path]:
    """
    Create per-OS archives with exec bit preserved on Unix, include README/LICENSE(s)+docs/,
    and delete the raw binary after packaging.
    """
    sysname = platform.system().lower()
    produced: list[Path] = []
    extras = [
        path
        for path in (Path("LICENSE-MIT"), Path("LICENSE-APACHE"), Path("README.md"))
        if path.exists()
    ]
    docs = Path("docs")

    if sysname == "windows":
        bin_name = f"{PROJECT_NAME}.exe"
        bin_path = dist / bin_name
        if not bin_path.exists():
            fail(f"PyInstaller binary not found: {bin_path}")
        arch = "windows-x86_64"

        archive = dist / f"{PROJECT_NAME}-{arch}-v{version}.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(bin_path, bin_name)
            for extra in extras:
                zf.write(extra, extra.name)
            _zip_add_dir(zf, docs, arc_prefix="docs")

        produced.append(archive)
        bin_path.unlink(missing_ok=True)
    else:
        bin_name = PROJECT_NAME
        bin_path = dist / bin_name
        if not bin_path.exists():
            fail(f"PyInstaller binary not found: {bin_path}")
        arch = "linux-x86_64" if sysname == "linux" else "macos-universal2"

        archive = dist / f"{PROJECT_NAME}-{arch}-v{version}.tar.gz"
        with tarfile.open(archive, "w:gz") as tf:
            tf.add(bin_path, arcname=bin_name)
            for extra in extras:
                tf.add(extra, arcname=extra.name)
            if docs.exists():
                tf.add(docs, arcname="docs")

        produced.append(archive)
        bin_path.unlink(missing_ok=True)

    return produced


def build_standalone():
    """Build a standalone executable using PyInstaller."""
    if check_meta() != 0:
        return 1

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("Error: PyInstaller not found. Install via `uv sync --extra dev`.", file=sys.stderr)
        return 1

    build_dir = Path("build")
    if build_dir.exists():
        shutil.rmtree(build_dir)
    build_dir.mkdir()
    DIST.mkdir(parents=True, exist_ok=True)

    sep = ";" if os.name == "nt" else ":"
    data_args: list[str] = []
    for name in ("config.toml", "profiles.toml"):
        embedded = Path(f"src/{PROJECT_NAME}/_embedded/{name}").resolve()
        if embedded.exists():
            data_args.extend(["--add-data", f"{embedded}{sep}{PROJECT_NAME}/_embedded"])

    cmd = [
        "pyinstaller",
        "-F",
        "-n",
        PROJECT_NAME,
        "--specpath",
        str(build_dir),
        *data_args,
        str(Path(f"src/{PROJECT_NAME}/__main__.py").resolve()),
    ]

    try:
        run_checked(*cmd)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1

    system = platform.system().lower()
    bin_name = f"{PROJECT_NAME}.exe" if system == "windows" else PROJECT_NAME
    bin_path = DIST / bin_name
    if not bin_path.exists():
        print(f"Error: PyInstaller output not found: {bin_path}", file=sys.stderr)
        return 1

    if system != "windows":
        bin_path.chmod(0o755)

    size_mb = bin_path.stat().st_size / 1024 / 1024
    print(f"\n✓ Created: {bin_path} ({size_mb:.2f} MB)", file=sys.stderr)

    project = project_config.get("project") or {}
    version = str(project.get("version") or "")
    try:
        archives = package_binary(DIST, version)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1

    for archive in archives:
        print(f"✓ Packaged: {archive}", file=sys.stderr)

    return 0


def clean():
    """Remove build artifacts"""
    patterns = [
        "dist",
        "build",
        "*.egg-info",
        "**/__pycache__",
        "**/*.pyc",
        ".cache",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".coverage_cache",
        ".coverage",
        "coverage.xml",
        "htmlcov",
    ]

    to_remove: set[Path] = set()
    for pattern in patterns:
        to_remove.update(Path(".").glob(pattern))

    # Sort so files are removed before their parent directories
    for path in sorted(to_remove, key=lambda p: (p.is_dir(), len(p.as_posix())), reverse=True):
        if not path.exists():
            continue
        if path.is_dir():
            print(f"Removing {path}/", file=sys.stderr)
            shutil.rmtree(path)
        else:
            print(f"Removing {path}", file=sys.stderr)
            path.unlink()

    return 0


Task = Callable[[], int]


def print_usage(tasks: Mapping[str, Task]) -> None:
    names = "|".join(sorted(tasks))
    print(f"Usage: {DEV_SCRIPT} {{{names}}}", file=sys.stderr)

    width = max(len(name) for name in tasks) + 2
    for name in tasks:
        func = tasks[name]
        doc = inspect.getdoc(func) or ""
        first = doc.strip().splitlines()[0] if doc else ""
        if first:
            print(f"  {name:<{width}}{first}", file=sys.stderr)

    print(
        "\nRun from the project root folder, i.e. where pyproject.toml is located!\n",
        file=sys.stderr,
    )


def main() -> int:
    global project_config
    project_config = load_project_config()

    tasks: dict[str, Task] = {
        "emit-meta": emit_meta,
        "check-meta": check_meta,
        "fix": fix,
        "check": check,
        "test-slow": test_slow,
        "check-all": check_all,
        "build": build,
        "build-standalone": build_standalone,
        "clean": clean,
    }

    if len(sys.argv) < 2 or sys.argv[1] in {"-h", "--help", "help"}:
        print_usage(tasks)
        return 0 if len(sys.argv) >= 2 else 1

    task = sys.argv[1]

    if task not in tasks:
        print(f"Unknown task: {task}", file=sys.stderr)
        print(f"Available: {', '.join(tasks)}", file=sys.stderr)
        return 1

    return tasks[task]()


if __name__ == "__main__":
    sys.exit(main())
