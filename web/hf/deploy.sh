#!/usr/bin/env bash
#
# Push this repo to a Hugging Face Docker Space, with the HF-required root
# files (Dockerfile + README) staged on a throwaway `hf-deploy` branch so your
# real branches stay clean.
#
# Prerequisites:
#   1. Create a Docker Space:  https://huggingface.co/new-space  (SDK = Docker)
#   2. Have an HF *write* token: https://huggingface.co/settings/tokens
#      Configure git to use it, e.g.:
#         git config --global credential.helper store
#      then push once and enter your HF username + token when prompted.
#
# Usage:
#   web/hf/deploy.sh https://huggingface.co/spaces/<user>/<space>
#
set -euo pipefail

SPACE_URL="${1:-}"
if [[ -z "$SPACE_URL" ]]; then
  echo "usage: web/hf/deploy.sh https://huggingface.co/spaces/<user>/<space>" >&2
  exit 1
fi

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

ORIGINAL_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
cleanup() { git checkout "$ORIGINAL_BRANCH" >/dev/null 2>&1 || true; }
trap cleanup EXIT

git remote remove hf-space 2>/dev/null || true
git remote add hf-space "$SPACE_URL"

# Build a clean deploy branch from the current commit and add the two files HF
# requires at the repo root.
git checkout -B hf-deploy
cp web/hf/Dockerfile ./Dockerfile
cp web/hf/space_card.md ./README.md
git add Dockerfile README.md
git commit -m "HF Space deploy artifacts" >/dev/null 2>&1 || true

echo "Pushing to $SPACE_URL (branch main)…"
git push -f hf-space hf-deploy:main

echo
echo "Done. Watch the build at: ${SPACE_URL%/}/settings  (or the Space page)."
echo "First build takes a few minutes (it compiles the SPA and installs Python deps)."
