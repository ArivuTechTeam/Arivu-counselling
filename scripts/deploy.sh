#!/usr/bin/env bash
# Deploys the backend to Railway. Only runs from the akbar branch (testing) —
# update REQUIRED_BRANCH to main once akbar is merged and testing is done.
set -euo pipefail

REQUIRED_BRANCH="akbar"
current_branch="$(git branch --show-current)"

if [[ "$current_branch" != "$REQUIRED_BRANCH" ]]; then
  echo "Refusing to deploy: on branch '$current_branch', expected '$REQUIRED_BRANCH'." >&2
  exit 1
fi

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
# railway up uploads relative to the linked project root, not $PWD — scope
# the build to backend/ explicitly, or it uploads the whole repo and fails.
cd "$repo_root"
railway up backend --path-as-root
