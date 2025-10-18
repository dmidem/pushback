from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).with_name("e2e-test.sh")


def _require_docker() -> None:
    """Fail the test (not skip) with a helpful message if Docker is unavailable."""
    if not shutil.which("docker"):
        pytest.fail(
            "Docker CLI not found on PATH. "
            "Install Docker and ensure the 'docker' command is available."
        )

    try:
        subprocess.run(
            ["docker", "info"],
            check=True,
            capture_output=True,  # UP022-compliant
            text=True,
        )
    except subprocess.CalledProcessError as e:
        msg = [
            "Docker is installed but 'docker info' failed.",
            "Common causes: Docker daemon not running or insufficient permissions.",
            f"Exit code: {e.returncode}",
        ]
        if e.stderr:
            msg.append("stderr:\n" + e.stderr.strip())
        elif e.stdout:
            msg.append("stdout:\n" + e.stdout.strip())
        pytest.fail("\n".join(msg))


pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(not SCRIPT.exists(), reason="e2e-test.sh not found"),
]


def test_e2e(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    _require_docker()

    try:
        SCRIPT.chmod(SCRIPT.stat().st_mode | 0o111)
    except Exception:
        pass

    env = {**os.environ, "WORKDIR": str(tmp_path)}

    # Cross-platform live output: disable pytest capture and inherit stdio
    with capsys.disabled():
        rc = subprocess.call(
            ["bash", str(SCRIPT)],
            cwd=SCRIPT.parent,
            env=env,
            stdout=None,
            stderr=None,
        )

    assert rc == 0
