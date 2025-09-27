"""Remote server operations via SSH."""

import shlex
import subprocess
from pathlib import Path


class RemoteManager:
    """Manage remote server operations"""

    def __init__(self, multiplex: bool = True):
        """Initialize remote manager"""
        self.multiplex = multiplex

    def ssh_opts(self, port: int) -> list[str]:
        """Build SSH options"""
        if not self.multiplex:
            return ["-p", str(port)]

        control_path = str(Path.home() / ".ssh/pushback-%r@%h-%p")
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

    def run_ssh(self, user: str, host: str, port: int, script: str) -> subprocess.CompletedProcess:
        """Run SSH command"""
        cmd = ["ssh", *self.ssh_opts(port), f"{user}@{host}", script]
        return subprocess.run(cmd, check=False, capture_output=True, text=True)

    def test_dir(self, user: str, host: str, port: int, path: str) -> bool:
        """Test if remote directory exists"""
        is_tilde, rest = self._split_remote_base(path)
        if is_tilde:
            target = rest if rest else "."
            script = f"cd ~ && test -d {self._quote(target)} && echo OK || echo MISSING"
        else:
            script = f"test -d {self._quote(path)} && echo OK || echo MISSING"

        try:
            result = self.run_ssh(user, host, port, script)
            return "OK" in (result.stdout or "")
        except Exception:
            return False

    def list_siblings(self, user: str, host: str, port: int, base: str, prefix: str) -> list[str]:
        """List sibling directories with given prefix"""
        is_tilde, rest = self._split_remote_base(base)
        if is_tilde:
            base_dir = (rest.rstrip("/") + "/") if rest else ""
            script = (
                f"cd ~ && ls -1d "
                f"{self._quote(base_dir + prefix + '_')}* 2>/dev/null | "
                f"xargs -n1 basename 2>/dev/null || true"
            )
        else:
            script = (
                f"ls -1d "
                f"{self._quote(base.rstrip('/') + '/' + prefix + '_')}* "
                f"2>/dev/null | xargs -n1 basename 2>/dev/null || true"
            )

        try:
            result = self.run_ssh(user, host, port, script)
            if result.returncode != 0 and not (result.stdout or "").strip():
                return []
            return [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
        except Exception:
            return []

    def list_all(self, user: str, host: str, port: int, base: str) -> list[str]:
        """List all directories in base"""
        is_tilde, rest = self._split_remote_base(base)
        if is_tilde:
            target = rest.rstrip("/") if rest else "."
            script = f"cd ~ && ls -1 {self._quote(target)} 2>/dev/null || true"
        else:
            script = f"ls -1 {self._quote(base.rstrip('/'))} 2>/dev/null || true"

        try:
            result = self.run_ssh(user, host, port, script)
            if result.returncode != 0 and not (result.stdout or "").strip():
                return []
            return [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
        except Exception:
            return []

    def list_backups(self, server_name: str, server_config: dict, name_filter: str) -> int:
        """List remote backups"""
        user = server_config["USER"]
        host = server_config["HOST"]
        base = server_config["BASE"]
        port = int(server_config["PORT"])

        if not self.test_dir(user, host, port, base):
            print(
                f"Error: remote base does not exist on {server_name}: {base}",
                file=__import__("sys").stderr,
            )
            return 2

        if name_filter:
            items = self.list_siblings(user, host, port, base, name_filter)
        else:
            items = self.list_all(user, host, port, base)
            items = [x for x in items if "_" in x]

        if not items:
            print(f"(no backups found on {server_name})")
            return 0

        filter_text = f" (filtered by {name_filter})" if name_filter else ""
        print(f"Backups on {server_name} ({user}@{host}:{base}){filter_text}:")
        for item in sorted(items):
            print("  -", item)
        return 0

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
