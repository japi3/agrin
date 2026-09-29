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
trap 'git checkout -qf "$START" 2>/dev/null || true' EXIT

# An orphan branch: one commit holding the current tree and no history.
#
# Not a tidiness choice. Hugging Face rejects any blob over 10 MiB that is
# not in LFS, and it checks every object in the push, not just the tip. The
# passage file has been re-chunked twice, so the history carries 17.1 MiB
# and 12.6 MiB versions of it that would fail the hook even though the
# current one is small. A Space does not need our history, so it does not
# get it -- and the push is a few megabytes instead of thirteen.
git branch -D "$BRANCH" 2>/dev/null || true
git checkout -q --orphan "$BRANCH"
git reset -q

cat deploy/huggingface/space-header.md README.md > README.hf.md
mv README.hf.md README.md
git add -A
git commit -q -m "Saathi — deployed from github.com/japi3/agrin"

# Put the working tree back the way it was; the frontmatter belongs only in
# the commit that goes to Hugging Face.
git checkout -q "$START" -- README.md 2>/dev/null || true

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
