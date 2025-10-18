"""Configuration loading and management."""

import hashlib
import os
import sys
import tomllib
from dataclasses import dataclass
from datetime import datetime
from importlib import resources
from pathlib import Path
from typing import TypedDict

from . import APP_NAME


class OptionsDict(TypedDict):
    """Type hints for configuration options."""

    delete_remote: bool
    profiles_file: str
    snapshot_mode: str
    snapshot_custom_hours: int
    include_backupignore: bool
    include_gitignore: bool
    autodetect_profiles: bool


class ServerEntry(TypedDict):
    """Server definition as loaded from TOML."""

    user: str
    host: str
    port: int
    base: str
    default: bool


@dataclass(frozen=True, slots=True)
class SyncParams:
    """Computed sync parameters for a project root."""

    root: Path
    canonical_path: str
    folder_name: str
    suffix: str
    snapshot_mode: str
    snapshot_custom_hours: int
    time_suffix: str


def default_config_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")
        return Path(base) / APP_NAME
    xdg = os.environ.get("XDG_CONFIG_HOME")
    return (Path(xdg) if xdg else Path.home() / ".config") / APP_NAME


DEFAULT_CONFIG_DIR = default_config_dir()
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "config.toml"
DEFAULT_PROFILES_PATH = DEFAULT_CONFIG_DIR / "profiles.toml"


DEFAULT_OPTIONS: OptionsDict = {
    "delete_remote": False,
    "profiles_file": str(DEFAULT_PROFILES_PATH),
    "snapshot_mode": "none",
    "snapshot_custom_hours": 24,
    "include_backupignore": True,
    "include_gitignore": False,
    "autodetect_profiles": True,
}


def _get_embedded_file(filename: str) -> str:
    """Get embedded default file content"""
    try:
        import pushback._embedded

        return resources.read_text(pushback._embedded, filename, encoding="utf-8")
    except Exception:
        if filename == "config.toml":
            return _minimal_config()
        if filename == "profiles.toml":
            return _minimal_profiles()
        return ""


def _minimal_config() -> str:
    """Minimal fallback config"""
    return f"""\
[options]
delete_remote = false
profiles_file = "~/.config/{APP_NAME}/profiles.toml"
snapshot_mode = "none"
snapshot_custom_hours = 24
include_backupignore = true
include_gitignore = false
autodetect_profiles = true

[[server]]
name = "main"
user = "your_user"
host = "your.host.example"
port = 22
base = "~/{APP_NAME}"
default = true
"""


def _minimal_profiles() -> str:
    """Minimal fallback profiles"""
    return """\
[profile.safe_defaults]
always = true
notes = "Safe defaults"
ignore = [".git/", ".DS_Store"]
"""


class Config:
    """Configuration manager"""

    def __init__(self, config_path: str | None = None):
        """Initialize configuration"""
        self.path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
        self.servers: dict[str, ServerEntry] = {}
        self.options: OptionsDict = DEFAULT_OPTIONS.copy()
        self.profiles_path = Path()

    def exists(self) -> bool:
        """Check if config file exists"""
        return self.path.exists()

    def create_default(self, force: bool = False, auto: bool = False):
        """
        Create default configuration files

        Args:
            force: Overwrite existing files
            auto: Auto-create without prompts (first-run behavior)
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)

        profiles_path = Path(DEFAULT_OPTIONS["profiles_file"]).expanduser()
        profiles_path.parent.mkdir(parents=True, exist_ok=True)

        if self.path.exists() and not force:
            if not auto:
                print(f"Config already exists: {self.path}")
                print("Use --force-all to overwrite")
        else:
            config_content = _get_embedded_file("config.toml")
            self.path.write_text(config_content, encoding="utf-8")
            if not auto:
                print(f"Created config: {self.path}")

        if profiles_path.exists() and not force:
            if not auto:
                print(f"Profiles already exist: {profiles_path}")
        else:
            profiles_content = _get_embedded_file("profiles.toml")
            profiles_path.write_text(profiles_content, encoding="utf-8")
            if not auto:
                print(f"Created profiles: {profiles_path}")

        if not auto:
            print(f"\nEdit these files to configure {APP_NAME}:")
            print(f"  Config:   {self.path}")
            print(f"  Profiles: {profiles_path}")

    def ensure_initialized(self):
        """Auto-create config on first run if missing"""
        if not self.path.exists():
            profiles_path = Path(DEFAULT_OPTIONS["profiles_file"]).expanduser()
            if not profiles_path.exists():
                print("First run detected. Creating default configuration...")
                self.create_default(auto=True)
                print()

    def load(self):
        """Load configuration from TOML file"""
        self.ensure_initialized()

        try:
            content = self.path.read_text(encoding="utf-8")
            data = tomllib.loads(content)
        except FileNotFoundError:
            raise ValueError(f"Config file not found: {self.path}") from None
        except tomllib.TOMLDecodeError as exc:
            raise ValueError(f"Invalid TOML in config: {exc}") from None

        if "options" in data:
            self.options = self._parse_options(data["options"])

        if "server" not in data:
            raise ValueError("No servers defined in config")

        self.servers = {}
        for server in data["server"]:
            name = server.get("name")
            if not name:
                raise ValueError("Server missing 'name' field")

            for field in ("user", "host", "base"):
                if field not in server:
                    raise ValueError(f"Server '{name}' missing required field: {field}")

            try:
                port = int(server.get("port", 22))
            except (TypeError, ValueError):
                raise ValueError(
                    f"Server '{name}' has invalid port: {server.get('port')!r}"
                ) from None

            self.servers[name] = {
                "user": str(server["user"]),
                "host": str(server["host"]),
                "port": port,
                "base": str(server["base"]),
                "default": bool(server.get("default", False)),
            }

        if not any(s["default"] for s in self.servers.values()):
            raise ValueError("At least one server must have default = true")

        profiles_file = self.options["profiles_file"]
        self.profiles_path = Path(profiles_file).expanduser()

    def list_servers(self):
        """Print configured servers"""
        if not self.servers:
            print("No servers configured.")
            return

        print("Configured servers:")
        for name, cfg in self.servers.items():
            host = cfg["host"]
            user = cfg["user"]
            port = cfg["port"]
            base = cfg["base"]
            default_str = " (default)" if cfg["default"] else ""
            print(f"  {name}: {user}@{host}:{port} -> {base}{default_str}")

    def select_servers(self, server_arg: str | None) -> dict[str, ServerEntry]:
        """Select which servers to use"""
        if server_arg:
            requested = [s.strip() for s in server_arg.split(",") if s.strip()]
            selected: dict[str, ServerEntry] = {}
            for server_name in requested:
                if server_name in self.servers:
                    selected[server_name] = self.servers[server_name]
                else:
                    print(f"Error: server '{server_name}' not found", file=sys.stderr)
                    print(f"Available: {', '.join(self.servers.keys())}", file=sys.stderr)
                    return {}
            return selected

        return {name: cfg for name, cfg in self.servers.items() if cfg["default"]}

    def prepare_sync_params(self, root: Path, args) -> SyncParams:
        """Prepare parameters for syncing"""
        canonical_path = str(root)
        folder_name = root.name or "folder"
        suffix = hashlib.sha1(canonical_path.encode("utf-8")).hexdigest()[:8]

        snapshot_mode = args.snapshot_mode or self.options["snapshot_mode"]
        snapshot_custom_hours = args.snapshot_custom_hours or self.options["snapshot_custom_hours"]

        time_suffix = self._get_time_suffix(snapshot_mode, snapshot_custom_hours)

        return SyncParams(
            root=root,
            canonical_path=canonical_path,
            folder_name=folder_name,
            suffix=suffix,
            snapshot_mode=snapshot_mode,
            snapshot_custom_hours=snapshot_custom_hours,
            time_suffix=time_suffix,
        )

    def _parse_options(self, opts: dict) -> OptionsDict:
        """Parse options from TOML data with type conversion."""
        return {
            "delete_remote": bool(opts.get("delete_remote", DEFAULT_OPTIONS["delete_remote"])),
            "profiles_file": str(opts.get("profiles_file", DEFAULT_OPTIONS["profiles_file"])),
            "snapshot_mode": str(opts.get("snapshot_mode", DEFAULT_OPTIONS["snapshot_mode"])),
            "snapshot_custom_hours": int(
                opts.get("snapshot_custom_hours", DEFAULT_OPTIONS["snapshot_custom_hours"])
            ),
            "include_backupignore": bool(
                opts.get("include_backupignore", DEFAULT_OPTIONS["include_backupignore"])
            ),
            "include_gitignore": bool(
                opts.get("include_gitignore", DEFAULT_OPTIONS["include_gitignore"])
            ),
            "autodetect_profiles": bool(
                opts.get("autodetect_profiles", DEFAULT_OPTIONS["autodetect_profiles"])
            ),
        }

    def _get_time_suffix(self, mode: str, custom_hours: int) -> str:
        """Generate time suffix based on snapshot mode"""
        now = datetime.now()

        if mode == "none":
            return ""
        if mode == "yearly":
            return f"_{now.year}"
        if mode == "monthly":
            return f"_{now.year}-{now.month:02d}"
        if mode == "weekly":
            year, week, _ = now.isocalendar()
            return f"_{year}W{week:02d}"
        if mode == "daily":
            return f"_{now.year}-{now.month:02d}-{now.day:02d}"
        if mode == "hourly":
            return f"_{now.year}-{now.month:02d}-{now.day:02d}H{now.hour:02d}"
        if mode == "custom":
            hours_since_epoch = int(now.timestamp()) // 3600
            interval_number = hours_since_epoch // custom_hours
            return f"_I{interval_number}"
        return ""
