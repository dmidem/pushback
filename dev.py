#!/usr/bin/env python3

"""Development task runner for pushback."""

import shutil
import subprocess
import sys
from pathlib import Path


def check_project_root():
    """Ensure we're running from project root."""
    if not Path("pyproject.toml").exists():
        print("Error: pyproject.toml not found in current directory", file=sys.stderr)
        print("Run dev.py from project root only.", file=sys.stderr)
        sys.exit(1)


def run(*args: str) -> int:
    """Run a command and return its exit code."""
    print(f"+ {' '.join(args)}", file=sys.stderr)
    return subprocess.run(args).returncode


def check():
    """Format check + lint + typecheck + test"""
    check_project_root()
    return (
        run("uv", "run", "ruff", "format", "--check", "src/", "tests/")
        or run("uv", "run", "ruff", "check", "src/", "tests/")
        or run("uv", "run", "mypy", "src/", "tests/")
        or run("uv", "run", "pytest", "--cov=pushback", "--cov-report=xml")
    )


def fix():
    """Format + auto-fix"""
    check_project_root()
    return run("uv", "run", "ruff", "format", "src/", "tests/") or run(
        "uv", "run", "ruff", "check", "--fix", "src/", "tests/"
    )


def build():
    """Build wheel, sdist, and zipapp"""
    check_project_root()

    # Clean dist safely
    if Path("dist").exists():
        print("Cleaning dist/...", file=sys.stderr)
        shutil.rmtree("dist")

    # Build with uv
    if run("uv", "build") != 0:
        return 1

    # Build zipapp
    if (
        run(
            "uv",
            "run",
            "python",
            "-m",
            "zipapp",
            "src",
            "-o",
            "dist/pushback.pyz",
            "-m",
            "pushback.cli:main",
            "-p", "/usr/bin/env python3",
            "-c",
        )
        != 0
    ):
        return 1

    # Inspect built artifacts
    print("\n--- Inspecting built artifacts ---\n", file=sys.stderr)

    # Check sdist contents
    sdist = next(Path("dist").glob("*.tar.gz"), None)
    if sdist and shutil.which("tar"):
        print(f"--- {sdist.name} (first 20 files) ---", file=sys.stderr)
        subprocess.run(["tar", "-tzf", str(sdist)], check=True)
        subprocess.run(["sh", "-c", f"tar -tzf {sdist} | head -20"], check=True)
        print()

    # Check wheel contents (.py and .toml files)
    wheel = next(Path("dist").glob("*.whl"), None)
    if wheel and shutil.which("unzip"):
        print(f"--- {wheel.name} (.py and .toml files) ---", file=sys.stderr)
        subprocess.run(["sh", "-c", f"unzip -l {wheel} | grep -E '\\.(py|toml)$'"], check=True)
        print()

    return 0


def clean():
    """Remove build artifacts"""
    check_project_root()

    patterns = [
        "dist",
        "build",
        "*.egg-info",
        "**/__pycache__",
        "**/*.pyc",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".coverage",
        "coverage.xml",
        "htmlcov",
    ]

    for pattern in patterns:
        for path in Path(".").glob(pattern):
            if path.is_dir():
                print(f"Removing {path}/", file=sys.stderr)
                shutil.rmtree(path)
            else:
                print(f"Removing {path}", file=sys.stderr)
                path.unlink()

    return 0


def main():
    if len(sys.argv) < 2:
        print("Usage: python dev.py {check|fix|build|clean}", file=sys.stderr)
        return 1

    task = sys.argv[1]
    tasks = {
        "check": check,
        "fix": fix,
        "build": build,
        "clean": clean,
    }

    if task not in tasks:
        print(f"Unknown task: {task}", file=sys.stderr)
        print(f"Available: {', '.join(tasks)}", file=sys.stderr)
        return 1

    return tasks[task]()


if __name__ == "__main__":
    sys.exit(main())
