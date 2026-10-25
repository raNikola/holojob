#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ ! -d ".venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt

echo "Installing Playwright Chromium (for PDF resume export)..."
playwright install chromium

echo "Installing Playwright Firefox (for LinkedIn contact discovery)..."
playwright install firefox

echo ""
echo "Setup Complete"
echo ""
echo "Activate:"
echo "  source .venv/bin/activate"
echo ""
echo "Discovery:"
echo "  python python/job_discovery/run_discovery.py --providers jobspy --country Serbia"
echo "  python python/job_discovery/run_discovery.py --providers serbia"
echo "  python python/job_discovery/run_discovery.py --providers all --country Serbia"
echo ""
echo "Scoring & tailoring (Modules 4–5):"
echo "  npm run score:jobs"
echo "  npm run tailor:resumes -- --limit 5"
