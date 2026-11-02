#!/bin/sh
# Use the tracked hooks in scripts/git-hooks. Safe to run again.
set -eu
cd "$(dirname "$0")/.."
git config core.hooksPath scripts/git-hooks
echo "core.hooksPath = $(git config core.hooksPath)"
