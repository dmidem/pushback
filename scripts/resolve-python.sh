#!/usr/bin/env bash
set -euo pipefail

# resolve-python.sh
# Usage: resolve-python.sh <matrix-python-version> [src_dir]
#   <matrix-python-version> : "min" | "latest" | explicit like "3.11" or "3.12.5"
#   [src_dir]               : base src directory (default: "src")
#
# Outcome:
#   - Determines the concrete version string:
#       - "latest"  -> "3.x"  (for actions/setup-python)
#       - "min"     -> reads MIN_PYTHON from src/*/_meta.py
#       - explicit  -> passed through
#   - Exports RESOLVED_PYTHON into $GITHUB_ENV when available,
#     otherwise prints it to stdout.

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "Usage: $0 <min|latest|MAJOR.MINOR[.PATCH]> [src_dir]" >&2
  exit 64
fi

INPUT="$1"
SRC_DIR="${2:-src}"

case "$INPUT" in
  latest)
    RESOLVED="3.x"   # actions/setup-python will pick the latest 3.x patch
    ;;
  min)
    shopt -s nullglob
    metas=( "$SRC_DIR"/*/_meta.py )
    if [[ ${#metas[@]} -lt 1 ]]; then
      echo "ERROR: No _meta.py found under '$SRC_DIR/*'" >&2
      exit 1
    fi
    meta="${metas[0]}"
    # Extract: MIN_PYTHON = "X.Y"
    MIN=$(grep -E '^MIN_PYTHON[[:space:]]*=' "$meta" | cut -d'"' -f2 || true)
    if [[ -z "${MIN:-}" ]]; then
      echo "ERROR: MIN_PYTHON not found in $meta" >&2
      exit 1
    fi
    RESOLVED="$MIN"
    ;;
  *)
    RESOLVED="$INPUT"
    ;;
esac

# Prefer writing to GITHUB_ENV (GitHub Actions), else print to stdout
if [[ -n "${GITHUB_ENV:-}" ]]; then
  echo "RESOLVED_PYTHON=$RESOLVED" >> "$GITHUB_ENV"
else
  echo "$RESOLVED"
fi
