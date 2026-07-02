from __future__ import annotations

import re

from ..budget_config import AGENT_BUDGETS


REAL_AGENT_RUNTIME_NAME = "worktual-real-agent-runtime-loop"
DEFAULT_AGENT_RUNTIME_TIMEOUT_SECONDS = 360
DEFAULT_REPAIR_MODEL_SOFT_TIMEOUT_SECONDS = 90
DEFAULT_SCOPED_UPDATE_MODEL_SOFT_TIMEOUT_SECONDS = 45
REPAIR_RUNTIME_MIN_REMAINING_SECONDS = 30
SCOPED_UPDATE_MAX_OUTPUT_TOKENS = AGENT_BUDGETS.scoped_update_output_tokens
SCOPED_UPDATE_EMPTY_PATCH_RETRY_MAX_OUTPUT_TOKENS = AGENT_BUDGETS.scoped_update_retry_output_tokens
SCOPED_UPDATE_COMPACT_CONTEXT_THRESHOLD_CHARS = 32_000
SCOPED_UPDATE_COMPACT_CONTEXT_FILE_THRESHOLD_CHARS = 16_000
SCOPED_UPDATE_COMPACT_EXCERPT_MAX_COUNT = 10
SCOPED_UPDATE_COMPACT_EXCERPT_MAX_CHARS = 3_200
SCOPED_UPDATE_COMPACT_TERM_MATCH_RADIUS = 420
SCOPED_UPDATE_EDIT_PLAN_ANCHOR_MAX_CHARS = 800
SCOPED_UPDATE_EDIT_PLAN_MAX_ANCHORS = 6
SCOPED_UPDATE_EDIT_PLAN_TERM_MATCH_RADIUS = 240
SCOPED_UPDATE_COMPACT_PROMPT_MAX_ANALYSIS_CHARS = 10_000
SCOPED_UPDATE_COMPACT_PROMPT_MAX_EXCERPT_CHARS = 28_000
SCOPED_UPDATE_MAX_TASKS = 4
SCOPED_UPDATE_MAX_FILES_PER_MODEL_STEP = 1
SCOPED_UPDATE_MAX_EXISTING_FILES = 4
SCOPED_UPDATE_MAX_SCOPE_EXPANSIONS = 2
SCOPED_UPDATE_FUZZY_MIN_CHARS = 40
SCOPED_UPDATE_FUZZY_MIN_RATIO = 0.84
SCOPED_UPDATE_FUZZY_MIN_MARGIN = 0.08
SCOPED_UPDATE_MAX_NEW_FILES = 2
SCOPED_UPDATE_NEW_FILE_EXTENSIONS = (
  ".js",
  ".jsx",
  ".ts",
  ".tsx",
  ".css",
  ".json",
  ".py",
  ".sql",
  ".toml",
  ".txt",
  ".yml",
  ".yaml",
  ".md",
)
SCOPED_UPDATE_NEW_FILE_PREFIXES = (
  "src/",
  "public/",
  "backend/",
  "api/",
  "app/",
  "server/",
  "database/",
  "db/",
  "migrations/",
  "alembic/",
  "scripts/",
  "tests/",
)
VITE_SCAFFOLD_PATHS = ("index.html", "package.json", "src/main.jsx", "src/index.css")
TAILWIND_SCAFFOLD_PATHS = ("tailwind.config.js", "postcss.config.js")
TAILWIND_DIRECTIVES = "@tailwind base;\n@tailwind components;\n@tailwind utilities;"
TAILWIND_CLASS_RE = re.compile(
  r"(?:className|class)\s*=\s*(?:[\"'][^\"']*(?:\bflex\b|\bgrid\b|\bhidden\b|\bblock\b|\brelative\b|\babsolute\b|\bsticky\b|\bfixed\b|\bbg-[A-Za-z0-9_:/.\-[\]#%]+|\btext-[A-Za-z0-9_:/.\-[\]#%]+|\bpx-[A-Za-z0-9_:/.\-[\]#%]+|\bpy-[A-Za-z0-9_:/.\-[\]#%]+|\bw-[A-Za-z0-9_:/.\-[\]#%]+|\bh-[A-Za-z0-9_:/.\-[\]#%]+|\bmax-w-[A-Za-z0-9_:/.\-[\]#%]+|\bmin-h-[A-Za-z0-9_:/.\-[\]#%]+|\brounded[A-Za-z0-9_:/.\-[\]#%]*|\bshadow[A-Za-z0-9_:/.\-[\]#%]*|\bobject-cover\b)[^\"']*[\"']|{`[^`]*(?:\bflex\b|\bgrid\b|\bbg-[A-Za-z0-9_:/.\-[\]#%]+|\btext-[A-Za-z0-9_:/.\-[\]#%]+|\bpx-[A-Za-z0-9_:/.\-[\]#%]+|\bpy-[A-Za-z0-9_:/.\-[\]#%]+|\bw-[A-Za-z0-9_:/.\-[\]#%]+|\bh-[A-Za-z0-9_:/.\-[\]#%]+|\brounded[A-Za-z0-9_:/.\-[\]#%]*|\bshadow[A-Za-z0-9_:/.\-[\]#%]*|\bobject-cover\b)[^`]*`})",
  re.DOTALL,
)
SUPERVISOR_SYSTEM_INSTRUCTION = (
  "You are the Worktual AI Dev Supervisor Agent. Choose the next agent action from the provided "
  "available_actions list only. Return strict JSON with keys: next_agent, next_action, tools_to_call, "
  "reason, stop_or_continue. Use tools_to_call only for backend tools listed under the selected action. "
  "Never invent completed backend work, never skip required backend tools or completion gates, "
  "and never choose actions or tools outside the provided options. Prefer the smallest safe workflow: "
  "scoped patch for bounded updates, full generation only for new projects or explicit rebuilds. "
  "Require validation, preview/QA, safe materialization, and memory persistence before DONE. "
  "Escalate to clarification or approval before destructive writes, deletes, large rewrites, "
  "security-sensitive edits, or unrelated file changes."
)

SUPERVISOR_GOAL = (
  "Generate or update a web, full-stack, backend, database, or integration project from the user prompt. "
  "The loop is complete only after project files exist, the artifact contract is valid, applicable "
  "build/preview checks are ready, integrity QA passes when applicable, candidate files are committed "
  "through WRITE_PROJECT_FILES, and final project memory is persisted through PERSIST_PROJECT_MEMORY."
)
