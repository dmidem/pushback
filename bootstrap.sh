#!/usr/bin/env bash
set -euo pipefail

uv sync --group dev "$@"

ACT=".venv/bin/activate"
LINE='export PYTHONDONTWRITEBYTECODE=1'
grep -qF "$LINE" "$ACT" || printf '%s\n' "$LINE" >> "$ACT"

mkdir -p .venv/bin
ln -sf ../../scripts/dev.py .venv/bin/dev

cat <<'MSG'

✅ Ready.

Run once: source .venv/bin/activate
Then you can run: dev
To leave the venv later (optional) run: deactivate
MSG
