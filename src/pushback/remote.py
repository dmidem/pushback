"""Remote server operations via SSH."""

import shlex
import subprocess
from collections.abc import Mapping
from pathlib import Path

from . import APP_NAME


class RemoteManager:
    """Manage remote server operations"""

    def __init__(self, ssh_multiplex: bool = True):
        """Initialize remote manager"""
        self.ssh_multiplex = ssh_multiplex

    def ssh_opts(self, port: int) -> list[str]:
        """Build SSH options"""
        if not self.ssh_multiplex:
            return ["-p", str(port)]

        control_path = str(Path.home() / f".ssh/{APP_NAME}-%r@%h-%p")
        return [
            "-p",
            str(port),
            "-o",
            "ControlMaster=auto",
            "-o",
            f"ControlPath={control_path}",
            "-o",
            "ControlPersist=60",
        ]

    def run_ssh(self, user: str, host: str, port: int, script: str) -> str:
        """Run SSH command"""
        cmd = ["ssh", *self.ssh_opts(port), f"{user}@{host}", script]
        try:
            return subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
        except FileNotFoundError as exc:
            raise RuntimeError("SSH client not found, install and ensure it is in PATH.") from exc
        except subprocess.CalledProcessError as exc:
            msg = (exc.output or "").strip() or f"ssh exited with code {exc.returncode}"
            raise RuntimeError(msg) from exc

    def test_dir(self, user: str, host: str, port: int, path: str) -> bool:
        """Test if remote directory exists"""
        is_tilde, rest = self._split_remote_base(path)
        if is_tilde:
            target = rest if rest else "."
            script = f"cd ~ && test -d {self._quote(target)} && echo OK || echo MISSING"
        else:
            script = f"test -d {self._quote(path)} && echo OK || echo MISSING"
        return "OK" in (self.run_ssh(user, host, port, script) or "")

    def list_by_script(self, user: str, host: str, port: int, script: str) -> list[str]:
        """List directories using with given script"""
        result = self.run_ssh(user, host, port, script)
        return [line.strip() for line in (result or "").splitlines() if line.strip()]

    def list_siblings(self, user: str, host: str, port: int, base: str, prefix: str) -> list[str]:
        """List sibling directories with given prefix"""
        is_tilde, rest = self._split_remote_base(base)

        if is_tilde:
            base_dir = (rest.rstrip("/") + "/") if rest else ""
            cd_prefix = "cd ~ && "
            search_path = base_dir
        else:
            cd_prefix = ""
            search_path = base.rstrip("/") + "/"

        script = (
            f"{cd_prefix}"
            f"find {self._quote(search_path.rstrip('/'))} -maxdepth 1 -type d "
            f"-name {self._quote(prefix + '_*')} -print0 2>/dev/null | "
            f"xargs -0 -n1 basename 2>/dev/null || true"
        )
        return self.list_by_script(user, host, port, script)

    def list_all(self, user: str, host: str, port: int, base: str) -> list[str]:
        """List all directories in base"""
        is_tilde, rest = self._split_remote_base(base)

        if is_tilde:
            cd_prefix = "cd ~ && "
            search_path = rest.rstrip("/") if rest else "."
        else:
            cd_prefix = ""
            search_path = base.rstrip("/")

        script = (
            f"{cd_prefix}"
            f"find {self._quote(search_path)} -maxdepth 1 -type d ! -name '.' "
            f"-print0 2>/dev/null | "
            f"xargs -0 -n1 basename 2>/dev/null || true"
        )
        return self.list_by_script(user, host, port, script)

    def list_backups(self, server_name: str, server_config, name_filter: str) -> list[str]:
        """List remote backups"""
        user, host, port, base = self._unpack_server_config(server_name, server_config)

        if not self.test_dir(user, host, port, base):
            raise RuntimeError(f"remote base does not exist on {server_name}: {base}")

        if name_filter:
            items = self.list_siblings(user, host, port, base, name_filter)
        else:
            items = self.list_all(user, host, port, base)
            items = [x for x in items if "_" in x]

        return items

    def find_existing_snapshot(
        self, siblings: list[str], base_name: str, time_suffix: str
    ) -> str | None:
        """Find existing snapshot that matches time suffix"""
        if not time_suffix:
            exact = f"{base_name}_"
            for sibling in siblings:
                if sibling.startswith(exact) and len(sibling) > len(exact):
                    return sibling
            return None

        target = f"{base_name}{time_suffix}"
        for sibling in siblings:
            if sibling.startswith(target):
                return sibling
        return None

    @staticmethod
    def _split_remote_base(base: str) -> tuple[bool, str]:
        """Returns (is_tilde_path, rest_of_path)"""
        if base == "~":
            return True, ""
        if base.startswith("~/"):
            return True, base[2:]
        return False, base

    @staticmethod
    def _quote(s: str) -> str:
        """Shell-quote string"""
        return shlex.quote(s)

    @staticmethod
    def _unpack_server_config(server_name: str, server_config) -> tuple[str, str, int, str]:
        """Normalise server configuration into primitives."""
        if hasattr(server_config, "user"):
            user = getattr(server_config, "user")
            host = getattr(server_config, "host")
            port = getattr(server_config, "port", 22)
            base = getattr(server_config, "base")
        elif isinstance(server_config, Mapping):
            try:
                user = server_config["user"]
                host = server_config["host"]
                base = server_config["base"]
            except KeyError as missing:
                raise KeyError(f"Server '{server_name}' missing field: {missing.args[0]}") from None
            port = server_config.get("port", 22)
        else:
            raise TypeError(
                "Unsupported server configuration type for "
                f"'{server_name}': {type(server_config)!r}"
            )

        try:
            port_int = int(port)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Server '{server_name}' has invalid port value: {port!r}") from exc

        return str(user), str(host), port_int, str(base)
