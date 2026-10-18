#!/usr/bin/env bash
# Run only after an explicit IDE action. Do not install tools or read .env files.
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -n "${LSF_IDE_PYTHON:-}" ]]; then
  python="$LSF_IDE_PYTHON"
elif [[ -x "$root/.venv/bin/python" ]]; then
  python="$root/.venv/bin/python"
elif [[ -x "$root/.venv/Scripts/python.exe" ]]; then
  python="$root/.venv/Scripts/python.exe"
else
  python="python3"
fi
if ! command -v "$python" >/dev/null 2>&1; then
  printf '%s\n' 'Python is missing. Prepare .venv or set LSF_IDE_PYTHON; see docs/development/intellij-idea.md.' >&2
  exit 127
fi
exec "$python" "$root/tools/intellij.py" run "$@"
