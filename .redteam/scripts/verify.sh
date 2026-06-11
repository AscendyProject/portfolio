#!/usr/bin/env bash
set -euo pipefail

# ascendy-portfolio gate: ruff + pytest over OUR code (portfolio/ + tests/),
# NOT the vendored harness under .redteam/.

# Auto-activate a local venv if present.
if [ -z "${VIRTUAL_ENV:-}" ] && [ -f "venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    source venv/bin/activate
fi

echo "=== ruff check ==="
ruff check portfolio/ tests/

echo "=== ruff format check ==="
ruff format --check portfolio/ tests/

echo "=== pytest ==="
pytest tests -x --tb=short

echo "✅ verify.sh OK"
