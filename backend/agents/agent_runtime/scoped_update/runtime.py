from __future__ import annotations

import re
import time
from typing import Any, Callable

try:
  from ....debug_trace import trace_function
except ImportError:
  from debug_trace import trace_function

from ...prompts import build_scoped_update_patch_prompt
from ..constants import (
  SCOPED_UPDATE_EMPTY_PATCH_RETRY_MAX_OUTPUT_TOKENS,
  SCOPED_UPDATE_MAX_EXISTING_FILES,
  SCOPED_UPDATE_MAX_FILES_PER_MODEL_STEP,
  SCOPED_UPDATE_MAX_OUTPUT_TOKENS,
  SCOPED_UPDATE_MAX_SCOPE_EXPANSIONS,
  SCOPED_UPDATE_MAX_TASKS,
)
from ...artifacts import normalize_artifact_path
from ...prompt_context import current_user_prompt
from ..errors import ScopedUpdateGuardError, UpdateRequestNeedsClarificationError
from ..fallbacks import is_artifact_json_invalid_error, is_model_connection_error
from ..file_ops import merge_project_file_changes, unique_paths
from ..model_agents import run_artifact_provider_with_soft_timeout
from ..schemas import SCOPED_UPDATE_RESPONSE_SCHEMA
from ..timeouts import artifact_call_soft_timeout_seconds
from ..values import list_value, string_list, text_or_default
from . import (
  build_scoped_edit_plan,
  code_search_matches_for_task,
  collect_deterministic_scoped_update_fallback_changes,
  deterministic_onboarding_chat_update_changes,
  deterministic_undefined_name_runtime_fix_changes,
  deterministic_undefined_reference_fix_changes,
  empty_scoped_update_retry_prompt,
  invalid_scoped_update_json_guard_error,
  is_no_effective_scoped_guard_error,
  is_no_patch_scoped_guard_error,
  log_scoped_no_patch_response,
  no_effective_scoped_update_retry_prompt,
  normalize_scoped_update_response,
  scoped_update_request_text,
  scoped_update_analysis_for_task,
  scoped_update_prompt_for_task,
  should_retry_empty_scoped_update_response,
  strict_scoped_update_retry_prompt,
  validate_scoped_update_changes,
)


SCOPED_UPDATE_SYSTEM_INSTRUCTION = (
  "You are an expert web development agent. When modifying an existing codebase, "
  "do not guess line numbers or use broken tool calls. Instead, output code "
  "modifications using explicit SEARCH/REPLACE blocks inside the requested JSON. "
  "Patch only approved files and preserve every unmentioned file, route, style, "
  "data object, backend contract, and local uploaded folder entry. Never delete, "
  "empty, prune, or fully rewrite an existing file for a small update. "
  "Return completed only when the JSON contains a real edit or approved new file "
  "that will change the current source. "
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
      if re.search(r"(?:export\s+)?const\s+\w+\s*=\s*\[", content_key):
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


@trace_function(candidate_count=lambda _artifact_provider, **kwargs: len((kwargs.get("update_analysis") or {}).get("candidate_files") or []), previous_error=lambda _artifact_provider, **kwargs: "yes" if kwargs.get("previous_error") else "no")
def run_scoped_update_agent(
  artifact_provider: Any,
  *,
  prompt: str,
  update_analysis: dict[str, Any],
  existing_files: list[dict[str, str]],
  code_search_matches: list[dict[str, Any]],
  previous_error: str | None = None,
  deadline_monotonic: float | None = None,
) -> dict[str, Any]:
  prompt = current_user_prompt(prompt)
  existing_by_path = {file_item["path"]: file_item["content"] for file_item in existing_files}
  candidate_paths = [
    path
    for path in string_list(update_analysis.get("candidate_files"), [])
    if path in existing_by_path
  ]
  candidate_paths = prioritize_scoped_candidate_paths(
    candidate_paths,
    prompt=prompt,
    update_analysis=update_analysis,
    existing_by_path=existing_by_path,
  )[:SCOPED_UPDATE_MAX_FILES_PER_MODEL_STEP]
  if not candidate_paths:
    raise UpdateRequestNeedsClarificationError(
      "Update request needs clarification before editing files: "
      "I could not identify a safe existing source file for this update. Please name the component or file to change."
    )
  candidate_files: list[dict[str, Any]] = []
  for path in candidate_paths:
    content = existing_by_path[path]
    if len(content) > 160000:
      raise ScopedUpdateGuardError(
        f"Scoped update blocked because {path} is too large for a safe model patch. "
        "Split the component or identify a smaller target first."
      )
    candidate_files.append({"path": path, "content": content, "content_chars": len(content)})
  effective_prompt = prompt
  if previous_error:
    effective_prompt = (
      f"{prompt}\n\n"
      "The previous scoped patch failed validation or preview QA:\n"
      f"{previous_error[:2400]}\n\n"
      "Retry as a minimal existing-code patch. If the previous failure says the update "
      "rewrote too much of a file, do not return a complete changed_files replacement "
      "for that file. Return only exact search/replace edits around the requested "
      "handler, state, data, labels, or small JSX block. Preserve all unrelated layout, "
      "components, styles, copy, imports, and file structure. If the previous failure "
      "mentions an unapproved file or scope boundary, patch only the approved candidate "
      "file shown in this retry prompt and leave other files for later subtasks."
    )
  deterministic_changes = deterministic_undefined_reference_fix_changes(
    prompt=effective_prompt,
    update_analysis=update_analysis,
    existing_files=candidate_files,
  )
  if deterministic_changes:
    return {
      "status": "completed",
      "summary": "Applied deterministic fix for undefined reference crash.",
      "edits": [],
      "changed_files": [
        {"path": file_item["path"], "code": file_item["content"]}
        for file_item in deterministic_changes
      ],
      "clarification_question": "",
      "deterministic_fallback": "undefined_reference_fix",
    }
  deterministic_changes = deterministic_undefined_name_runtime_fix_changes(
    prompt=effective_prompt,
    update_analysis=update_analysis,
    existing_files=candidate_files,
  )
  if deterministic_changes:
    return {
      "status": "completed",
      "summary": "Applied deterministic guard for undefined .name runtime crash.",
      "edits": [],
      "changed_files": [
        {"path": file_item["path"], "code": file_item["content"]}
        for file_item in deterministic_changes
      ],
      "clarification_question": "",
      "deterministic_fallback": "undefined_name_runtime_fix",
    }
  deterministic_changes = deterministic_onboarding_chat_update_changes(
    prompt=effective_prompt,
    update_analysis=update_analysis,
    existing_files=candidate_files,
  )
  if deterministic_changes:
    return {
      "status": "completed",
      "summary": "Applied deterministic 5-step conversational onboarding chat component.",
      "edits": [],
      "changed_files": [
        {"path": file_item["path"], "code": file_item["content"]}
        for file_item in deterministic_changes
      ],
      "clarification_question": "",
      "deterministic_fallback": "onboarding_chat_flow",
    }
  scoped_edit_plan = build_scoped_edit_plan(
    effective_prompt,
    update_analysis=update_analysis,
    candidate_files=candidate_files,
    code_search_matches=code_search_matches,
  )
  planned_update_analysis = {
    **update_analysis,
    "scoped_edit_plan": scoped_edit_plan,
  }
  scoped_prompt = build_scoped_update_patch_prompt(
    effective_prompt,
    update_analysis=planned_update_analysis,
    candidate_files=candidate_files,
    code_search_matches=code_search_matches,
  )
  primary_scoped_prompt = scoped_prompt
  try:
    response = run_artifact_provider_with_soft_timeout(
      artifact_provider,
      primary_scoped_prompt,
      system_instruction=SCOPED_UPDATE_SYSTEM_INSTRUCTION,
      trace_label="scoped_update_artifact",
      response_schema=SCOPED_UPDATE_RESPONSE_SCHEMA,
      max_output_tokens=SCOPED_UPDATE_MAX_OUTPUT_TOKENS,
      timeout_seconds=scoped_update_call_timeout_seconds(deadline_monotonic),
      prompt_fragments_used=["user_prompt", "scoped_update_analysis", "selected_file_excerpts", "patch_policy"],
      selected_files=candidate_paths,
    )
  except Exception as exc:
    if is_model_connection_error(exc):
      raise scoped_update_model_error(exc, phase="the primary patch call") from exc
    if not is_artifact_json_invalid_error(exc):
      raise
    try:
      response = run_artifact_provider_with_soft_timeout(
        artifact_provider,
        strict_scoped_update_retry_prompt(primary_scoped_prompt),
        system_instruction=SCOPED_UPDATE_SYSTEM_INSTRUCTION,
        trace_label="scoped_update_artifact",
        response_schema=SCOPED_UPDATE_RESPONSE_SCHEMA,
        max_output_tokens=SCOPED_UPDATE_MAX_OUTPUT_TOKENS,
        timeout_seconds=scoped_update_call_timeout_seconds(deadline_monotonic),
        prompt_fragments_used=["user_prompt", "scoped_update_analysis", "selected_file_excerpts", "patch_policy", "json_retry"],
        selected_files=candidate_paths,
      )
    except Exception as retry_exc:
      if is_model_connection_error(retry_exc):
        raise scoped_update_model_error(retry_exc, phase="the strict JSON retry") from retry_exc
      if is_artifact_json_invalid_error(retry_exc):
        raise invalid_scoped_update_json_guard_error(retry_exc, phase="after strict JSON retry") from retry_exc
      raise
  normalized_response = normalize_scoped_update_response(response)
  if should_retry_empty_scoped_update_response(normalized_response):
    log_scoped_no_patch_response(
      normalized_response,
      update_analysis=planned_update_analysis,
      phase="primary",
    )
    retry_prompt = empty_scoped_update_retry_prompt(scoped_prompt)
    try:
      response = run_artifact_provider_with_soft_timeout(
        artifact_provider,
        retry_prompt,
        system_instruction=SCOPED_UPDATE_SYSTEM_INSTRUCTION,
        trace_label="scoped_update_artifact",
        response_schema=SCOPED_UPDATE_RESPONSE_SCHEMA,
        max_output_tokens=SCOPED_UPDATE_EMPTY_PATCH_RETRY_MAX_OUTPUT_TOKENS,
        timeout_seconds=scoped_update_call_timeout_seconds(deadline_monotonic),
        prompt_fragments_used=["user_prompt", "scoped_update_analysis", "selected_file_excerpts", "patch_policy", "empty_patch_retry"],
        selected_files=candidate_paths,
      )
    except Exception as retry_exc:
      if is_model_connection_error(retry_exc):
        raise scoped_update_model_error(retry_exc, phase="the empty-patch retry") from retry_exc
      if is_artifact_json_invalid_error(retry_exc):
        raise invalid_scoped_update_json_guard_error(retry_exc, phase="while retrying an empty patch") from retry_exc
      raise
    normalized_response = normalize_scoped_update_response(response)
  if should_retry_empty_scoped_update_response(normalized_response):
    log_scoped_no_patch_response(
      normalized_response,
      update_analysis=planned_update_analysis,
      phase="retry",
    )
  normalized_response["_scoped_prompt"] = scoped_prompt
  normalized_response["_candidate_paths"] = candidate_paths
  return normalized_response


def scoped_update_scope_expansion_retry_prompt(prompt: str, event: dict[str, Any]) -> str:
  accepted_paths = string_list(event.get("accepted_paths"), [])
  return (
    f"{prompt}\n\n"
    "The runtime safely expanded this subtask's internal file scope after your request. "
    f"The next available file is: {', '.join(accepted_paths)}. "
    "Apply the requested change now. Do not ask the user for permission to modify these files."
  )


def scoped_update_expansion_file_rejection(path: str, content: str) -> str:
  try:
    from ...platform_file_locks import is_locked_platform_update_path
  except ImportError:
    from agents.platform_file_locks import is_locked_platform_update_path
  if is_locked_platform_update_path(path):
    return "the file is platform-managed and cannot be edited during website updates"
  lowered_path = path.lower()
  parts = {part for part in lowered_path.split("/") if part}
  basename = lowered_path.rsplit("/", 1)[-1]
  if parts & SCOPED_UPDATE_EXPANSION_DENIED_PARTS:
    return "the path is inside a generated, cached, or vendor directory"
  if basename in SCOPED_UPDATE_EXPANSION_DENIED_FILES:
    return "the file is generated, credential-related, or lock-managed"
  if basename.startswith(".env") and basename != ".env.example":
    return "environment secret files cannot be added to autonomous edit scope"
  if len(content) > 160000:
    return "the file is too large for a safe model patch"
  if "\x00" in content or content.lstrip().lower().startswith("data:"):
    return "binary or encoded asset files cannot be edited by the scoped patch model"
  if basename != ".env.example" and not lowered_path.endswith(SCOPED_UPDATE_EXPANSION_ALLOWED_EXTENSIONS):
    return "the file type is not supported for autonomous scoped editing"
  return ""


def resolve_scoped_update_scope_expansion(
  response: dict[str, Any],
  *,
  update_analysis: dict[str, Any],
  existing_files: list[dict[str, str]],
  retry_count: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
  requested_raw = unique_paths(string_list(response.get("requested_files"), []))
  if not requested_raw:
    raise ScopedUpdateGuardError(
      "Scoped update requested internal scope expansion without naming an existing project file. "
      "The existing website was preserved."
    )
  if len(requested_raw) > SCOPED_UPDATE_MAX_EXISTING_FILES:
    raise ScopedUpdateGuardError(
      "Scoped update requested too many files for bounded scope expansion. "
      "The existing website was preserved."
    )

  existing_by_path = {
    text_or_default(file_item.get("path"), ""): text_or_default(file_item.get("content"), "")
    for file_item in existing_files
    if isinstance(file_item, dict) and text_or_default(file_item.get("path"), "")
  }
  normalized_requested: list[str] = []
  for raw_path in requested_raw:
    try:
      path = normalize_artifact_path(raw_path.strip("`'\" "))
    except Exception as exc:
      raise ScopedUpdateGuardError(
        f"Scoped update requested an unsafe scope-expansion path {raw_path}: {exc}. "
        "The existing website was preserved."
      ) from exc
    if path not in existing_by_path:
      raise ScopedUpdateGuardError(
        f"Scoped update requested missing project file {path} for scope expansion. "
        "The existing website was preserved."
      )
    rejection = scoped_update_expansion_file_rejection(path, existing_by_path[path])
    if rejection:
      raise ScopedUpdateGuardError(
        f"Scoped update rejected scope expansion for {path} because {rejection}. "
        "The existing website was preserved."
      )
    if path not in normalized_requested:
      normalized_requested.append(path)

  current_candidates = [
    path
    for path in string_list(update_analysis.get("candidate_files"), [])
    if path in existing_by_path
  ]
  visible_paths = set(string_list(response.get("_candidate_paths"), []))
  accepted_paths = [path for path in normalized_requested if path not in visible_paths]
  if not accepted_paths:
    raise ScopedUpdateGuardError(
      "Scoped update repeatedly requested scope expansion for files already available in the current model step. "
      "The existing website was preserved."
    )
  newly_approved_paths = [path for path in accepted_paths if path not in current_candidates]
  expanded_candidates = unique_paths([*accepted_paths, *current_candidates])
  if len(expanded_candidates) > SCOPED_UPDATE_MAX_EXISTING_FILES:
    raise ScopedUpdateGuardError(
      "Scoped update scope expansion would exceed the four-existing-file safety limit. "
      "The existing website was preserved."
    )

  expanded_analysis = {
    **update_analysis,
    "candidate_files": expanded_candidates,
  }
  event = {
    "retry_count": retry_count,
    "requested_paths": normalized_requested,
    "accepted_paths": accepted_paths,
    "newly_approved_paths": newly_approved_paths,
    "candidate_files": expanded_candidates,
    "reason": (
      text_or_default(response.get("clarification_question"), "")
      or text_or_default(response.get("summary"), "")
      or "The patch model identified another existing project file required for this subtask."
    )[:500],
  }
  return expanded_analysis, event


def run_scoped_update_task_with_expansion(
  artifact_provider: Any,
  *,
  prompt: str,
  update_analysis: dict[str, Any],
  existing_files: list[dict[str, str]],
  code_search_matches: list[dict[str, Any]],
  previous_error: str | None,
  deadline_monotonic: float | None,
  task: dict[str, Any] | None = None,
  working_files: list[dict[str, str]] | None = None,
  created_candidate_paths: list[str] | None = None,
  task_id: str = "scoped_update",
  task_index: int = 1,
  scope_expansion_callback: ScopeExpansionCallback | None = None,
) -> tuple[dict[str, Any], list[dict[str, str]], dict[str, Any], list[dict[str, Any]]]:
  current_analysis = dict(update_analysis)
  current_prompt = prompt
  scope_expansions: list[dict[str, Any]] = []
  while True:
    current_matches = code_search_matches_for_task(code_search_matches, current_analysis)
    scoped_result = run_scoped_update_agent(
      artifact_provider,
      prompt=current_prompt,
      update_analysis=current_analysis,
      existing_files=existing_files,
      code_search_matches=current_matches,
      previous_error=previous_error,
      deadline_monotonic=deadline_monotonic,
    )
    if text_or_default(scoped_result.get("status"), "") == "needs_scope_expansion":
      if len(scope_expansions) >= SCOPED_UPDATE_MAX_SCOPE_EXPANSIONS:
        raise ScopedUpdateGuardError(
          "Scoped update exceeded the two-attempt internal scope-expansion limit. "
          "The existing website was preserved."
        )
      current_analysis, event = resolve_scoped_update_scope_expansion(
        scoped_result,
        update_analysis=current_analysis,
        existing_files=existing_files,
        retry_count=len(scope_expansions) + 1,
      )
      event.update({"task_id": task_id, "task_index": task_index})
      scope_expansions.append(event)
      if scope_expansion_callback is not None:
        scope_expansion_callback(dict(event))
      current_prompt = scoped_update_scope_expansion_retry_prompt(prompt, event)
      continue

    try:
      changed_files = validate_scoped_update_changes(
        scoped_result,
        update_analysis=current_analysis,
        existing_files=existing_files,
      )
    except ScopedUpdateGuardError as exc:
      recovered = recover_scoped_update_guard_failure(
        exc,
        artifact_provider=artifact_provider,
        scoped_result=scoped_result,
        prompt=current_prompt,
        update_analysis=current_analysis,
        existing_files=existing_files,
        deadline_monotonic=deadline_monotonic,
        task=task,
        working_files=working_files,
        created_candidate_paths=created_candidate_paths,
      )
      if recovered is None:
        raise
      scoped_result, changed_files = recovered
    scoped_result["scope_expansions"] = scope_expansions
    return scoped_result, changed_files, current_analysis, scope_expansions


def recover_scoped_update_guard_failure(
  exc: ScopedUpdateGuardError,
  *,
  artifact_provider: Any,
  scoped_result: dict[str, Any],
  prompt: str,
  update_analysis: dict[str, Any],
  existing_files: list[dict[str, str]],
  deadline_monotonic: float | None,
  task: dict[str, Any] | None = None,
  working_files: list[dict[str, str]] | None = None,
  created_candidate_paths: list[str] | None = None,
) -> tuple[dict[str, Any], list[dict[str, str]]] | None:
  if not is_no_patch_scoped_guard_error(exc):
    return None

  scoped_prompt = text_or_default(scoped_result.get("_scoped_prompt"), "")
  if is_no_effective_scoped_guard_error(exc) and scoped_prompt:
    try:
      response = run_artifact_provider_with_soft_timeout(
        artifact_provider,
        no_effective_scoped_update_retry_prompt(scoped_prompt),
        system_instruction=SCOPED_UPDATE_SYSTEM_INSTRUCTION,
        trace_label="scoped_update_artifact",
        response_schema=SCOPED_UPDATE_RESPONSE_SCHEMA,
        max_output_tokens=SCOPED_UPDATE_EMPTY_PATCH_RETRY_MAX_OUTPUT_TOKENS,
        timeout_seconds=scoped_update_call_timeout_seconds(deadline_monotonic),
        prompt_fragments_used=["user_prompt", "scoped_update_analysis", "selected_file_excerpts", "patch_policy", "no_effective_change_retry"],
        selected_files=string_list(scoped_result.get("_candidate_paths"), []),
      )
    except Exception as retry_exc:
      if is_model_connection_error(retry_exc):
        pass
      elif is_artifact_json_invalid_error(retry_exc):
        pass
      else:
        raise
    else:
      retry_result = normalize_scoped_update_response(response)
      retry_result["_scoped_prompt"] = scoped_prompt
      try:
        changed_files = validate_scoped_update_changes(
          retry_result,
          update_analysis=update_analysis,
          existing_files=existing_files,
        )
      except ScopedUpdateGuardError:
        pass
      else:
        return retry_result, changed_files

  fallback_changes, fallback_kind = collect_deterministic_scoped_update_fallback_changes(
    prompt=prompt,
    update_analysis=update_analysis,
    existing_files=existing_files,
    task=task,
    working_files=working_files,
    created_candidate_paths=created_candidate_paths,
  )
  if not fallback_changes:
    return None

  recovered_result = {
    "status": "completed",
    "summary": "Applied bounded deterministic scoped fallback after Gemini returned no usable scoped patch.",
    "edits": [],
    "changed_files": [
      {"path": file_item["path"], "code": file_item["content"]}
      for file_item in fallback_changes
    ],
    "clarification_question": "",
    "deterministic_fallback": fallback_kind or "scoped_update_recovery",
  }
  return recovered_result, fallback_changes


@trace_function(task_count=lambda _artifact_provider, **kwargs: len((kwargs.get("update_analysis") or {}).get("scoped_update_tasks") or []), previous_error=lambda _artifact_provider, **kwargs: "yes" if kwargs.get("previous_error") else "no")
def run_scoped_update_sequence(
  artifact_provider: Any,
  *,
  prompt: str,
  update_analysis: dict[str, Any],
  existing_files: list[dict[str, str]],
  code_search_matches: list[dict[str, Any]],
  previous_error: str | None = None,
  deadline_monotonic: float | None = None,
  scope_expansion_callback: ScopeExpansionCallback | None = None,
) -> tuple[dict[str, Any], list[dict[str, str]], list[dict[str, Any]]]:
  prompt = current_user_prompt(prompt)
  tasks = [
    task
    for task in list_value(update_analysis.get("scoped_update_tasks"))
    if isinstance(task, dict)
  ][:SCOPED_UPDATE_MAX_TASKS]
  if len(tasks) <= 1:
    scoped_result, changed_files, _final_analysis, _scope_expansions = run_scoped_update_task_with_expansion(
      artifact_provider,
      prompt=prompt,
      update_analysis=update_analysis,
      existing_files=existing_files,
      code_search_matches=code_search_matches,
      previous_error=previous_error,
      deadline_monotonic=deadline_monotonic,
      task=tasks[0] if tasks else None,
      task_id=text_or_default(tasks[0].get("id"), "scoped_update") if tasks else "scoped_update",
      scope_expansion_callback=scope_expansion_callback,
    )
    return scoped_result, changed_files, []

  working_files = [dict(file_item) for file_item in existing_files]
  original_existing_paths = {
    text_or_default(file_item.get("path"), "")
    for file_item in existing_files
    if isinstance(file_item, dict)
  }
  created_candidate_paths: list[str] = []
  final_changed_by_path: dict[str, str] = {}
  changed_path_order: list[str] = []
  task_results: list[dict[str, Any]] = []
  prior_task_memory: list[str] = []
  all_scope_expansions: list[dict[str, Any]] = []
  for index, task in enumerate(tasks):
    stop_after_current_task = False
    task_analysis = scoped_update_analysis_for_task(
      update_analysis,
      task,
      working_files,
      additional_candidate_files=created_candidate_paths,
    )
    task_prompt = scoped_update_prompt_for_task(
      root_prompt=prompt,
      task=task,
      index=index,
      total=len(tasks),
      prior_task_memory=prior_task_memory,
      previous_error=previous_error if index == 0 else None,
    )
    task_result, task_changed_files, task_analysis, task_scope_expansions = run_scoped_update_task_with_expansion(
      artifact_provider,
      prompt=task_prompt,
      update_analysis=task_analysis,
      existing_files=working_files,
      code_search_matches=code_search_matches,
      previous_error=previous_error if index == 0 else None,
      deadline_monotonic=deadline_monotonic,
      task=task,
      working_files=working_files,
      created_candidate_paths=created_candidate_paths,
      task_id=text_or_default(task.get("id"), f"step_{index + 1}"),
      task_index=index + 1,
      scope_expansion_callback=scope_expansion_callback,
    )
    all_scope_expansions.extend(task_scope_expansions)
    stop_after_current_task = text_or_default(task_result.get("deterministic_fallback"), "") == "created_component_content"
    working_files = merge_project_file_changes(working_files, task_changed_files)
    task_changed_paths = [file_item["path"] for file_item in task_changed_files]
    for path in task_changed_paths:
      if path not in original_existing_paths and path not in created_candidate_paths:
        created_candidate_paths.append(path)
    for file_item in task_changed_files:
      path = file_item["path"]
      final_changed_by_path[path] = file_item["content"]
      if path not in changed_path_order:
        changed_path_order.append(path)
    task_summary = {
      "id": text_or_default(task.get("id"), f"step_{index + 1}"),
      "index": index + 1,
      "summary": text_or_default(task.get("summary"), text_or_default(task_result.get("summary"), "")),
      "prompt": text_or_default(task.get("prompt"), "")[:500],
      "candidate_files": string_list(task_analysis.get("candidate_files"), []),
      "candidate_new_files": string_list(task_analysis.get("candidate_new_files"), []),
      "changed_file_paths": task_changed_paths,
      "status": text_or_default(task_result.get("status"), "completed"),
      "scope_expansions": task_scope_expansions,
    }
    task_results.append(task_summary)
    prior_task_memory.append(
      f"Step {index + 1} changed {', '.join(task_changed_paths)}: "
      f"{task_summary['summary']}"
    )
    if stop_after_current_task:
      break

  changed_files = [
    {"path": path, "content": final_changed_by_path[path]}
    for path in changed_path_order
    if path in final_changed_by_path
  ]
  return (
    {
      "status": "completed",
      "summary": f"Applied {len(task_results)} scoped update subtasks.",
      "edits": [],
      "changed_files": [{"path": item["path"], "code": item["content"]} for item in changed_files],
      "requested_files": [],
      "clarification_question": "",
      "task_results": task_results,
      "scope_expansions": all_scope_expansions,
    },
    changed_files,
    task_results,
  )
