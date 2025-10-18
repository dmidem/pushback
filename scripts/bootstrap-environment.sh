#!/usr/bin/env bash
set -euo pipefail

# install-os-deps.sh — ensure rsync + ssh are available on GitHub runners
# Works on: ubuntu-latest, macos-latest, windows-latest (via Chocolatey)

echo "==> Detecting OS…"
OS="${RUNNER_OS:-$(uname -s)}"
echo "    RUNNER_OS=${RUNNER_OS:-<unset>} uname=${OS}"

case "$OS" in
  Linux|linux*)
    echo "==> Installing rsync & openssh-client via apt…"
    sudo apt-get update -y
    sudo apt-get install -y rsync openssh-client
    ;;

  macOS|Darwin)
    echo "==> Ensuring GNU rsync via Homebrew…"
    # macOS ships with openrsync, but we need GNU rsync
    # Homebrew installs GNU rsync to avoid conflicts with system rsync
    
    # Check if we have openrsync (system) or no rsync at all
    if ! command -v rsync >/dev/null 2>&1 || rsync --version 2>&1 | grep -qi "openrsync"; then
      echo "    Installing GNU rsync from Homebrew…"
      brew install rsync
    fi

    # OpenSSH client ships with macOS; nothing to install
    ;;

  Windows|Windows_NT)
    echo "==> Ensuring rsync via Chocolatey…"
    # choco is available on Windows runners; retry with upgrade if needed
    if ! choco install rsync --yes --no-progress; then
      choco upgrade rsync --yes --no-progress
    fi
    # OpenSSH client is included on Windows runners
    ;;

  *)
    echo "ERROR: Unsupported OS: $OS" >&2
    exit 1
    ;;
esac

echo "==> Versions:"
rsync --version | head -n 1 || true
ssh -V || true
