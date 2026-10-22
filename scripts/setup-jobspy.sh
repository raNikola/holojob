#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

python3 -m venv .venv

# shellcheck disable=SC1091
source .venv/bin/activate

pip install --upgrade pip
pip install -r python/job_discovery/requirements.txt

echo ""
echo "Setup Complete"
echo ""
echo "Run:"
echo "  source .venv/bin/activate"
echo "  python python/job_discovery/run_jobspy.py"
