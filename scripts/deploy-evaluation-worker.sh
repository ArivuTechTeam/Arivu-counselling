#!/usr/bin/env bash
set -euo pipefail

required_branch="main"
current_branch="$(git branch --show-current)"
if [[ "$current_branch" != "$required_branch" ]]; then
  echo "Refusing to deploy: on branch '$current_branch', expected '$required_branch'." >&2
  exit 1
fi

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

# The Railway service must be created once in the dashboard with its Dockerfile
# path set to Dockerfile.evaluation-worker and no public domain/port.
railway up backend --path-as-root --service quiz-generator-evaluation-worker
