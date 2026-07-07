from __future__ import annotations

import re
import time
from typing import Any, Callable

from backend.agents.agent_runtime.constants import (
  SCOPED_UPDATE_EMPTY_PATCH_RETRY_MAX_OUTPUT_TOKENS,
  SCOPED_UPDATE_MAX_EXISTING_FILES,
  SCOPED_UPDATE_MAX_FILES_PER_MODEL_STEP,
  SCOPED_UPDATE_MAX_OUTPUT_TOKENS,
  SCOPED_UPDATE_MAX_SCOPE_EXPANSIONS,
  SCOPED_UPDATE_MAX_TASKS,
)
from backend.agents.agent_runtime.errors import ScopedUpdateGuardError
from backend.agents.agent_runtime.timeouts import artifact_call_soft_timeout_seconds
from backend.agents.agent_runtime.values import text_or_default
from backend.agents.agent_runtime.scoped_update.workflow_parts import scoped_update_request_text

SCOPED_UPDATE_SYSTEM_INSTRUCTION = (
  "You are an expert web development agent. When modifying an existing codebase, "
  "do not guess line numbers or use broken tool calls. Instead, output code "
  "modifications using explicit SEARCH/REPLACE blocks inside the requested JSON. "
  "Patch only approved files and preserve every unmentioned file, route, style, "
  "data object, backend contract, and local uploaded folder entry. Never delete, "
  "empty, prune, or fully rewrite an existing file for a small update. "
  "Return completed only when the JSON contains a real edit or approved new file "
  "that will change the current source. "
  "For interaction contracts, either wire the real handler/navigation/state change, "
  "request internal scope expansion for the exact missing owner file, or ask a concrete "
  "clarification only when the user behavior is ambiguous. "
  "If another existing project file is required, request internal scope expansion "
  "with the exact path instead of asking the user for permission. If the user's "
  "target is ambiguous, return needs_clarification instead of regenerating. "
  "Return strict JSON only."
)

ScopeExpansionCallback = Callable[[dict[str, Any]], None]

SCOPED_UPDATE_EXPANSION_ALLOWED_EXTENSIONS = (
  ".c",
  ".cpp",
  ".cs",
  ".css",
  ".gql",
  ".go",
  ".graphql",
  ".html",
  ".java",
  ".js",
  ".json",
  ".jsx",
  ".kt",
  ".less",
  ".md",
  ".php",
  ".py",
  ".rb",
  ".rs",
  ".sass",
  ".scss",
  ".sh",
  ".sql",
  ".svelte",
  ".swift",
  ".toml",
  ".ts",
  ".tsx",
  ".txt",
  ".vue",
  ".xml",
  ".yaml",
  ".yml",
)
SCOPED_UPDATE_EXPANSION_DENIED_PARTS = {
  ".cache",
  ".git",
  ".next",
  "__pycache__",
  "build",
  "coverage",
  "dist",
  "node_modules",
  "out",
  "target",
  "vendor",
}
SCOPED_UPDATE_EXPANSION_DENIED_FILES = {
  ".npmrc",
  ".pypirc",
  "credentials.json",
  "id_dsa",
  "id_ed25519",
  "id_rsa",
  "package-lock.json",
  "pipfile.lock",
  "pnpm-lock.yaml",
  "poetry.lock",
  "secrets.json",
  "yarn.lock",
}


def scoped_update_remaining_timeout_seconds(deadline_monotonic: float | None) -> int | None:
  if deadline_monotonic is None:
    return None
  remaining = deadline_monotonic - time.monotonic()
  if remaining <= 0:
    raise ScopedUpdateGuardError(
      "Scoped update timed out before the model returned a safe patch. "
      "The existing website was preserved. Try a smaller update, name the exact component, "
      "or increase SCOPED_UPDATE_MODEL_SOFT_TIMEOUT_SECONDS / SCOPED_UPDATE_SEQUENCE_TIMEOUT_SECONDS."
    )
  return max(1, int(remaining))


def scoped_update_call_timeout_seconds(deadline_monotonic: float | None) -> int | None:
  remaining_timeout = scoped_update_remaining_timeout_seconds(deadline_monotonic)
  model_timeout = artifact_call_soft_timeout_seconds("scoped_update_artifact")
  if remaining_timeout is None:
    return model_timeout
  if model_timeout <= 0:
    return remaining_timeout
  return min(model_timeout, remaining_timeout)


def scoped_update_model_error(error: Exception, *, phase: str) -> ScopedUpdateGuardError:
  lowered = str(error).lower()
  if "timed out" in lowered or "timeout" in lowered:
    return ScopedUpdateGuardError(
      f"Scoped update timed out during {phase}. "
      "The existing website was preserved. Try a smaller update, name the exact component, "
      "or increase SCOPED_UPDATE_MODEL_SOFT_TIMEOUT_SECONDS / SCOPED_UPDATE_SEQUENCE_TIMEOUT_SECONDS."
    )
  return ScopedUpdateGuardError(
    f"Scoped update {phase} could not reach the model provider. "
    "The existing website was preserved; retry after the model/network connection is stable."
  )


def prioritize_scoped_candidate_paths(
  paths: list[str],
  *,
  prompt: str,
  update_analysis: dict[str, Any],
  existing_by_path: dict[str, str],
) -> list[str]:
  request_text = scoped_update_request_text(prompt, update_analysis).lower()
  onboarding_chat_request = (
    "onboarding" in request_text
    and any(marker in request_text for marker in ("chat", "conversation", "conversational", "ai chat"))
    and any(marker in request_text for marker in ("5", "five", "step"))
  )
  undefined_name_request = "name" in request_text and (
    "cannot read properties" in request_text or "undefined (reading" in request_text
  )
  list_content_request = any(
    marker in request_text for marker in ("add", "include", "insert", "append", "more", "another")
  ) and any(
    marker in request_text for marker in ("animal", "tiger", "item", "record", "entry", "card", "list")
  )
  if not onboarding_chat_request and not undefined_name_request and not list_content_request:
    return paths

  request_tokens = {
    token
    for token in re.findall(r"[a-z0-9]+", request_text)
    if len(token) >= 4
  }

  def score_path(path: str) -> int:
    path_key = path.lower()
    content_key = existing_by_path.get(path, "").lower()
    path_tokens = {
      token
      for token in re.findall(r"[a-z0-9]+", path_key)
      if len(token) >= 4
    }
    score = 0
    if path_key in request_text:
      score += 400
    score += len(request_tokens & path_tokens) * 35
    if path.endswith((".jsx", ".tsx")):
      score += 80
    elif path.endswith((".js", ".ts")):
      score += 25
    if onboarding_chat_request and ("onboarding" in path_key or "wizard" in path_key):
      score += 1000
    if onboarding_chat_request and ("/components/" in path_key or "/pages/" in path_key):
      score += 140
    if onboarding_chat_request and ("/data/" in path_key or path_key.endswith(("mockdata.js", "mock-data.js", "data.js"))):
      score -= 250
    if list_content_request:
      if "/data/" in path_key or path_key.endswith(("data.js", "data.ts", "mockdata.js", "mock-data.js")):
        score += 800
      if re.search(r"(?:export\\s+)?const\\s+\\w+\\s*=\\s*\\[", content_key):
        score += 650
      if "/pages/" in path_key or "page" in path_key:
        score += 80
      if path.endswith((".jsx", ".tsx")):
        score += 40
    if undefined_name_request:
      compact_content = content_key.replace(" ", "")
      if "usestate(null)" in compact_content:
        score += 300
      if "config={config}" in content_key or "config.name" in content_key:
        score += 260
      if ".name" in content_key:
        score += 120
    return score

  indexed_paths = list(enumerate(paths))
  indexed_paths.sort(key=lambda item: (-score_path(item[1]), item[0]))
  return [path for _, path in indexed_paths]
