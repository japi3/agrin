#!/usr/bin/env bash
#
# Push this repository to a Hugging Face Space, which runs the real app --
# the React PWA served by FastAPI out of one container, exactly what runs on
# localhost:8080.
#
# Why a script rather than "git push": a Space is configured by YAML
# frontmatter at the top of its README.md, and that frontmatter renders as a
# stray table on GitHub. So master stays clean and the frontmatter is added
# only on a branch that exists to be pushed to Hugging Face.
#
# Run it after creating the Space in the browser:
#
#   deploy/huggingface/push.sh <your-hf-username> <space-name>
#
# It will ask for your Hugging Face access token (Settings -> Access Tokens,
# with write permission). The token is handed to git and not stored here.

set -euo pipefail

USER="${1:?usage: push.sh <hf-username> <space-name>}"
SPACE="${2:?usage: push.sh <hf-username> <space-name>}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BRANCH="hf-space"

cd "$ROOT"

if [ -n "$(git status --porcelain)" ]; then
  echo "Working tree is dirty. Commit or stash first." >&2
  exit 1
fi

START="$(git rev-parse --abbrev-ref HEAD)"
trap 'git checkout -q "$START"' EXIT

# Rebuild the branch from scratch each time, so it is always this commit plus
# the frontmatter and never a divergent history to reconcile.
git branch -D "$BRANCH" 2>/dev/null || true
git checkout -q -b "$BRANCH"

cat deploy/huggingface/space-header.md README.md > README.hf.md
mv README.hf.md README.md
git add README.md
git commit -q -m "Space configuration for Hugging Face"

echo
echo "Pushing to https://huggingface.co/spaces/$USER/$SPACE"
echo "Username: $USER   Password: paste your HF access token"
echo
git push -f "https://huggingface.co/spaces/$USER/$SPACE" "$BRANCH:main"

echo
echo "Done. The Space will build; watch the log at:"
echo "  https://huggingface.co/spaces/$USER/$SPACE"
echo
echo "Then set the secrets under Settings -> Variables and secrets:"
echo "  GEMINI_API_KEYS   (see .streamlit/secrets.toml)"
echo "  DATA_GOV_IN_KEY"
