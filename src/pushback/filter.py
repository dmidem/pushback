"""Build rsync filter rules from profiles and gitignore files."""

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast


@dataclass(frozen=True)
class GitignorePattern:
    """Parsed gitignore pattern with semantic information."""

    original: str
    pattern: str
    negated: bool
    anchored: bool
    dir_only: bool


def _unescape(text: str) -> str:
    """Remove backslash escapes from string."""
    result = []
    skip_next = False

    for i, char in enumerate(text):
        if skip_next:
            skip_next = False
            continue
        if char == "\\" and i + 1 < len(text):
            result.append(text[i + 1])
            skip_next = True
        else:
            result.append(char)

    return "".join(result)


def _parse_gitignore_line(line: str) -> GitignorePattern | None:
    """Parse a single .gitignore line into a pattern object."""
    line = line.rstrip("\n\r")
    stripped = line.strip()

    # Skip blank lines and comments
    if not stripped or (stripped.startswith("#") and not line.lstrip().startswith("\\#")):
        return None

    # Extract negation flag
    negated = line.startswith("!") and not line.startswith("\\!")
    if negated:
        line = line[1:]

    # Unescape and check for dir-only marker
    line = _unescape(line)
    dir_only = line.endswith("/")
    if dir_only:
        line = line[:-1]

    # Check for root anchoring
    anchored = line.startswith("/")
    if anchored:
        line = line[1:]

    if not line:
        return None

    return GitignorePattern(
        original=stripped,
        pattern=line,
        negated=negated,
        anchored=anchored,
        dir_only=dir_only,
    )


def convert_gitignore_to_rsync(lines: list[str], base: str = "") -> list[str]:
    """Convert gitignore patterns to rsync filter rules."""
    # Parse and reverse (git last-wins → rsync first-wins)
    patterns = [p for line in lines if (p := _parse_gitignore_line(line))]
    patterns.reverse()

    rules = []
    base_prefix = ("/" + base.strip("/")) if base and base != "." else ""

    for p in patterns:
        # Build pattern path
        if p.anchored:
            path = "/" + p.pattern
        elif "/" in p.pattern:
            path = "/" + p.pattern
        else:
            path = "**/" + p.pattern

        if p.dir_only and not path.endswith("/"):
            path += "/"

        # Apply base path
        if base_prefix:
            path = base_prefix + ("/" if not path.startswith("/") else "") + path.lstrip("./")

        # Add include/exclude prefix
        rules.append(("+ " if p.negated else "- ") + path)

    return rules


def _load_profiles(path: Path) -> dict[str, Any]:
    """Load profiles from TOML file."""
    if not path.exists():
        raise FileNotFoundError(f"Profiles file not found: {path}")

    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return cast(dict[str, Any], data.get("profile", {}))


def _matches_detection_rules(rules: dict, root: Path) -> bool:
    """Check if profile detection rules match the project."""
    if "any_of" in rules:
        return any(list(root.glob(pattern)) for pattern in rules["any_of"])

    if "all_of" in rules:
        return all(list(root.glob(pattern)) for pattern in rules["all_of"])

    return False


def build_merge_filter(
    project_root: Path,
    profiles_path: Path,
    include_backupignore: bool = True,
    include_gitignore: bool = False,
    autodetect_profiles: bool = True,
) -> tuple[list[str], list[str]]:
    """Build complete rsync filter from profiles and ignore files."""
    profiles = _load_profiles(profiles_path)

    # Select active profiles
    active = []
    for name, config in profiles.items():
        if config.get("always", False):
            active.append(name)
        elif autodetect_profiles and "detect" in config:
            if _matches_detection_rules(config["detect"], project_root):
                active.append(name)

    # Collect patterns from all sources
    patterns = []

    for profile_name in active:
        patterns.extend(profiles[profile_name].get("ignore", []))

    for filename, should_include in [
        (".backupignore", include_backupignore),
        (".gitignore", include_gitignore),
    ]:
        if should_include and (file := project_root / filename).exists():
            patterns.extend(file.read_text(encoding="utf-8").splitlines(keepends=True))

    return convert_gitignore_to_rsync(patterns), active
