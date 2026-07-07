#!/usr/bin/env bash
# Worktual local environment bootstrap — starts the helper and optionally installs project deps.
# Usage: bash worktual-local-setup.sh [/path/to/project]
set -euo pipefail

WORKTUAL_SERVER="__WORKTUAL_SERVER__"
PROJECT_PATH="${1:-}"
HELPER_SCRIPT="${TMPDIR:-/tmp}/worktual-skills-helper.py"
HELPER_LOG="${TMPDIR:-/tmp}/worktual-skills-helper.log"
HELPER_URL="http://127.0.0.1:8799"

echo "Worktual local setup"
echo "Server: ${WORKTUAL_SERVER}"

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 is required. Install Python 3 and retry." >&2
  exit 1
fi

echo "Downloading local helper..."
curl -kfsSL "${WORKTUAL_SERVER}/api/local-helper/skills-helper.py" -o "${HELPER_SCRIPT}"

if curl -fsS "${HELPER_URL}/health" >/dev/null 2>&1; then
  echo "Local helper is already running at ${HELPER_URL}"
else
  echo "Starting local helper in background (log: ${HELPER_LOG})..."
  nohup python3 "${HELPER_SCRIPT}" >"${HELPER_LOG}" 2>&1 &
  sleep 2
  if ! curl -fsS "${HELPER_URL}/health" >/dev/null 2>&1; then
    echo "ERROR: Helper did not start. Check ${HELPER_LOG}" >&2
    exit 1
  fi
  echo "Local helper is running at ${HELPER_URL}"
fi

if [ -n "${PROJECT_PATH}" ] && [ -d "${PROJECT_PATH}" ]; then
  if [ -f "${PROJECT_PATH}/package.json" ]; then
    echo "Installing frontend dependencies in ${PROJECT_PATH}..."
    if ! command -v npm >/dev/null 2>&1; then
      echo "ERROR: npm is required for frontend projects. Install Node.js and retry." >&2
      exit 1
    fi
    (
      cd "${PROJECT_PATH}"
      npm install --ignore-scripts
      npm run build
    )
    echo "Project dependencies installed and build completed."
  else
    echo "No package.json in ${PROJECT_PATH}; skipped npm install."
  fi
else
  echo "No project path provided; skipped npm install."
  echo "Return to Worktual, click Check Local Helper, then Install on this computer again with your project folder linked."
fi

echo "Done. You can close this terminal and return to Worktual."
