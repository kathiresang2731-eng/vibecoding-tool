from __future__ import annotations

import json
import os
import re
from typing import Any, Callable

try:
  from ...agentic.tools.definitions import ToolExecutionError
  from ...agentic.tools.handlers import pull_linked_workspace_to_store, upsert_project_files_tool
  from ...agentic.tools.platform import list_dir_tool, read_file_tool, str_replace_tool
  from ...agentic.tools.validators import required_string
  from ...runtime_control import raise_if_runtime_cancelled
  from ...storage import UserContext
except ImportError:
  from agentic.tools.definitions import ToolExecutionError
  from agentic.tools.handlers import pull_linked_workspace_to_store, upsert_project_files_tool
  from agentic.tools.platform import list_dir_tool, read_file_tool, str_replace_tool
  from agentic.tools.validators import required_string
  from runtime_control import raise_if_runtime_cancelled
  from storage import UserContext

from ..artifacts.errors import ArtifactValidationError
from ..artifacts.paths import normalize_artifact_path
from ..code_locations import source_symbol_for_line

try:
  from .line_refs import line_delta_for_replace, line_range_for_substring, read_range_for_content, tool_location_detail
except ImportError:
  from agents.streaming.line_refs import line_delta_for_replace, line_range_for_substring, read_range_for_content, tool_location_detail

try:
  from ..agent_tool_catalog import STREAMING_FILE_GEMINI_TOOL_DESCRIPTIONS
except ImportError:
  from agents.agent_tool_catalog import STREAMING_FILE_GEMINI_TOOL_DESCRIPTIONS

try:
  from ..prompting.policies import prompt_policy_block
except ImportError:
  from agents.prompting.policies import prompt_policy_block

try:
  from ..budget_config import AGENT_BUDGETS
except ImportError:
  from agents.budget_config import AGENT_BUDGETS

try:
  from ..chat_history import prompt_already_has_update_continuity, primary_update_prompt
except ImportError:
  from agents.chat_history import prompt_already_has_update_continuity, primary_update_prompt

ProgressCallback = Callable[..., None]

CONTEXT_CHAR_BUDGET = AGENT_BUDGETS.streaming_context_chars
UPDATE_CONTEXT_CHAR_BUDGET = AGENT_BUDGETS.streaming_update_context_chars
INLINE_FILE_MAX_CHARS = AGENT_BUDGETS.streaming_inline_file_chars
UPDATE_INLINE_FILE_MAX_CHARS = AGENT_BUDGETS.streaming_update_inline_file_chars
UPDATE_PRIORITY_FILE_MAX_CHARS = AGENT_BUDGETS.streaming_update_priority_file_chars
TOOL_READ_MAX_CHARS = AGENT_BUDGETS.streaming_tool_read_chars
DELTA_CHUNK_SIZE = 28
SECRET_ENV_BASENAMES = {
  ".env",
  ".env.local",
  ".env.development",
  ".env.production",
  ".env.test",
}
ENV_EXAMPLE_PATH = ".env.example"


def _runtime_steps_from_tool_calls(
  tool_calls: list[dict[str, Any]] | None,
  *,
  intent: str,
) -> list[dict[str, Any]]:
  calls = [item for item in (tool_calls or []) if isinstance(item, dict)]
  steps: list[dict[str, Any]] = []
  if intent == "website_update":
    steps.append({"agent": "update_analysis_agent", "tool": "analyze_update_request", "status": "completed"})
  elif intent == "website_generation":
    steps.append({"agent": "prompt_analyst_agent", "tool": "analyze_prompt", "status": "completed"})
  for call in calls:
    name = str(call.get("name") or "").strip()
    if not name:
      continue
    steps.append(
      {
        "agent": (
          "streaming_file_agent"
          if name in {"read_file", "list_files", "write_file", "str_replace", "search_codebase"}
          else "backend_runtime_agent"
        ),
        "tool": name,
        "status": "completed",
      }
    )
  return steps


def _short_list_for_failure(values: list[str] | tuple[str, ...], *, limit: int = 6) -> str:
  cleaned = [str(value).strip() for value in values if str(value or "").strip()]
  if not cleaned:
    return "none"
  suffix = "" if len(cleaned) <= limit else f", +{len(cleaned) - limit} more"
  return ", ".join(cleaned[:limit]) + suffix


def _syntax_retry_context(
  *,
  syntax_issues: list[str] | None = None,
  tool_failures: list[str] | None = None,
  max_items: int = 8,
) -> str:
  issues = [str(issue).strip() for issue in (syntax_issues or []) if str(issue or "").strip()]
  failures = [
    str(item).strip()
    for item in (tool_failures or [])
    if str(item or "").strip()
    and (
      "syntax" in str(item).lower()
      or "unbalanced" in str(item).lower()
      or "missing export" in str(item).lower()
    )
  ]
  lines = [*issues[:max_items], *failures[:max(0, max_items - len(issues[:max_items]))]]
  if not lines:
    return ""
  return "\n".join(f"- {line[:500]}" for line in lines[:max_items])


def _syntax_repair_retry_prompt(
  *,
  base_user_message: str,
  syntax_issues: list[str],
  failed_paths: list[str],
  previous_output: str = "",
) -> str:
  issue_block = _syntax_retry_context(syntax_issues=syntax_issues)
  path_block = ", ".join(path for path in failed_paths if path)
  previous_summary = f"Previous model summary: {previous_output[:500]}\n" if previous_output else ""
  return (
    f"{base_user_message}\n\n"
    "Previous attempt was rejected by the backend syntax gate before save. "
    "Retry once with a smaller, targeted patch.\n"
    f"Failed path(s): {path_block or 'unknown'}\n"
    f"Syntax issue(s):\n{issue_block or '- syntax validation failed'}\n\n"
    "Repair instructions:\n"
    "- Re-read each failed file before editing.\n"
    "- Prefer str_replace on the smallest broken block instead of rewriting the full file.\n"
    "- Ensure every JSX/TSX component keeps export default when required.\n"
    "- Balance braces, parentheses, brackets, and JSX tags before calling write_file or str_replace.\n"
    "- Do not edit unrelated files, package.json, generated router shims, or platform config files.\n"
    f"{previous_summary}"
  )

STREAMING_FILE_AGENT_TOOLS: list[dict[str, Any]] = [
  {
    "type": "function",
    "function": {
      "name": "read_file",
      "description": STREAMING_FILE_GEMINI_TOOL_DESCRIPTIONS["read_file"],
      "parameters": {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
        "additionalProperties": False,
      },
    },
  },
  {
    "type": "function",
    "function": {
      "name": "write_file",
      "description": STREAMING_FILE_GEMINI_TOOL_DESCRIPTIONS["write_file"],
      "parameters": {
        "type": "object",
        "properties": {
          "path": {"type": "string"},
          "content": {"type": "string"},
        },
        "required": ["path", "content"],
        "additionalProperties": False,
      },
    },
  },
  {
    "type": "function",
    "function": {
      "name": "str_replace",
      "description": STREAMING_FILE_GEMINI_TOOL_DESCRIPTIONS["str_replace"],
      "parameters": {
        "type": "object",
        "properties": {
          "path": {"type": "string"},
          "old_string": {"type": "string"},
          "new_string": {"type": "string"},
        },
        "required": ["path", "old_string", "new_string"],
        "additionalProperties": False,
      },
    },
  },
  {
    "type": "function",
    "function": {
      "name": "list_files",
      "description": STREAMING_FILE_GEMINI_TOOL_DESCRIPTIONS["list_files"],
      "parameters": {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "additionalProperties": False,
      },
    },
  },
  {
    "type": "function",
    "function": {
      "name": "search_codebase",
      "description": STREAMING_FILE_GEMINI_TOOL_DESCRIPTIONS["search_codebase"],
      "parameters": {
        "type": "object",
        "properties": {
          "query": {"type": "string"},
          "limit": {"type": "integer"},
        },
        "required": ["query"],
        "additionalProperties": False,
      },
    },
  },
]

SYSTEM_INSTRUCTION = (
  "You are a fast website coding agent. Use read_file, list_files, write_file, and str_replace to "
  "implement the user's request. Read relevant files before editing. For str_replace, copy the exact "
  "text from the file including whitespace. All React source paths must live under src/ (for example "
  "src/App.jsx, src/pages/Home.jsx, src/components/Navbar.jsx). Root config files like package.json, "
  "index.html, vite.config.js, and tailwind.config.js stay at the project root. Keep each component "
  "under 350 lines; split large UI into smaller components instead of one giant file. "
  "For generation, build enterprise-quality multi-section pages with working button handlers and "
  "react-router-dom navigation — never leave dead CTAs. When finished, reply "
  "with a short summary of what changed.\n\n"
  f"{prompt_policy_block(include_generation=True, include_update=False)}"
)


def _is_secret_env_path(path: str) -> bool:
  normalized = str(path or "").replace("\\", "/").strip()
  base = normalized.rsplit("/", 1)[-1]
  return base in SECRET_ENV_BASENAMES


def _env_example_path_for(path: str) -> str:
  normalized = str(path or "").replace("\\", "/").strip()
  if "/" not in normalized:
    return ENV_EXAMPLE_PATH
  folder = normalized.rsplit("/", 1)[0]
  return f"{folder}/{ENV_EXAMPLE_PATH}".replace("//", "/")

UPDATE_SYSTEM_INSTRUCTION = (
  f"{SYSTEM_INSTRUCTION} "
  "This is a DIRECT PROJECT UPDATE to an existing project. Use the current workspace files and project memory "
  "as the source of truth, then update the actual code directly. When the prompt includes conversation continuity from "
  "earlier chat turns, treat those earlier requirements as still active unless the latest message clearly "
  "replaces them. Change only what the user asked for across the full session intent. Preserve all unrelated "
  "layout, copy, routes, and styling. For existing files you MUST use str_replace for partial edits. "
  "write_file is allowed ONLY for brand-new paths that do not exist yet. "
  "Never replace an entire existing file with write_file — the backend will block large rewrites. "
  "Never delete, empty, or prune unmentioned files; local uploaded folders must keep every unmentioned file. "
  "If the exact section cannot be identified, inspect the live workspace using list_files/read_file and project memory; "
  "ask for clarification only when the target remains genuinely ambiguous after inspection. "
  "When project memory suggests target files, treat them as priority starting points, not as a hard edit cage. "
  "You may read and edit any relevant workspace file required to complete the user request. "
  "Never edit auto-generated runtime shim files (src/worktual-*-shim.*). "
  "For broken buttons, clicks with no action, or auth/trial flows: wire real onClick handlers and "
  "react-router-dom navigation (useNavigate/Link) in the target page/component. "
  "You MUST apply at least one successful str_replace (or write_file for a brand-new path) before finishing. "
  "Reading files alone is never a completed update."
)

ERROR_REPAIR_SYSTEM_INSTRUCTION = (
  f"{UPDATE_SYSTEM_INSTRUCTION} "
  "The user is reporting a bug, build error, or runtime failure. Work surgically: read ONLY the "
  "candidate files listed in the error diagnosis (at most 3), apply the smallest fix, then stop. "
  "Do NOT list or read every page file to hunt for issues. Do NOT edit src/worktual-*-shim.* files; "
  "fix the app page or component that imports the library instead. Use str_replace only on existing files. "
  "If str_replace fails, re-read the file and use a longer exact old_string — never rewrite the whole file. "
  "After fixing, summarize the root cause and changed files."
)

RUNTIME_SHIM_PATH_MARKERS = ("worktual-router-shim", "worktual-recharts-shim", "worktual-framer-motion-shim", "worktual-clsx-shim", "worktual-tailwind-merge-shim")

ERROR_REPAIR_PROMPT_MARKERS = (
  "build error",
  "syntaxerror",
  "referenceerror",
  "typeerror",
  "uncaught",
  "stack trace",
  "stacktrace",
  "doesn't work",
  "does not work",
  "not working",
  "not clickable",
  "nothing happens",
  "no action",
  "no response",
  "when i click",
  "when user clicks",
  "when clicked",
  "clicking the",
  "click the button",
  "button doesn't",
  "button does not",
  "guest trial",
  "sandbox quick",
  "console error",
  "runtime error",
  "blank page",
  "white screen",
  "does not provide an export",
  "doesn't provide an export",
  "provide an export named",
  "export named",
  "named export",
  "failed to",
  "failure",
)

ERROR_REPAIR_CONTEXT_MARKERS = (
  "error",
  "bug",
  "broken",
  "crash",
  "exception",
  "issue",
  "cannot find module",
  "could not resolve",
  "module not found",
  "does not provide an export",
  "doesn't provide an export",
  "provide an export named",
  "export named",
  "named export",
  "failed",
  "not defined",
)


def is_runtime_shim_path(path: str) -> bool:
  normalized = str(path or "").replace("\\", "/").lower()
  return any(marker in normalized for marker in RUNTIME_SHIM_PATH_MARKERS)


def is_error_repair_prompt(prompt: str) -> bool:
  lowered = primary_update_prompt(prompt).lower()
  if any(marker in lowered for marker in ERROR_REPAIR_PROMPT_MARKERS):
    return True
  if re.search(r"\bfix\b", lowered) and any(marker in lowered for marker in ERROR_REPAIR_CONTEXT_MARKERS):
    return True
  if "fix" in lowered and any(marker in lowered for marker in ("doesn't work", "does not work", "not working")):
    return True
  if "click" in lowered and any(marker in lowered for marker in ("button", "trial", "guest", "cta", "link")):
    return True
  if "bypass" in lowered and any(marker in lowered for marker in ("auth", "login", "trial", "guest", "dashboard")):
    return True
  return False


def is_ui_interaction_repair_prompt(prompt: str) -> bool:
  try:
    from .task_planner import is_ui_interaction_repair_prompt as _is_ui_interaction_repair_prompt
  except ImportError:
    from agents.streaming.task_planner import is_ui_interaction_repair_prompt as _is_ui_interaction_repair_prompt
  return _is_ui_interaction_repair_prompt(prompt)


def is_auth_flow_update_prompt(prompt: str) -> bool:
  try:
    from .task_planner import is_auth_onboarding_flow_repair_prompt
  except ImportError:
    from agents.streaming.task_planner import is_auth_onboarding_flow_repair_prompt
  return is_auth_onboarding_flow_repair_prompt(prompt)


def _merge_prompt_with_chat_continuity(
  prompt: str,
  *,
  tool_context: Any,
  user: UserContext,
  project_id: str,
  chat_session_id: str | None,
  chat_topic_id: str | None = None,
) -> str:
  if not chat_session_id or tool_context is None:
    return prompt
  try:
    from ..chat_history import merge_update_prompt_with_chat_context
    from ..memory.context import _load_project_chat_messages
  except ImportError:
    from agents.chat_history import merge_update_prompt_with_chat_context
    from agents.memory.context import _load_project_chat_messages
  messages = _load_project_chat_messages(
    tool_context.store,
    user,
    project_id=project_id,
    chat_session_id=chat_session_id,
    chat_topic_id=chat_topic_id,
  )
  return merge_update_prompt_with_chat_context(prompt, messages)


def _unified_update_scope_enabled(*, intent: str, worker_id: str | None) -> bool:
  if intent != "website_update" or worker_id:
    return False
  try:
    from ..runtime_config import unified_website_updates_active
  except ImportError:
    from agents.runtime_config import unified_website_updates_active
  return unified_website_updates_active()


def _env_int(name: str, fallback: int) -> int:
  raw = str(os.getenv(name, str(fallback))).strip()
  try:
    return int(raw)
  except ValueError:
    return fallback


def _env_bool(name: str, fallback: bool) -> bool:
  raw = str(os.getenv(name, str(fallback))).strip().lower()
  if raw in {"1", "true", "yes", "on"}:
    return True
  if raw in {"0", "false", "no", "off"}:
    return False
  return fallback


def _minimum_update_step_limit(
  *,
  request_kind: str,
  error_repair: bool = False,
  auth_flow: bool = False,
  ui_interaction: bool = False,
  has_chat_continuity: bool = False,
) -> int:
  """Keep website updates from becoming read-only because of an undersized env budget."""
  normalized_kind = str(request_kind or "").strip().lower()
  if normalized_kind == "flow_patch" or auth_flow:
    return 12
  if normalized_kind in {"theme_color_update", "style_reference_update"}:
    return 8
  if normalized_kind == "interaction_wiring_update" or ui_interaction:
    return 10
  if error_repair or has_chat_continuity:
    return 6
  return 6


def _is_tool_loop_step_exhaustion(error: str | None) -> bool:
  normalized = str(error or "").strip().lower()
  return bool(normalized and "tool-calling loop exceeded" in normalized)


def streaming_file_agent_step_limit(
  *,
  intent: str,
  prompt: str,
  worker_id: str | None = None,
  max_steps: int | None = None,
  request_kind: str = "",
) -> int:
  if max_steps is not None:
    return max_steps
  normalized_kind = str(request_kind or "").strip().lower()
  style_reference = normalized_kind == "style_reference_update"
  interaction_wiring = normalized_kind == "interaction_wiring_update"
  if _unified_update_scope_enabled(intent=intent, worker_id=worker_id):
    # Unified update scope already has the model-derived request_kind. Do not
    # call legacy prompt heuristics here; they are kept only for the non-unified
    # fallback path below.
    ui_interaction = intent == "website_update" and interaction_wiring
    error_repair = intent == "website_update" and normalized_kind == "bug_fix" and not ui_interaction
    if error_repair:
      base = _env_int("STREAMING_FILE_AGENT_MAX_STEPS", 10)
    else:
      base = _env_int("STREAMING_FILE_AGENT_UPDATE_MAX_STEPS", 10)
    bonus = 0
    if style_reference:
      bonus += 2
    elif interaction_wiring:
      bonus += 1
    elif normalized_kind == "flow_patch":
      bonus += 4
    return max(
      base + bonus,
      _minimum_update_step_limit(
        request_kind=normalized_kind,
        error_repair=error_repair,
        ui_interaction=ui_interaction,
      ),
    )
  error_repair = intent == "website_update" and is_error_repair_prompt(prompt)
  auth_flow = intent == "website_update" and is_auth_flow_update_prompt(prompt)
  ui_interaction = intent == "website_update" and is_ui_interaction_repair_prompt(prompt)
  has_chat_continuity = intent == "website_update" and prompt_already_has_update_continuity(prompt)
  scoped_update = (
    intent == "website_update"
    and not error_repair
    and not auth_flow
    and not ui_interaction
    and not has_chat_continuity
    and not worker_id
  )
  if error_repair or auth_flow or ui_interaction or has_chat_continuity:
    return max(
      _env_int("STREAMING_FILE_AGENT_MAX_STEPS", 10),
      _minimum_update_step_limit(
        request_kind=normalized_kind,
        error_repair=error_repair,
        auth_flow=auth_flow,
        ui_interaction=ui_interaction,
        has_chat_continuity=has_chat_continuity,
      ),
    )
  if scoped_update:
    return max(
      _env_int("STREAMING_FILE_AGENT_UPDATE_MAX_STEPS", 8),
      _minimum_update_step_limit(request_kind=normalized_kind),
    )
  if intent == "website_generation" and (
    "Greenfield build blueprint" in prompt or "Generation continuation required" in prompt
  ):
    return _env_int("STREAMING_FILE_AGENT_GREENFIELD_MAX_STEPS", 24)
  return _env_int("STREAMING_FILE_AGENT_MAX_STEPS", 12)


def select_system_instruction(*, intent: str, prompt: str) -> str:
  if intent == "website_update":
    if _unified_update_scope_enabled(intent=intent, worker_id=None):
      return UPDATE_SYSTEM_INSTRUCTION
    from .legacy_update_routing import select_legacy_system_instruction

    return select_legacy_system_instruction(prompt=prompt)
  return SYSTEM_INSTRUCTION


def _normalize_tool_path(raw_path: str) -> str:
  try:
    return normalize_artifact_path(raw_path)
  except ArtifactValidationError as exc:
    raise ToolExecutionError(
      f"{exc} Use paths like src/App.jsx, src/pages/Home.jsx, src/components/Navbar.jsx, or package.json."
    ) from exc


def _emit_assistant_delta(text: str, emit_progress: ProgressCallback) -> None:
  cleaned = str(text or "")
  if not cleaned.strip():
    return
  for index in range(0, len(cleaned), DELTA_CHUNK_SIZE):
    chunk = cleaned[index : index + DELTA_CHUNK_SIZE]
    emit_progress("assistant.delta", chunk, detail={"delta": chunk})


def _truncate_content(content: str, *, max_chars: int) -> tuple[str, bool]:
  if len(content) <= max_chars:
    return content, False
  return content[:max_chars] + f"\n\n...[truncated {len(content) - max_chars} chars]", True


def _mentioned_paths(prompt: str, paths: list[str]) -> list[str]:
  prompt_lower = prompt.lower()
  mentioned: list[str] = []
  for path in paths:
    if is_runtime_shim_path(path):
      continue
    base = path.rsplit("/", 1)[-1]
    if path.lower() in prompt_lower or base.lower() in prompt_lower:
      mentioned.append(path)
  return mentioned


def _load_memory_context_block(
  *,
  tool_context: Any,
  user: UserContext,
  project_id: str,
  prompt: str,
  chat_session_id: str | None = None,
  chat_topic_id: str | None = None,
  project_name: str = "",
  files: list[dict[str, Any]] | None = None,
  ideology_only: bool = False,
  chat_messages: list[dict[str, Any]] | None = None,
  enhancement_context: str = "",
  error_context: str = "",
) -> str:
  try:
    try:
      from ..memory.context import build_agent_flow_memory_block
    except ImportError:
      from agents.memory.context import build_agent_flow_memory_block
    return build_agent_flow_memory_block(
      tool_context.store,
      user,
      project_id=project_id,
      prompt=prompt,
      chat_session_id=chat_session_id,
      chat_topic_id=chat_topic_id,
      project_name=project_name,
      files=files,
      chat_messages=chat_messages,
      enhancement_context=enhancement_context,
      error_context=error_context,
      episodic_limit=4,
      ideology_only=ideology_only,
    )
  except Exception:
    return ""


def _collect_error_repair_diagnosis(
  *,
  prompt: str,
  files: list[dict[str, Any]],
) -> dict[str, Any]:
  raise_if_runtime_cancelled()
  try:
    try:
      from ..agent_runtime.error_handling import analyze_error_context
      from ..agent_runtime.update_analysis import build_update_code_search_matches
    except ImportError:
      from agents.agent_runtime.error_handling import analyze_error_context
      from agents.agent_runtime.update_analysis import build_update_code_search_matches
  except ImportError:
    return {"tool_files": [], "diagnosis": {}, "code_matches": [], "syntax_issues": []}

  tool_files = [
    {"path": str(item.get("path") or ""), "content": str(item.get("content") or "")}
    for item in files
    if isinstance(item, dict) and item.get("path") and not is_runtime_shim_path(str(item.get("path") or ""))
  ]
  code_matches = build_update_code_search_matches(prompt, tool_files)
  diagnosis = analyze_error_context(prompt, existing_files=tool_files, code_search_matches=code_matches)
  candidates = [path for path in (diagnosis.get("candidate_files") or []) if not is_runtime_shim_path(str(path))]
  syntax_issues = _diagnose_changed_source_files(
    [{"path": str(item.get("path") or ""), "content": str(item.get("content") or "")} for item in tool_files if str(item.get("path") or "") in set(candidates[:6])]
  )
  return {
    "tool_files": tool_files,
    "diagnosis": diagnosis,
    "code_matches": code_matches,
    "syntax_issues": syntax_issues,
  }


def _format_error_diagnosis_block(diagnosis_payload: dict[str, Any]) -> str:
  diagnosis = diagnosis_payload.get("diagnosis") or {}
  code_matches = diagnosis_payload.get("code_matches") or []
  syntax_issues = diagnosis_payload.get("syntax_issues") or []
  if not diagnosis:
    return ""
  lines = [
    "Error repair diagnosis (read these files first; do not scan the whole project):",
    f"- Categories: {', '.join(diagnosis.get('categories') or [])}",
    f"- Languages: {', '.join(diagnosis.get('languages') or [])}",
  ]
  hints = diagnosis.get("root_cause_hints") or []
  if hints:
    lines.append("- Root cause hints:")
    lines.extend(f"  • {hint}" for hint in hints[:4])
  candidates = [path for path in (diagnosis.get("candidate_files") or []) if not is_runtime_shim_path(str(path))]
  if candidates:
    lines.append("- Candidate files (fix here first): " + ", ".join(candidates[:4]))
  for match in code_matches[:3]:
    path = str(match.get("path") or "")
    if not path or is_runtime_shim_path(path):
      continue
    snippets = match.get("snippets") or []
    if snippets:
      lines.append(f"\n### Match snippet: {path}\n```\n{str(snippets[0])[:1800]}\n```")
  if syntax_issues:
    lines.append("- Quick syntax scan: " + "; ".join(syntax_issues[:4]))
  return "\n".join(lines)


def _emit_cumulative_staged_patch_diff(
  *,
  emit: ProgressCallback,
  intent: str,
  changed_paths: set[str],
  staged_files: dict[str, str],
  files_before_map: dict[str, str],
  persisted: bool = False,
) -> None:
  if intent != "website_update" or not changed_paths:
    return
  try:
    try:
      from ...code_diff import build_project_diff
    except ImportError:
      from code_diff import build_project_diff
    paths = sorted(changed_paths)
    before_files = [{"path": path, "content": files_before_map.get(path, "")} for path in paths]
    after_files = [{"path": path, "content": staged_files.get(path, files_before_map.get(path, ""))} for path in paths]
    diff_payload = build_project_diff(before_files, after_files, compare_mode="changed_only")
    if not diff_payload.get("file_count"):
      return
    emit(
      "patch.proposed",
      (
        f"Saved patch: {diff_payload.get('file_count', 0)} file(s)"
        if persisted
        else f"Staged patch: {diff_payload.get('file_count', 0)} file(s) (not saved yet)"
      ),
      status="completed" if persisted else "running",
      detail={**diff_payload, "staged": not persisted, "persisted": persisted},
    )
  except Exception:
    pass


def _format_scope_enrichment_block(
  *,
  scoped_target_paths: list[str],
  scope_enrichment_snippets: list[dict[str, str]],
  enrichment_profile: str,
  interaction_summary: str,
  scope_rationale: str,
  interaction: dict[str, str] | None = None,
) -> str:
  if not scope_enrichment_snippets and not scoped_target_paths:
    return ""
  snippet_lines: list[str] = []
  for item in scope_enrichment_snippets[:10]:
    path = str(item.get("path") or "")
    snippet = str(item.get("snippet") or "")
    kind = str(item.get("kind") or "context")
    if path and snippet:
      snippet_lines.append(f"### {path} [{kind}]\n{snippet[:1400]}")
  profile = str(enrichment_profile or "").strip().lower()
  interaction_obj = interaction if isinstance(interaction, dict) else {}
  component = str(interaction_obj.get("component") or "").strip()
  trigger = str(interaction_obj.get("trigger") or "").strip()
  expected = str(interaction_obj.get("expected") or "").strip()
  source_page = str(interaction_obj.get("source_page") or "").strip()
  target_page_or_route = str(interaction_obj.get("target_page_or_route") or "").strip()
  structured_issue = interaction_summary[:400] or scope_rationale[:400] or "fix broken UI handler wiring"
  if component or trigger or expected:
    structured_issue = (
      f"{component or 'UI element'}"
      f"{f' ({trigger})' if trigger else ''}"
      f"{f': {expected}' if expected else ''}"
      f"{f' | source: {source_page}' if source_page else ''}"
      f"{f' | target: {target_page_or_route}' if target_page_or_route else ''}"
    ).strip()
  if profile == "interaction_wiring" or str(interaction_summary or "").strip() or component:
    block = (
      f"Priority files from project memory/search: {', '.join(scoped_target_paths)}.\n"
      f"Interaction contract: {structured_issue}.\n"
      "Pre-loaded handler/UI context (start here, then inspect any related workspace files needed):\n"
    )
    if snippet_lines:
      block += "\n".join(snippet_lines) + "\n"
    block += (
      "Wire the real trigger to the expected behavior using the app's existing state, handler, "
      "router, or navigation pattern. If the route/source owner is missing, use list_files/read_file "
      "to locate it and patch the relevant workspace file directly. Avoid unrelated rewrites.\n\n"
    )
    return block
  if snippet_lines:
    return (
      f"Priority files from project memory/search: {', '.join(scoped_target_paths)}.\n"
      f"Resolution rationale: {scope_rationale[:400] or 'memory + codebase retrieval + LLM update analysis'}.\n"
      "Pre-loaded project context:\n"
      + "\n".join(snippet_lines)
      + "\nApply minimal str_replace edits on the files that actually own the requested behavior; inspect related files if needed.\n\n"
    )
  return ""


def build_project_context_block(
  *,
  project_id: str,
  tool_context: Any,
  user: UserContext,
  prompt: str,
  char_budget: int = CONTEXT_CHAR_BUDGET,
  intent: str = "",
  chat_session_id: str | None = None,
  chat_topic_id: str | None = None,
  project_name: str = "",
  scoped_priority_paths: list[str] | None = None,
) -> str:
  files = tool_context.store.list_files(project_id, user)
  try:
    from ..project_workspace import is_greenfield_codebase, is_scaffold_only_codebase, meaningful_project_source_files
  except ImportError:
    from agents.project_workspace import is_greenfield_codebase, is_scaffold_only_codebase, meaningful_project_source_files
  meaningful_files = meaningful_project_source_files(files)
  scaffold_only = intent == "website_generation" and is_scaffold_only_codebase(files)
  greenfield = (is_greenfield_codebase(files) or scaffold_only) and intent in {"website_generation", "simple_code"}
  paths = [
    str(item.get("path") or "")
    for item in files
    if isinstance(item, dict) and item.get("path") and not is_runtime_shim_path(str(item.get("path") or ""))
  ]
  error_repair = intent == "website_update" and is_error_repair_prompt(prompt)
  unified_scope = _unified_update_scope_enabled(intent=intent, worker_id=None)
  if unified_scope:
    auth_flow_update = False
    ui_interaction_update = False
    error_repair = False
    has_chat_continuity = intent == "website_update" and prompt_already_has_update_continuity(prompt)
    scoped_update = False
  else:
    auth_flow_update = intent == "website_update" and is_auth_flow_update_prompt(prompt)
    ui_interaction_update = intent == "website_update" and is_ui_interaction_repair_prompt(prompt)
    has_chat_continuity = intent == "website_update" and prompt_already_has_update_continuity(prompt)
    scoped_update = intent == "website_update" and not error_repair and not auth_flow_update and not ui_interaction_update and not has_chat_continuity
  char_budget = UPDATE_CONTEXT_CHAR_BUDGET if scoped_update else CONTEXT_CHAR_BUDGET
  inline_file_max_chars = UPDATE_INLINE_FILE_MAX_CHARS if scoped_update else INLINE_FILE_MAX_CHARS
  priority_file_max_chars = UPDATE_PRIORITY_FILE_MAX_CHARS if scoped_update else inline_file_max_chars
  mentioned = _mentioned_paths(prompt, paths)
  priority_paths = mentioned[:3] if scoped_update else mentioned[:6]
  diagnosis_block = ""
  diagnosis_payload: dict[str, Any] = {}
  files_map = {
    str(item.get("path") or ""): str(item.get("content") or "")
    for item in files
    if isinstance(item, dict) and item.get("path")
  }
  if error_repair:
    diagnosis_payload = _collect_error_repair_diagnosis(prompt=prompt, files=files if isinstance(files, list) else [])
    diagnosis_block = _format_error_diagnosis_block(diagnosis_payload)
    for candidate in (diagnosis_payload.get("diagnosis") or {}).get("candidate_files") or []:
      candidate_path = str(candidate)
      if candidate_path and candidate_path not in priority_paths and candidate_path in paths:
        priority_paths.append(candidate_path)
    priority_paths = priority_paths[:4]
  elif scoped_priority_paths:
    priority_paths = [path for path in scoped_priority_paths if path in paths][:6]
  elif scoped_update or auth_flow_update or ui_interaction_update:
    try:
      from .task_planner import resolve_scoped_target_paths
    except ImportError:
      from agents.streaming.task_planner import resolve_scoped_target_paths
    priority_paths = resolve_scoped_target_paths(prompt, paths=paths, files_map=files_map)[
      : (4 if auth_flow_update or ui_interaction_update else 3)
    ]
  if not priority_paths and not scoped_update:
    priority_paths = [path for path in paths if path.endswith(("App.jsx", "main.jsx", "index.html"))][:4]
  if not priority_paths and not scoped_update:
    priority_paths = paths[:4]

  lines = [
    f"Project id: {project_id}",
    f"File count: {len(paths)}",
  ]
  if scaffold_only:
    lines.extend(
      [
        "SCAFFOLD-ONLY PROJECT: platform Vite config files exist but no pages/components yet.",
        "Create all pages, components, routes, and app logic per the build blueprint.",
        "Do not stop after config files — the user expects a complete working application.",
      ]
    )
  elif greenfield:
    lines.extend(
      [
        "GREENFIELD PROJECT: this workspace has no existing application source code.",
        "Do not list_dir or read src/pages, src/components, or other folders from prior projects.",
        "Create a fresh Vite + React scaffold from scratch for the user request.",
      ]
    )
  memory_block = _load_memory_context_block(
    tool_context=tool_context,
    user=user,
    project_id=project_id,
    prompt=prompt,
    chat_session_id=chat_session_id,
    chat_topic_id=chat_topic_id,
    project_name=project_name,
    files=meaningful_files if greenfield else (files if isinstance(files, list) else None),
    ideology_only=greenfield,
    error_context=diagnosis_block if error_repair else "",
  )
  if memory_block:
    lines.append(memory_block)
  if diagnosis_block:
    lines.append(diagnosis_block)
  if intent == "website_update" and priority_paths:
    lines.append(
      "The priority snippets below were selected from project memory, code search, or the current prompt. "
      "Start with them, but inspect any relevant live workspace file needed to complete the update."
    )
  elif paths:
    lines.append(
      "The files below are the user's current live project snapshot (including manual edits). "
      "Treat them as source of truth and read files again with tools before editing."
    )
  if intent == "website_update" and priority_paths:
    lines.append("Priority update files: " + ", ".join(priority_paths))
    lines.append("These are not a hard scope; use list_files/read_file for related files when the update requires them.")
  elif paths:
    lines.append("Paths: " + ", ".join(paths[:50 if scoped_update else 80]) + ("..." if len(paths) > (50 if scoped_update else 80) else ""))
  remaining = char_budget - len("\n".join(lines))
  for path in priority_paths:
    if remaining <= 0:
      break
    for item in files:
      if not isinstance(item, dict) or str(item.get("path") or "") != path:
        continue
      content, truncated = _truncate_content(
        str(item.get("content") or ""),
        max_chars=min(priority_file_max_chars if scoped_update else inline_file_max_chars, remaining),
      )
      suffix = " (truncated)" if truncated else ""
      block = f"\n\n### {path}{suffix}\n```\n{content}\n```"
      lines.append(block)
      remaining -= len(block)
      break
  return "\n".join(lines)


def _file_content_map(tool_context: Any, user: UserContext, project_id: str, staged: dict[str, str]) -> dict[str, str]:
  merged = {
    str(item.get("path") or ""): str(item.get("content") or "")
    for item in tool_context.store.list_files(project_id, user)
    if isinstance(item, dict) and item.get("path")
  }
  merged.update(staged)
  return merged


def _diagnose_changed_source_files(files: list[dict[str, str]]) -> list[str]:
  issues: list[str] = []
  for item in files:
    path = str(item.get("path") or "")
    if not path.endswith((".jsx", ".tsx", ".js", ".ts")):
      continue
    code = str(item.get("content") or "")
    if not code.strip():
      issues.append(f"{path}: file is empty")
      continue
    if code.count("{") != code.count("}"):
      issues.append(f"{path}: unbalanced '{{' / '}}' braces")
    if code.count("(") != code.count(")"):
      issues.append(f"{path}: unbalanced '(' / ')' parentheses")
    if code.count("[") != code.count("]"):
      issues.append(f"{path}: unbalanced '[' / ']' brackets")
  return issues


def _build_generated_website(
  files: list[dict[str, str]],
  *,
  summary: str,
  title: str | None = None,
) -> dict[str, Any]:
  artifact_files = [
    {"path": item["path"], "purpose": "Updated by streaming file agent.", "code": item["content"]}
    for item in files
    if item.get("path")
  ]
  title_match = re.search(r"<title>([^<]+)</title>", files[0]["content"], re.IGNORECASE) if files else None
  resolved_title = (
    str(title or "").strip()
    or (title_match.group(1).strip() if title_match else "")
    or "Generated Website"
  )
  headline = summary.strip()[:120] if summary.strip() else resolved_title
  return {
    "title": resolved_title,
    "headline": headline,
    "subheadline": summary.strip() or "Website updated from your prompt.",
    "primary_cta": "Preview site",
    "secondary_cta": "Edit files",
    "preview_html": "",
    "sections": [
      {
        "name": "Hero",
        "purpose": "Introduce the generated website.",
        "content": summary.strip() or "Website generated from the user prompt.",
        "items": ["Headline", "Subheadline", "Primary CTA"],
      }
    ],
    "files": artifact_files,
  }


def _visual_qa_contract_status(visual_qa_result: dict[str, Any] | None) -> str:
  if not isinstance(visual_qa_result, dict):
    return "skipped"
  code = str(visual_qa_result.get("code") or "").strip()
  if code == "visual_qa_timeout":
    return "inconclusive"
  if visual_qa_result.get("advisory") is True:
    return "advisory"
  status = str(visual_qa_result.get("status") or "").strip().lower()
  if status == "passed":
    return "passed"
  if status == "failed":
    return "failed"
  return status or "unknown"


def _streaming_run_state(
  *,
  intent: str,
  persisted_files: list[dict[str, Any]],
  empty_update: bool,
  requirement_failed: bool,
  build_gate_result: dict[str, Any] | None,
  visual_qa_result: dict[str, Any] | None,
  loop_status: str,
) -> str:
  if intent == "website_update":
    if empty_update:
      return "update_failed_no_changes"
    if requirement_failed:
      return "update_failed_requirement_not_met"
    if persisted_files:
      visual_status = _visual_qa_contract_status(visual_qa_result)
      if visual_status == "passed":
        return "update_saved_preview_ready"
      if visual_status == "inconclusive":
        return "update_saved_qa_inconclusive"
      if visual_status in {"advisory", "failed"}:
        return "update_saved_qa_advisory"
      build_status = str((build_gate_result or {}).get("status") or "").strip().lower()
      if build_status == "ready":
        return "update_saved_preview_ready"
      return "update_saved_preview_ready" if not build_status else "update_saved_qa_inconclusive"
    return "update_failed_no_changes"
  if intent == "website_generation":
    return "generation_completed" if persisted_files and loop_status != "failed" else "generation_failed"
  if intent == "simple_code":
    return "generation_completed" if persisted_files else "runtime_failed"
  return "runtime_failed" if loop_status == "failed" else "generation_completed"


def derive_error_repair_scope_paths(
  *,
  prompt: str,
  files: list[dict[str, Any]],
  build_log: str = "",
  max_paths: int = 4,
) -> list[str]:
  scoped_paths: list[str] = []
  existing_paths = {
    str(item.get("path") or "").replace("\\", "/")
    for item in files
    if isinstance(item, dict) and item.get("path")
  }

  if build_log:
    try:
      from .build_gate import parse_build_error_paths
    except ImportError:
      from agents.streaming.build_gate import parse_build_error_paths
    scoped_paths.extend(parse_build_error_paths(build_log, max_paths=max_paths))

  if len(scoped_paths) < max_paths:
    diagnosis_payload = _collect_error_repair_diagnosis(prompt=prompt, files=files)
    for candidate in (diagnosis_payload.get("diagnosis") or {}).get("candidate_files") or []:
      scoped_paths.append(str(candidate or ""))
      if len(scoped_paths) >= max_paths:
        break

  normalized: list[str] = []
  for raw_path in scoped_paths:
    path = str(raw_path or "").replace("\\", "/").strip()
    if path.startswith("./"):
      path = path[2:]
    if path.startswith("/"):
      path = path[1:]
    if not path or is_runtime_shim_path(path) or path not in existing_paths or path in normalized:
      continue
    normalized.append(path)
    if len(normalized) >= max_paths:
      break
  return normalized


def run_streaming_file_agent(
  *,
  project_id: str,
  user: UserContext,
  tool_context: Any,
  prompt: str,
  intent: str,
  artifact_provider: Any,
  emit_progress: ProgressCallback,
  max_steps: int | None = None,
  attachments: list[dict[str, Any]] | None = None,
  allowed_write_paths: frozenset[str] | set[str] | None = None,
  persist_to_store: bool = True,
  skip_workspace_pull: bool = False,
  file_resolver_override: Callable[[str], str] | None = None,
  on_file_staged: Callable[[str, str], None] | None = None,
  worker_id: str | None = None,
  skip_build_gate: bool = False,
  chat_session_id: str | None = None,
  chat_topic_id: str | None = None,
  project_name: str = "",
  patch_action: str | None = None,
  agent_run_id: str | None = None,
  generation_plan: dict[str, Any] | None = None,
  confirmation_brief: dict[str, Any] | None = None,
  target_resolution: dict[str, Any] | None = None,
) -> dict[str, Any]:
  try:
    from ..prompt_context import current_user_prompt
  except ImportError:
    from agents.prompt_context import current_user_prompt

  prompt = current_user_prompt(prompt)
  target_resolution = target_resolution if isinstance(target_resolution, dict) else {}
  if intent == "website_update" and chat_session_id:
    prompt = _merge_prompt_with_chat_continuity(
      prompt,
      tool_context=tool_context,
      user=user,
      project_id=project_id,
      chat_session_id=chat_session_id,
      chat_topic_id=chat_topic_id,
    )
  has_chat_continuity = intent == "website_update" and prompt_already_has_update_continuity(prompt)
  staged_files: dict[str, str] = {}
  changed_paths: set[str] = set()
  effective_allowed_write_paths = frozenset(allowed_write_paths) if allowed_write_paths is not None else None
  unified_scope = _unified_update_scope_enabled(intent=intent, worker_id=worker_id)
  resolved_scope = None
  scope_rationale = ""
  scope_target_files: list[str] = []
  scope_reference_files: list[str] = []
  scope_new_files: list[str] = []
  scope_request_kind = ""
  scope_update_mode = ""
  style_reference_snippets: list[dict[str, str]] = []
  scope_enrichment_snippets: list[dict[str, str]] = []
  enrichment_profile = ""
  interaction_summary = ""
  scope_interaction: dict[str, str] = {}
  if unified_scope:
    # The update analyzer below provides project-memory/search guidance. It is
    # not a hard scoped-patch cage; the agent may inspect/edit any relevant
    # workspace file needed for the requested update.
    error_repair = False
    auth_flow_update = False
    ui_interaction_update = False
    scoped_update = False
  else:
    error_repair = intent == "website_update" and is_error_repair_prompt(prompt)
    auth_flow_update = intent == "website_update" and is_auth_flow_update_prompt(prompt)
    ui_interaction_update = intent == "website_update" and is_ui_interaction_repair_prompt(prompt)
    scoped_update = (
      intent == "website_update"
      and not error_repair
      and not auth_flow_update
      and not ui_interaction_update
      and not has_chat_continuity
      and not worker_id
    )
  last_local_sync: dict[str, Any] | None = None
  tool_failures: list[str] = []

  def emit(step: str, message: str, **kwargs: Any) -> None:
    emit_progress(step, message, **kwargs)

  scoped_target_paths: list[str] = []
  if unified_scope and not error_repair:
    try:
      from ..update_engine.scope_engine import resolve_update_scope
      from .streaming_parity import clarification_stream_result

      project_files = tool_context.store.list_files(project_id, user)
      resolved_scope = resolve_update_scope(
        prompt=prompt,
        project_files=project_files,
        control_provider=artifact_provider,
        store=tool_context.store,
        user=user,
        project_id=project_id,
        chat_session_id=chat_session_id,
        chat_topic_id=chat_topic_id,
        project_name=project_name,
        emit_progress=emit,
      )
      if resolved_scope.update_mode == "needs_clarification" and not resolved_scope.candidate_files:
        question = str(
          resolved_scope.clarification_question
          or "Please specify which page, component, or file to update and what should change."
        )
        return clarification_stream_result(question)
      scope_new_files = list(resolved_scope.candidate_new_files or [])
      scoped_target_paths = list(dict.fromkeys([*resolved_scope.candidate_files, *scope_new_files]))[:8]
      scope_rationale = str(resolved_scope.scope_rationale or "")
      scope_target_files = list(resolved_scope.target_files or [])
      scope_reference_files = list(resolved_scope.reference_files or [])
      scope_request_kind = str(resolved_scope.request_kind or "")
      scope_update_mode = str(resolved_scope.update_mode or "")
      style_reference_snippets = list(resolved_scope.style_reference_snippets or [])
      scope_enrichment_snippets = list(resolved_scope.scope_enrichment_snippets or [])
      enrichment_profile = str(resolved_scope.enrichment_profile or "")
      interaction_summary = str(resolved_scope.interaction_summary or "")
      scope_interaction = dict(resolved_scope.interaction or {})
      ui_interaction_update = (
        scope_request_kind == "interaction_wiring_update"
        or enrichment_profile == "interaction_wiring"
      )
      error_repair = scope_update_mode == "bug_fix" and not ui_interaction_update
      auth_flow_update = scope_request_kind == "flow_patch"
      if auth_flow_update:
        scoped_update = False
      if scope_target_files:
        scoped_target_paths = list(dict.fromkeys([*scope_target_files, *scope_reference_files, *scope_new_files]))[:8]
      resolved_target_files = [
        str(path).strip()
        for path in (target_resolution.get("resolved_files") or [])
        if str(path).strip()
      ]
      if resolved_target_files:
        scoped_target_paths = list(dict.fromkeys([*resolved_target_files, *scoped_target_paths]))[:8]
        scope_target_files = list(dict.fromkeys([*resolved_target_files, *scope_target_files]))[:8]
    except Exception:
      raise_if_runtime_cancelled()
      pass
  elif scoped_update:
    try:
      from .update_preflight import parallel_update_preflight_active, run_parallel_update_preflight
      from .streaming_parity import (
        clarification_stream_result,
        try_deterministic_module_contract_fix_streaming,
        try_deterministic_scoped_patch_streaming,
        try_deterministic_undefined_reference_fix_streaming,
      )

      if parallel_update_preflight_active(intent=intent):
        project_files = tool_context.store.list_files(project_id, user)
        preflight = run_parallel_update_preflight(
          prompt=prompt,
          project_files=project_files,
          control_provider=artifact_provider,
          store=tool_context.store if tool_context is not None else None,
          user=user,
          project_id=project_id,
          chat_session_id=chat_session_id,
          chat_topic_id=chat_topic_id,
          project_name=project_name,
        )
        update_analysis = preflight.get("update_analysis") if isinstance(preflight.get("update_analysis"), dict) else None
        if isinstance(update_analysis, dict) and update_analysis.get("update_mode") == "needs_clarification":
          question = str(
            update_analysis.get("clarification_question")
            or "Please specify which page, component, or file to update and what should change."
          )
          return clarification_stream_result(question)
        if isinstance(update_analysis, dict):
          scoped_result = try_deterministic_module_contract_fix_streaming(
            prompt=prompt,
            tool_context=tool_context,
            user=user,
            project_id=project_id,
            emit_progress=emit,
            patch_action=patch_action,
            chat_session_id=chat_session_id,
            agent_run_id=agent_run_id,
          )
          if scoped_result is not None:
            return scoped_result
          scoped_result = try_deterministic_undefined_reference_fix_streaming(
            prompt=prompt,
            tool_context=tool_context,
            user=user,
            project_id=project_id,
            intent=intent,
            artifact_provider=artifact_provider,
            emit_progress=emit,
            update_analysis=update_analysis,
            patch_action=patch_action,
            chat_session_id=chat_session_id,
            project_name=project_name,
          )
          if scoped_result is not None:
            return scoped_result
          scoped_result = try_deterministic_scoped_patch_streaming(
            update_analysis=update_analysis,
            tool_context=tool_context,
            user=user,
            project_id=project_id,
            prompt=prompt,
            intent=intent,
            artifact_provider=artifact_provider,
            emit_progress=emit,
            patch_action=patch_action,
            chat_session_id=chat_session_id,
            project_name=project_name,
          )
          if scoped_result is not None:
            return scoped_result
    except Exception:
      raise_if_runtime_cancelled()
      pass

  workspace_sync: dict[str, Any] = {}
  if not skip_workspace_pull:
    raise_if_runtime_cancelled()
    workspace_sync = pull_linked_workspace_to_store(
      tool_context,
      user,
      project_id=project_id,
      source="streaming_file_agent",
    )
    raise_if_runtime_cancelled()
  files_before_map = _file_content_map(tool_context, user, project_id, {})
  if workspace_sync.get("local_sync"):
    last_local_sync = workspace_sync["local_sync"]
    emit(
      "local.sync.completed",
      f"Loaded {workspace_sync.get('file_count', 0)} files from linked local folder",
      status="completed",
      detail=last_local_sync,
    )

  if error_repair:
    try:
      from .streaming_parity import (
        try_deterministic_module_contract_fix_streaming,
        try_deterministic_undefined_reference_fix_streaming,
      )

      quick_fix = try_deterministic_module_contract_fix_streaming(
        prompt=prompt,
        tool_context=tool_context,
        user=user,
        project_id=project_id,
        emit_progress=emit,
        patch_action=patch_action,
        chat_session_id=chat_session_id,
        agent_run_id=agent_run_id,
      )
      if quick_fix is not None:
        return quick_fix

      quick_fix = try_deterministic_undefined_reference_fix_streaming(
        prompt=prompt,
        tool_context=tool_context,
        user=user,
        project_id=project_id,
        intent=intent,
        artifact_provider=artifact_provider,
        emit_progress=emit,
        patch_action=patch_action,
        chat_session_id=chat_session_id,
        project_name=project_name,
      )
      if quick_fix is not None:
        return quick_fix
    except Exception:
      raise_if_runtime_cancelled()
      pass

  system_instruction = select_system_instruction(intent=intent, prompt=prompt)
  if not scoped_target_paths and scoped_update and not unified_scope:
    store_files = tool_context.store.list_files(project_id, user)
    scope_paths = [
      str(item.get("path") or "")
      for item in store_files
      if isinstance(item, dict) and item.get("path") and not is_runtime_shim_path(str(item.get("path") or ""))
    ]
    scope_map = {
      str(item.get("path") or ""): str(item.get("content") or "")
      for item in store_files
      if isinstance(item, dict) and item.get("path")
    }
    try:
      from .task_planner import resolve_scoped_target_paths
    except ImportError:
      from agents.streaming.task_planner import resolve_scoped_target_paths
    scoped_target_paths = resolve_scoped_target_paths(prompt, paths=scope_paths, files_map=scope_map)[:3]

  def shim_edit_error(path: str) -> str:
    return (
      f"Do not edit runtime shim {path}. Fix the importing src/pages or src/components file instead, "
      "or use write_file on the app source after read_file."
    )

  def persist_file_live(path: str, content: str) -> dict[str, str]:
    raise_if_runtime_cancelled()
    file_item = {"path": path, "content": content}
    if on_file_staged:
      on_file_staged(path, content)
    return file_item

  def emit_file_written(path: str, content: str, *, action: str = "write_file", line_detail: dict[str, Any] | None = None) -> None:
    if intent in {"website_generation", "website_update"}:
      try:
        from .syntax_guard import guard_syntax_write
      except ImportError:
        from agents.streaming.syntax_guard import guard_syntax_write
      blocked = guard_syntax_write(path, content)
      if blocked:
        tool_failures.append(str(blocked.get("error") or "syntax blocked"))
        emit(
          "tool.write_file" if action == "write_file" else "tool.str_replace",
          str(blocked.get("error") or "syntax blocked"),
          status="completed",
          detail=blocked,
        )
        return
    file_item = persist_file_live(path, content)
    location = tool_location_detail(
      path=path,
      action="write" if action == "write_file" else "edit",
      tool=action,
      **(line_detail or {}),
    )
    location.update(source_symbol_for_line(content, location.get("start_line") or 1))
    location["file"] = file_item
    location["files"] = [file_item]
    emit(
      "tool.write_file" if action == "write_file" else "tool.str_replace",
      f"Writing {path}" if action == "write_file" else f"Updated {path}",
      detail=location,
    )
    emit(
      "file.written",
      f"Added {path}",
      status="completed",
      detail={
        **location,
        "incremental": True,
        "file_index": len(changed_paths),
        "local_sync": last_local_sync,
      },
    )

  def resolve_content(path: str) -> str:
    if file_resolver_override is not None:
      return file_resolver_override(path)
    if path in staged_files:
      return staged_files[path]
    payload = read_file_tool(tool_context, user, {"project_id": project_id, "path": path})
    return str(payload.get("content") or "")

  def path_write_allowed(path: str) -> bool:
    return effective_allowed_write_paths is None or path in effective_allowed_write_paths

  def worker_readable_paths() -> frozenset[str]:
    if effective_allowed_write_paths is None:
      return frozenset()
    readable = set(effective_allowed_write_paths)
    known = set(files_before_map.keys()) | set(staged_files.keys())
    try:
      from .task_planner import _import_dependencies
    except ImportError:
      from agents.streaming.task_planner import _import_dependencies
    for path in effective_allowed_write_paths:
      content = staged_files.get(path) or files_before_map.get(path, "")
      if not content:
        try:
          content = resolve_content(path)
        except Exception:
          content = ""
      for imported in _import_dependencies(path, content, known):
        readable.add(imported)
    if any(str(item).startswith(("src/pages/", "src/components/")) for item in effective_allowed_write_paths):
      if "src/App.jsx" in known:
        readable.add("src/App.jsx")
    return frozenset(readable)

  def execute_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    raise_if_runtime_cancelled()
    normalized = str(name or "").strip().lower()
    args = arguments if isinstance(arguments, dict) else {}

    if normalized == "read_file":
      raw_path = required_string(args, "path")
      if _is_secret_env_path(raw_path):
        safe_path = _env_example_path_for(raw_path)
        message = f"Read blocked: {raw_path} can contain secrets. Use {safe_path} with placeholder values instead."
        emit(
          "tool.read_file",
          message,
          status="completed",
          detail={"path": raw_path, "safe_path": safe_path, "error": message, "recoverable": True},
        )
        return {"error": message, "path": raw_path, "safe_path": safe_path, "recoverable": True}
      path = _normalize_tool_path(raw_path)
      if effective_allowed_write_paths is not None:
        readable = worker_readable_paths()
        if path not in readable:
          message = (
            f"Read blocked: {path} is outside your assigned scope. "
            f"Use inline snippets or read only: {', '.join(sorted(readable))}."
          )
          emit(
            "tool.read_file",
            message,
            status="completed",
            detail={"path": path, "error": message, "recoverable": True, "scoped": True},
          )
          return {"error": message, "path": path, "recoverable": True}
      emit(
        "tool.read_file",
        f"Reading {path}",
        detail=tool_location_detail(path=path, action="read", tool="read_file"),
      )
      content = resolve_content(path)
      truncated, was_truncated = _truncate_content(content, max_chars=TOOL_READ_MAX_CHARS)
      start_line, end_line = read_range_for_content(content, truncated=was_truncated, visible_content=truncated)
      result = {"project_id": project_id, "path": path, "content": truncated, "size": len(content)}
      if was_truncated:
        result["truncated"] = True
        result["start_line"] = start_line
        result["end_line"] = end_line
      emit(
        "tool.read_file",
        f"Read {path} L{start_line}-{end_line}",
        status="completed",
        detail=tool_location_detail(
          path=path,
          action="read",
          start_line=start_line,
          end_line=end_line,
          tool="read_file",
          size=len(content),
          truncated=was_truncated,
          **source_symbol_for_line(content, start_line),
        ),
      )
      return result

    if normalized == "list_files":
      prefix = str(args.get("path") or "").strip()
      if effective_allowed_write_paths is not None:
        readable = worker_readable_paths()
        entries = [{"path": path, "type": "file"} for path in sorted(readable)]
        emit(
          "tool.list_files",
          f"Worker-scoped file list ({len(entries)} paths)",
          status="completed",
          detail={"path": prefix or ".", "tool": "list_files", "entries": entries, "scoped": True},
        )
        return {"project_id": project_id, "entries": entries, "scoped": True}
      if scoped_update and scoped_target_paths and prefix in {"", ".", "./"}:
        entries = [{"path": path, "type": "file"} for path in scoped_target_paths]
        emit(
          "tool.list_files",
          f"Scoped file list ({len(entries)} targets)",
          status="completed",
          detail={"path": prefix or ".", "tool": "list_files", "entries": entries, "scoped": True},
        )
        return {"project_id": project_id, "entries": entries, "scoped": True}
      emit("tool.list_files", f"Listing {prefix or '.'}", detail={"path": prefix or ".", "tool": "list_files"})
      result = list_dir_tool(tool_context, user, {"project_id": project_id, "path": prefix})
      emit(
        "tool.list_files",
        f"Listed {len(result.get('entries') or [])} entries under {prefix or '.'}",
        status="completed",
        detail={"path": prefix or ".", "entries": result.get("entries") or []},
      )
      return result

    if normalized == "search_codebase":
      query = required_string(args, "query")
      limit = int(args.get("limit") or 8)
      limit = max(1, min(limit, 12))
      emit(
        "tool.search_codebase",
        f"Searching codebase for: {query[:120]}",
        detail={"query": query, "tool": "search_codebase"},
      )
      project_files = [
        {"path": path, "content": staged_files.get(path) or files_before_map.get(path, "")}
        for path in sorted(set(files_before_map.keys()) | set(staged_files.keys()))
      ]
      for path in scoped_target_paths:
        if path not in {item["path"] for item in project_files}:
          try:
            content = resolve_content(path)
          except Exception:
            content = ""
          project_files.append({"path": path, "content": content})
      try:
        from ..update_engine.tools import search_codebase_matches
      except ImportError:
        from agents.update_engine.tools import search_codebase_matches
      matches = search_codebase_matches(query=query, project_files=project_files, limit=limit)
      emit(
        "tool.search_codebase",
        f"Found {len(matches)} codebase match(es)",
        status="completed",
        detail={"query": query, "matches": matches, "tool": "search_codebase"},
      )
      return {"project_id": project_id, "query": query, "matches": matches, "count": len(matches)}

    if normalized == "write_file":
      raw_path = required_string(args, "path")
      if _is_secret_env_path(raw_path):
        safe_path = _env_example_path_for(raw_path)
        emit(
          "tool.write_file",
          f"Redirecting secret env write from {raw_path} to {safe_path}",
          status="completed",
          detail={"requested_path": raw_path, "path": safe_path, "safe_path": safe_path, "redirected": True},
        )
        raw_path = safe_path
      path = _normalize_tool_path(raw_path)
      if not path_write_allowed(path):
        message = f"This worker may only edit: {', '.join(sorted(effective_allowed_write_paths or []))}."
        emit("tool.write_file", message, status="completed", detail={"path": path, "error": message, "recoverable": True})
        return {"error": message, "path": path, "recoverable": True}
      if is_runtime_shim_path(path):
        message = shim_edit_error(path)
        tool_failures.append(message)
        emit("tool.write_file", message, status="completed", detail={"path": path, "error": message, "recoverable": True})
        return {"error": message, "path": path, "recoverable": True}
      content = required_string(args, "content")
      if intent == "website_update":
        try:
          from .update_write_guard import guard_streaming_file_write
        except ImportError:
          from agents.streaming.update_write_guard import guard_streaming_file_write
        previous_content = staged_files.get(path, files_before_map.get(path, ""))
        blocked = guard_streaming_file_write(
          path,
          content,
          previous_content,
          update_mode=scope_update_mode or None,
          request_kind=scope_request_kind or None,
          prompt=prompt,
          via_write_file=True,
          intent=intent,
        )
        if blocked:
          tool_failures.append(str(blocked.get("error") or "blocked rewrite"))
          emit("tool.write_file", str(blocked.get("error") or "blocked rewrite"), status="completed", detail=blocked)
          return blocked
      try:
        from .syntax_guard import guard_syntax_write
      except ImportError:
        from agents.streaming.syntax_guard import guard_syntax_write
      syntax_blocked = guard_syntax_write(path, content)
      if syntax_blocked:
        tool_failures.append(str(syntax_blocked.get("error") or "syntax blocked"))
        emit("tool.write_file", str(syntax_blocked.get("error") or "syntax blocked"), status="completed", detail=syntax_blocked)
        return syntax_blocked
      staged_files[path] = content
      changed_paths.add(path)
      line_total = max(1, content.count("\n") + (1 if content else 0))
      emit_file_written(path, content, action="write_file", line_detail={"start_line": 1, "end_line": line_total, "added": line_total})
      return {"project_id": project_id, "path": path, "status": "staged", "size": len(content)}

    if normalized == "str_replace":
      raw_path = required_string(args, "path")
      if _is_secret_env_path(raw_path):
        safe_path = _env_example_path_for(raw_path)
        message = f"Edit blocked: {raw_path} can contain secrets. Create or update {safe_path} with placeholders instead."
        emit(
          "tool.str_replace",
          message,
          status="completed",
          detail={"path": raw_path, "safe_path": safe_path, "error": message, "recoverable": True},
        )
        return {"error": message, "path": raw_path, "safe_path": safe_path, "recoverable": True}
      path = _normalize_tool_path(raw_path)
      if not path_write_allowed(path):
        message = f"This worker may only edit: {', '.join(sorted(effective_allowed_write_paths or []))}."
        emit("tool.str_replace", message, status="completed", detail={"path": path, "error": message, "recoverable": True})
        return {"error": message, "path": path, "recoverable": True}
      if is_runtime_shim_path(path):
        message = shim_edit_error(path)
        tool_failures.append(message)
        emit("tool.str_replace", message, status="completed", detail={"path": path, "error": message, "recoverable": True})
        return {"error": message, "path": path, "recoverable": True}
      old_string = required_string(args, "old_string")
      new_string = args.get("new_string")
      if not isinstance(new_string, str):
        raise ToolExecutionError("new_string must be a string.")
      emit("tool.str_replace", f"Applying edit to {path}", detail=tool_location_detail(path=path, action="edit", tool="str_replace"))
      try:
        current = resolve_content(path)
        if intent == "website_update":
          try:
            from ..platform_file_locks import guard_locked_platform_write
          except ImportError:
            from agents.platform_file_locks import guard_locked_platform_write
          locked = guard_locked_platform_write(
            path,
            intent=intent,
            previous_content=current if current.strip() else files_before_map.get(path, ""),
            request_kind=scope_request_kind or "",
          )
          if locked:
            tool_failures.append(str(locked.get("error") or "locked platform file"))
            emit("tool.str_replace", str(locked.get("error") or "locked platform file"), status="completed", detail=locked)
            return locked
        occurrences = current.count(old_string)
        if occurrences == 0:
          raise ToolExecutionError(f"Could not find exact old_string in {path}.")
        if occurrences > 1:
          raise ToolExecutionError(
            f"old_string matched {occurrences} times in {path}. Provide a more specific old_string."
          )
        start_line, end_line = line_range_for_substring(current, old_string)
        added, removed = line_delta_for_replace(old_string, new_string)
        updated = current.replace(old_string, new_string, 1)
        if intent in {"website_generation", "website_update"}:
          try:
            from .syntax_guard import guard_syntax_write
          except ImportError:
            from agents.streaming.syntax_guard import guard_syntax_write
          syntax_blocked = guard_syntax_write(path, updated)
          if syntax_blocked:
            tool_failures.append(str(syntax_blocked.get("error") or "syntax blocked"))
            emit("tool.str_replace", str(syntax_blocked.get("error") or "syntax blocked"), status="completed", detail=syntax_blocked)
            return syntax_blocked
        staged_files[path] = updated
        changed_paths.add(path)
        emit(
          "tool.str_replace",
          f"Edited {path} L{start_line}-{end_line} (+{added}/-{removed})",
          status="completed",
          detail={
            **tool_location_detail(
              path=path,
              action="edit",
              start_line=start_line,
              end_line=end_line,
              added=added,
              removed=removed,
              tool="str_replace",
              replacements=1,
              **source_symbol_for_line(current, start_line),
            ),
            "staged": True,
            "persisted": False,
          },
        )
        _emit_cumulative_staged_patch_diff(
          emit=emit,
          intent=intent,
          changed_paths=changed_paths,
          staged_files=staged_files,
          files_before_map=files_before_map,
          persisted=False,
        )
        emit_file_written(
          path,
          updated,
          action="str_replace",
          line_detail={"start_line": start_line, "end_line": end_line, "added": added, "removed": removed},
        )
        return {
          "project_id": project_id,
          "path": path,
          "status": "staged",
          "size": len(updated),
          "replacements": 1,
        }
      except ToolExecutionError as exc:
        message = (
          f"{exc} Re-read {path} with read_file, then retry str_replace with a longer exact old_string. "
          "Do not use write_file on existing files."
        )
        tool_failures.append(message)
        emit("tool.str_replace", message, status="completed", detail={"path": path, "error": message, "recoverable": True})
        return {"error": message, "path": path, "recoverable": True}

    raise ToolExecutionError(f"Unknown streaming file agent tool: {name}")

  def try_apply_deterministic_scoped_update(
    *,
    event_step: str,
    output_prefix: str,
    require_interaction: bool = True,
  ) -> tuple[bool, str]:
    if (
      intent != "website_update"
      or not persist_to_store
      or worker_id
      or staged_files
      or changed_paths
      or resolved_scope is None
    ):
      return False, ""
    recovery_analysis = resolved_scope.to_update_analysis()
    request_kind = str(recovery_analysis.get("request_kind") or scope_request_kind or "")
    deterministic_interaction = (
      request_kind == "interaction_wiring_update"
      or enrichment_profile == "interaction_wiring"
      or any(term in prompt.lower() for term in ("button", "modal", "popup", "pop up", "alert", "redirect"))
    )
    if require_interaction and not deterministic_interaction:
      return False, ""
    try:
      from ..agent_runtime.scoped_update.generation import (
        collect_deterministic_scoped_update_fallback_changes,
      )
      from .syntax_guard import guard_syntax_write
      from .update_write_guard import guard_streaming_file_write

      recovery_files = [
        {"path": path, "content": content}
        for path, content in sorted(files_before_map.items())
      ]
      recovery_changes, recovery_kind = collect_deterministic_scoped_update_fallback_changes(
        prompt=prompt,
        update_analysis=recovery_analysis,
        existing_files=recovery_files,
      )
      approved_paths = {
        str(path)
        for path in [
          *(recovery_analysis.get("candidate_files") or []),
          *(recovery_analysis.get("target_files") or []),
        ]
        if str(path)
      }
      recovered_paths: list[str] = []
      for item in recovery_changes:
        path = str(item.get("path") or "")
        content = str(item.get("content") or "")
        previous = files_before_map.get(path, "")
        if (
          not path
          or path not in approved_paths
          or not content.strip()
          or content == previous
          or is_runtime_shim_path(path)
        ):
          continue
        blocked = guard_streaming_file_write(
          path,
          content,
          previous,
          update_mode=scope_update_mode or None,
          request_kind=scope_request_kind or None,
          prompt=prompt,
          via_write_file=False,
          intent=intent,
        )
        syntax_blocked = guard_syntax_write(path, content)
        if blocked or syntax_blocked:
          failure = blocked or syntax_blocked or {}
          tool_failures.append(str(failure.get("error") or "deterministic direct update rejected"))
          continue
        staged_files[path] = content
        changed_paths.add(path)
        recovered_paths.append(path)
        emit_file_written(path, content, action="str_replace")
      if not recovered_paths:
        return False, ""
      output = f"{output_prefix} ({recovery_kind or 'scoped interaction update'})."
      emit(
        event_step,
        output,
        status="completed",
        detail={
          "recovery_kind": recovery_kind,
          "changed_paths": recovered_paths,
          "interaction": scope_interaction,
          "candidate_files": sorted(approved_paths),
        },
      )
      return True, output
    except Exception as exc:
      raise_if_runtime_cancelled()
      tool_failures.append(f"deterministic direct update failed: {exc}")
      emit(
        f"{event_step}.failed",
        f"Deterministic direct update did not produce a patch: {exc}",
        status="completed",
        detail={"error": str(exc), "interaction": scope_interaction},
      )
      return False, ""

  execution_prompt = prompt
  current_project_files = [
    {"path": path, "content": content}
    for path, content in sorted(files_before_map.items())
  ]
  if error_repair:
    try:
      from ...agentic.tools.handlers import build_staged_project_preview_tool

      diagnostic_preview = build_staged_project_preview_tool(
        tool_context,
        user,
        {"project_id": project_id, "files": current_project_files},
      )
      diagnostic_version = (
        diagnostic_preview.get("version")
        if isinstance(diagnostic_preview.get("version"), dict)
        else {}
      )
      diagnostic_log = str(diagnostic_version.get("build_log") or "")
      if str(diagnostic_version.get("status") or "") != "ready" and diagnostic_log:
        execution_prompt = (
          f"{prompt}\n\nCurrent project build failure:\n"
          f"{diagnostic_log[-6000:]}\n\n"
          f"Repair files identified by the build: "
          f"{', '.join(derive_error_repair_scope_paths(prompt=prompt, files=current_project_files, build_log=diagnostic_log)) or 'unknown'}."
        )
      scoped_error_paths = derive_error_repair_scope_paths(
        prompt=execution_prompt,
        files=current_project_files,
        build_log=diagnostic_log,
      )
      if scoped_error_paths:
        if effective_allowed_write_paths is None:
          effective_allowed_write_paths = frozenset(scoped_error_paths)
        else:
          effective_allowed_write_paths = frozenset(set(effective_allowed_write_paths) | set(scoped_error_paths))
        emit(
          "error.scope.selected",
          f"Scoped repair to {len(scoped_error_paths)} likely file(s)",
          status="completed",
          detail={"paths": scoped_error_paths, "source": "build_log_and_diagnosis"},
        )
      emit(
        "error.diagnosed",
        "Captured the current build log for targeted repair",
        status="completed",
        detail={
          "paths": scoped_error_paths,
          "build_log_excerpt": diagnostic_log[-2000:],
          "scoped": effective_allowed_write_paths is not None,
        },
      )
    except Exception as exc:
      emit(
        "error.diagnosis.skipped",
        f"Could not capture a current build log: {exc}",
        status="completed",
        detail={"error": str(exc)},
      )

  context_block = (
    f"Parallel worker `{worker_id}`. Project id: {project_id}. "
    f"Assigned paths only: {', '.join(sorted(effective_allowed_write_paths or []))}."
    if worker_id
    else build_project_context_block(
      project_id=project_id,
      tool_context=tool_context,
      user=user,
      prompt=execution_prompt,
      intent=intent,
      chat_session_id=chat_session_id,
      chat_topic_id=chat_topic_id,
      project_name=project_name,
      scoped_priority_paths=list(
        dict.fromkeys(
          [
            *(scoped_target_paths or []),
            *[
              str(item.get("path") or "")
              for item in scope_enrichment_snippets
              if str(item.get("path") or "")
            ],
          ]
        )
      )
      or None,
    )
  )
  try:
    from ..prompting.attachments import enrich_prompt_with_attachments, normalize_prompt_attachments
  except ImportError:
    from agents.prompting.attachments import enrich_prompt_with_attachments, normalize_prompt_attachments
  normalized_attachments = normalize_prompt_attachments(attachments or [])
  enriched_prompt = enrich_prompt_with_attachments(execution_prompt, normalized_attachments)
  if intent == "website_generation" and confirmation_brief:
    try:
      from ..requirement_confirmation.prompts import format_confirmation_brief_for_generation
    except ImportError:
      from agents.requirement_confirmation.prompts import format_confirmation_brief_for_generation
    brief_block = format_confirmation_brief_for_generation(confirmation_brief)
    if brief_block and brief_block not in enriched_prompt:
      enriched_prompt = f"{brief_block}\n\n{enriched_prompt}"
  user_message = (
    f"{context_block}\n\n"
    f"Intent: {intent}\n"
    f"User request:\n{enriched_prompt}\n\n"
  )
  if auth_flow_update:
    try:
      from .task_planner import auth_onboarding_flow_repair_summary
    except ImportError:
      from agents.streaming.task_planner import auth_onboarding_flow_repair_summary
    user_message += (
      "AUTH / ONBOARDING FLOW PATCH REQUIRED:\n"
      f"{auth_onboarding_flow_repair_summary(prompt)}\n"
      "Read the application router and the relevant sign-in/auth, onboarding, and dashboard files before editing. "
      "Implement the smallest coherent route/state patch that enforces: initial entry -> sign in; successful sign in "
      "-> onboarding; onboarding completion -> dashboard. Remove or disable any dashboard onboarding CTA that "
      "contradicts this sequence. Preserve unrelated pages and do not edit package.json or platform router shims "
      "unless the user explicitly requested dependency or platform changes. If the same current request also includes "
      "visual/theme/color instructions, handle those only as a secondary update in approved style/page files after "
      "the auth -> onboarding -> dashboard flow is patched; never return a style-only patch for a flow request. "
      "Apply actual file edits; do not finish with an explanation only.\n\n"
    )
    if scoped_target_paths:
      user_message += f"Flow files in scope: {', '.join(scoped_target_paths)}.\n\n"
    if scope_new_files:
      user_message += f"Approved new files if needed: {', '.join(scope_new_files)}.\n\n"
  elif error_repair:
    user_message += (
      "Fix the reported error surgically using the candidate files above. "
      "Do not read every page file.\n\n"
    )
    if effective_allowed_write_paths:
      user_message += (
        f"Assigned repair paths: {', '.join(sorted(effective_allowed_write_paths))}. "
        "Read and edit only these paths and their direct imports. "
        "If the root cause is outside this scope, explain that instead of editing unrelated files.\n\n"
      )
  elif scoped_target_paths:
    if scope_request_kind in {"theme_color_update", "style_reference_update"}:
      user_message += (
        f"Priority visual/theme files from project memory/search: {', '.join(scoped_target_paths)}.\n"
        + (f"Approved new files if needed: {', '.join(scope_new_files)}.\n" if scope_new_files else "")
        + f"Resolution rationale: {scope_rationale[:400] or 'visual style ownership from project source'}.\n"
        "Act as the code-writing agent for this existing project. Read the priority files that own the current "
        "visual palette/classes/tokens, then apply real source edits with str_replace. Do not rely on backend "
        "static color mappings or return a summary-only answer. Preserve routes, copy, data, and behavior unless "
        "the user explicitly requested changing them. If another rendered source file owns remaining old styling, "
        "use list_files/read_file for context and edit the relevant workspace file directly. Avoid unrelated rewrites.\n\n"
      )
    if scope_reference_files:
      snippet_lines = []
      for item in style_reference_snippets[:3]:
        path = str(item.get("path") or "")
        snippet = str(item.get("snippet") or "")
        if path and snippet:
          snippet_lines.append(f"Reference styles from {path}:\n{snippet[:800]}")
      user_message += (
        f"Priority target files to edit: {', '.join(scope_target_files or scoped_target_paths)}.\n"
        f"Reference files (read-only): {', '.join(scope_reference_files)}.\n"
        + (f"Approved new files if needed: {', '.join(scope_new_files)}.\n" if scope_new_files else "")
        + f"Resolution rationale: {scope_rationale[:400] or 'match reference page styling on target page'}.\n"
        "Read every reference file first and copy color tokens/classNames to the target file(s). "
        "Do not edit reference files unless the requested update truly requires it.\n"
      )
      if snippet_lines:
        user_message += "\n".join(snippet_lines) + "\n"
      user_message += "\n"
    elif scope_enrichment_snippets or enrichment_profile == "interaction_wiring":
      enrichment_block = _format_scope_enrichment_block(
        scoped_target_paths=scoped_target_paths,
        scope_enrichment_snippets=scope_enrichment_snippets,
        enrichment_profile=enrichment_profile,
        interaction_summary=interaction_summary,
        scope_rationale=scope_rationale,
        interaction=scope_interaction,
      )
      if enrichment_block:
        user_message += enrichment_block
        if scope_new_files:
          user_message += f"Approved new files if needed: {', '.join(scope_new_files)}.\n\n"
      else:
        user_message += (
          f"Priority files from project memory/search: {', '.join(scoped_target_paths)}.\n"
          + (f"Approved new files if needed: {', '.join(scope_new_files)}.\n" if scope_new_files else "")
          + f"Resolution rationale: {scope_rationale[:400] or 'memory + codebase retrieval + update analysis'}.\n"
          "Apply the update directly in the workspace. Edit the smallest number of files needed — str_replace only on "
          "existing files. write_file is for new paths only. Use list_files/read_file if you need more context.\n\n"
        )
    else:
      user_message += (
        f"Priority files from project memory/search: {', '.join(scoped_target_paths)}.\n"
        + (f"Approved new files if needed: {', '.join(scope_new_files)}.\n" if scope_new_files else "")
        + f"Resolution rationale: {scope_rationale[:400] or 'memory + codebase retrieval + update analysis'}.\n"
        "Apply the requested update directly in the workspace. Edit the smallest number of files needed — str_replace only on "
        "existing files. write_file is for new paths only. Use list_files/read_file if you need more context.\n\n"
      )
  elif scoped_update:
    user_message += (
      "Apply the requested update directly in the workspace. Edit the smallest number of files needed — str_replace only on "
      "existing files. write_file is for new paths only. Use list_files/read_file to find the owning files.\n\n"
    )
  elif ui_interaction_update:
    from .legacy_update_routing import legacy_ui_interaction_user_message_block

    user_message += legacy_ui_interaction_user_message_block()
  elif worker_id:
    user_message += (
      "You are a parallel file worker. File snippets are inline in the user request. "
      "Apply edits immediately with str_replace or write_file on your assigned paths only. "
      "Do not list_files('.') or read unrelated project files.\n\n"
    )
  user_message += "Use tools to read, list, search, write, and edit files. Finish with a concise summary."

  if error_repair:
    emit(
      "error.diagnosed",
      "Scoped error repair to likely files and project memory",
      status="completed",
      detail={"mode": "streaming_error_repair", "prompt": prompt[:500]},
    )

  step_limit = streaming_file_agent_step_limit(
    intent=intent,
    prompt=prompt,
    worker_id=worker_id,
    max_steps=max_steps,
    request_kind=scope_request_kind,
  )

  emit("streaming.file_agent.started", "Starting streaming file agent with live tool loop")
  emit("agent.runtime.loop.started", "Running fast streaming file agent")

  loop_error: str | None = None
  deterministic_preflight_applied = False
  deterministic_preflight_output = ""
  if _env_bool("ENABLE_LOCAL_FIRST_INTERACTION_UPDATES", True):
    deterministic_preflight_applied, deterministic_preflight_output = try_apply_deterministic_scoped_update(
      event_step="update.deterministic_patch.applied",
      output_prefix="Applied a local deterministic interaction patch before calling the model",
      require_interaction=True,
    )
  elif (
    intent == "website_update"
    and persist_to_store
    and not worker_id
    and resolved_scope is not None
    and scope_request_kind == "interaction_wiring_update"
  ):
    emit(
      "update.deterministic_patch.disabled",
      "Local-first deterministic interaction updates are disabled by configuration",
      status="completed",
      detail={"flag": "ENABLE_LOCAL_FIRST_INTERACTION_UPDATES"},
    )
  if deterministic_preflight_applied:
    loop_result = {
      "status": "completed",
      "output_text": deterministic_preflight_output,
      "tool_calls": [],
    }
    emit(
      "agent.runtime.loop.skipped",
      "Skipped model patch loop because a local deterministic direct update was staged",
      status="completed",
      detail={"changed_paths": sorted(changed_paths), "reason": "deterministic_scoped_update"},
    )
  else:
    try:
      loop_result = artifact_provider.run_tool_loop(
        messages=[
          {"role": "system", "content": system_instruction},
          {"role": "user", "content": user_message, "attachments": normalized_attachments},
        ],
        tools=STREAMING_FILE_AGENT_TOOLS,
        execute_tool=execute_tool,
        max_steps=step_limit,
        trace_label=f"streaming_file_agent.{intent or 'unknown'}",
        on_step_text=None,
        on_tool_start=lambda tool_name, tool_args, step: emit(
          "tool.requested",
          f"Tool {tool_name} (step {step})",
          detail={"tool": tool_name, "arguments": tool_args, "step": step},
        ),
      )
    except Exception as exc:
      raise_if_runtime_cancelled()
      loop_error = str(exc)
      loop_result = {
        "status": "partial",
        "output_text": "",
        "tool_calls": [],
        "error": loop_error,
      }
      emit(
        "agent.runtime.loop.partial",
        f"Streaming file agent stopped early: {loop_error}",
        status="completed",
        detail={"error": loop_error, "changed_paths": sorted(changed_paths)},
      )

  output_text = str(loop_result.get("output_text") or "").strip()
  step_exhausted_without_patch = _is_tool_loop_step_exhaustion(loop_error)
  if (
    intent == "website_update"
    and persist_to_store
    and not worker_id
    and not staged_files
    and not changed_paths
    and (not loop_error or step_exhausted_without_patch)
  ):
    try:
      from .streaming_parity import (
        try_deterministic_module_contract_fix_streaming,
        try_deterministic_undefined_reference_fix_streaming,
      )

      quick_fix = try_deterministic_module_contract_fix_streaming(
        prompt=prompt,
        tool_context=tool_context,
        user=user,
        project_id=project_id,
        emit_progress=emit,
        patch_action=patch_action,
        chat_session_id=chat_session_id,
        agent_run_id=agent_run_id,
      )
      if quick_fix is not None:
        return quick_fix

      quick_fix = try_deterministic_undefined_reference_fix_streaming(
        prompt=prompt,
        tool_context=tool_context,
        user=user,
        project_id=project_id,
        intent=intent,
        artifact_provider=artifact_provider,
        emit_progress=emit,
        patch_action=patch_action,
        chat_session_id=chat_session_id,
        project_name=project_name,
      )
      if quick_fix is not None:
        return quick_fix
    except Exception as exc:
      raise_if_runtime_cancelled()
      emit(
        "update.empty_patch.fallback_failed",
        f"Deterministic no-change fallback did not produce a patch: {exc}",
        status="completed",
        detail={"error": str(exc)},
      )

    retry_message = (
      f"{user_message}\n\n"
      "Previous attempt produced ZERO file edits. Do not finish with a summary only. "
      "You must either apply at least one minimal safe str_replace/write_file edit, or ask a clarification question. "
      "If the request contains a browser/build error such as `does not provide an export named`, search_codebase for "
      "the missing symbol and the imported module, then patch the smallest importer or data module contract. "
      "If the request is a theme/color update, read the active page/component and stylesheet/theme token file, then "
      "apply explicit user-provided color/theme edits without regenerating unrelated content.\n"
    )
    if step_exhausted_without_patch:
      retry_message += (
        "\nPrevious tool loop stopped because the step budget was exhausted before any file edit happened:\n"
        f"- {loop_error}\n"
        "On this retry, avoid exploratory reads and patch one relevant workspace file as soon as you have enough context.\n"
      )
    syntax_context = _syntax_retry_context(tool_failures=tool_failures)
    if syntax_context:
      retry_message += (
        "\nSyntax/tool failure context from the previous attempt:\n"
        f"{syntax_context}\n"
        "Fix the listed issue(s) directly in the smallest target file before finishing.\n"
      )
    if auth_flow_update:
      retry_message += (
        "This is an auth/onboarding flow update. Patch the router and the directly related auth, onboarding, or "
        "dashboard handler files so the requested sign-in -> onboarding -> dashboard sequence is executable. "
        "Do not modify package.json, dependency versions, or platform shim files as a substitute for app-flow edits.\n"
      )
    emit(
      "update.empty_patch.retry",
      "The first update attempt produced no file edits; retrying with stricter patch instructions",
      status="running",
      detail={"previous_output": output_text[:500], "previous_error": loop_error, "step_limit": step_limit},
    )
    try:
      retry_result = artifact_provider.run_tool_loop(
        messages=[
          {"role": "system", "content": system_instruction},
          {"role": "user", "content": retry_message, "attachments": normalized_attachments},
        ],
        tools=STREAMING_FILE_AGENT_TOOLS,
        execute_tool=execute_tool,
        max_steps=max(step_limit, 8),
        trace_label=f"streaming_file_agent.{intent or 'unknown'}.empty_patch_retry",
        on_step_text=None,
        on_tool_start=lambda tool_name, tool_args, step: emit(
          "tool.requested",
          f"Retry tool {tool_name} (step {step})",
          detail={"tool": tool_name, "arguments": tool_args, "step": step, "retry": "empty_patch"},
        ),
      )
      retry_output = str(retry_result.get("output_text") or "").strip()
      if retry_output or staged_files or changed_paths:
        loop_result = retry_result
        output_text = retry_output or output_text
        emit(
          "update.empty_patch.retry.completed",
          "Empty-patch retry completed",
          status="completed",
          detail={"changed_paths": sorted(changed_paths), "has_output": bool(retry_output)},
        )
    except Exception as exc:
      raise_if_runtime_cancelled()
      tool_failures.append(f"empty patch retry failed: {exc}")
      emit(
        "update.empty_patch.retry_failed",
        f"Empty-patch retry failed: {exc}",
        status="failed",
        detail={"error": str(exc)},
      )

  if (
    intent == "website_update"
    and persist_to_store
    and not worker_id
    and not staged_files
    and not changed_paths
    and resolved_scope is not None
  ):
    recovered, recovered_output = try_apply_deterministic_scoped_update(
      event_step="update.empty_patch.recovered",
      output_prefix="Applied a bounded deterministic repair from actual project code anchors after the model returned no patch",
      require_interaction=False,
    )
    if recovered:
      output_text = recovered_output

  empty_patch_after_retry = (
    intent == "website_update"
    and persist_to_store
    and not worker_id
    and not staged_files
    and not changed_paths
  )
  if empty_patch_after_retry:
    attempted_tools = list(loop_result.get("tool_calls") or []) if isinstance(loop_result, dict) else []
    if tool_failures:
      no_patch_cause = "tool_or_safety_rejection"
    elif loop_error:
      no_patch_cause = "tool_loop_error"
    elif not attempted_tools:
      no_patch_cause = "model_returned_without_edit_tool"
    else:
      no_patch_cause = "tool_loop_produced_no_effective_diff"
    candidate_detail = ", ".join(scoped_target_paths[:6])
    no_patch_message = (
      "Targeted update could not be applied safely because no effective file changes passed the commit gates: "
      "the update agent completed both patch attempts without producing any file edits. "
      f"request_kind={scope_request_kind or 'unknown'}. "
      f"Cause: {no_patch_cause.replace('_', ' ')}."
    )
    if candidate_detail:
      no_patch_message += f" Candidate files: {candidate_detail}."
    tool_failures.append("website update produced zero file edits")
    output_text = no_patch_message
    loop_result = {
      **(loop_result if isinstance(loop_result, dict) else {}),
      "status": "failed",
      "output_text": no_patch_message,
      "changed_paths": [],
      "changed_file_paths": [],
      "error": "website_update_no_patch",
    }
    emit(
      "update.empty_patch.failed",
      no_patch_message,
      status="failed",
      detail={
        "error": "website_update_no_patch",
        "changed_paths": [],
        "cause": no_patch_cause,
        "candidate_files": scoped_target_paths,
        "target_files": scope_target_files,
        "request_kind": scope_request_kind,
        "update_mode": scope_update_mode,
        "interaction": scope_interaction,
        "scope_rationale": scope_rationale[:800],
        "tool_call_count": len(attempted_tools),
        "tool_failures": tool_failures[-8:],
        "loop_error": loop_error,
      },
    )

  if output_text:
    _emit_assistant_delta(output_text[:400], emit)

  persisted_files: list[dict[str, str]] = []
  precommit_build_result: dict[str, Any] | None = None
  precommit_visual_result: dict[str, Any] | None = None
  precommit_attempted = False
  rejected_writes: list[dict[str, Any]] = []
  commit_rejection_gate = ""
  syntax_repair_attempted = False

  def prepare_commit_payload(payload: list[dict[str, str]]) -> list[dict[str, str]]:
    try:
      try:
        from ..agent_runtime.scaffolding import ensure_tailwind_runtime_files, normalize_frontend_runtime_imports
      except ImportError:
        from agents.agent_runtime.scaffolding import ensure_tailwind_runtime_files, normalize_frontend_runtime_imports
      prepared, _ = normalize_frontend_runtime_imports(payload)
      if intent != "website_update":
        prepared, _ = ensure_tailwind_runtime_files(prepared)
      return prepared
    except Exception:
      return payload

  def filter_commit_payload(payload: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    if intent != "website_update":
      return payload, []
    try:
      from ..update_engine.commit_pipeline import filter_update_write_payload
    except ImportError:
      from agents.update_engine.commit_pipeline import filter_update_write_payload
    filtered, rejected = filter_update_write_payload(
      files_before_map=files_before_map,
      write_payload=payload,
      prompt=prompt,
      intent=intent,
      update_mode=scope_update_mode,
      request_kind=scope_request_kind,
    )
    if rejected:
      rejected_paths = {str(item.get("path") or "") for item in rejected}
      for path in rejected_paths:
        staged_files.pop(path, None)
        changed_paths.discard(path)
      emit(
        "commit.rejected",
        f"Commit blocked: {len(rejected)} file write(s) rejected by rewrite guard",
        status="failed",
        detail={
          "rejected": rejected,
          "gate": "rewrite_guard",
          "kept_paths": [item["path"] for item in filtered],
        },
      )
      emit(
        "update.rewrite.blocked",
        f"Blocked {len(rejected)} destructive rewrite(s) — preserved existing code",
        status="completed",
        detail={"rejected": rejected, "kept_paths": [item["path"] for item in filtered]},
      )
    return filtered, rejected

  if staged_files and persist_to_store:
    raise_if_runtime_cancelled()
    write_payload = prepare_commit_payload(
      [{"path": path, "content": content} for path, content in sorted(staged_files.items())]
    )
    write_payload, rejected_writes = filter_commit_payload(write_payload)
    if rejected_writes:
      commit_rejection_gate = "rewrite_guard"
    try:
      from .streaming_parity import streaming_patch_approval_gate

      raise_if_runtime_cancelled()
      approval_result = streaming_patch_approval_gate(
        tool_context=tool_context,
        user=user,
        project_id=project_id,
        prompt=prompt,
        write_payload=write_payload,
        files_before_map=files_before_map,
        emit_progress=emit,
        patch_action=patch_action,
        summary=output_text or "Streaming file agent proposed changes.",
      )
      if approval_result is not None:
        runtime = dict(approval_result.get("runtime") or {})
        runtime.update(
          {
            "engine": "streaming_file_agent",
            "tool_calls": loop_result.get("tool_calls") or [],
            "changed_paths": sorted(changed_paths),
            "output_text": output_text,
          }
        )
        approval_result["runtime"] = runtime
        return approval_result
    except Exception:
      pass
    try:
      from .syntax_guard import find_syntax_issues_in_payload
    except ImportError:
      from agents.streaming.syntax_guard import find_syntax_issues_in_payload
    syntax_issues = find_syntax_issues_in_payload(write_payload)
    if syntax_issues:
      original_syntax_issues = list(syntax_issues)
      failed_paths = sorted({str(item.get("path") or "") for item in write_payload if item.get("path")})
      for path in failed_paths:
        staged_files.pop(path, None)
        changed_paths.discard(path)
      if intent == "website_update" and persist_to_store and not worker_id and not syntax_repair_attempted:
        syntax_repair_attempted = True
        retry_message = _syntax_repair_retry_prompt(
          base_user_message=user_message,
          syntax_issues=syntax_issues[:8],
          failed_paths=failed_paths,
          previous_output=output_text,
        )
        emit(
          "update.syntax.retry",
          "Syntax gate blocked the staged update; retrying once with exact syntax issues",
          status="running",
          detail={"issues": syntax_issues[:8], "paths": failed_paths},
        )
        try:
          retry_result = artifact_provider.run_tool_loop(
            messages=[
              {"role": "system", "content": system_instruction},
              {"role": "user", "content": retry_message, "attachments": normalized_attachments},
            ],
            tools=STREAMING_FILE_AGENT_TOOLS,
            execute_tool=execute_tool,
            max_steps=max(step_limit, 8),
            trace_label=f"streaming_file_agent.{intent or 'unknown'}.syntax_retry",
            on_step_text=None,
            on_tool_start=lambda tool_name, tool_args, step: emit(
              "tool.requested",
              f"Syntax retry tool {tool_name} (step {step})",
              detail={"tool": tool_name, "arguments": tool_args, "step": step, "retry": "syntax"},
            ),
          )
          retry_output = str(retry_result.get("output_text") or "").strip()
          if retry_output:
            loop_result = retry_result
            output_text = retry_output
          write_payload = prepare_commit_payload(
            [{"path": path, "content": content} for path, content in sorted(staged_files.items())]
          )
          write_payload, retry_rejected_writes = filter_commit_payload(write_payload)
          if retry_rejected_writes:
            rejected_writes = retry_rejected_writes
            commit_rejection_gate = "rewrite_guard"
          syntax_issues = find_syntax_issues_in_payload(write_payload)
          if write_payload and not syntax_issues and not retry_rejected_writes:
            commit_rejection_gate = ""
            emit(
              "update.syntax.retry.completed",
              "Syntax repair retry produced a valid staged patch",
              status="completed",
              detail={"paths": [item["path"] for item in write_payload]},
            )
          else:
            emit(
              "update.syntax.retry_failed",
              "Syntax repair retry did not produce a valid patch",
              status="failed",
              detail={"issues": syntax_issues[:8], "paths": failed_paths},
            )
        except Exception as exc:
          raise_if_runtime_cancelled()
          tool_failures.append(f"syntax repair retry failed: {exc}")
          emit(
            "update.syntax.retry_failed",
            f"Syntax repair retry failed: {exc}",
            status="failed",
            detail={"error": str(exc), "issues": syntax_issues[:8], "paths": failed_paths},
          )
      if syntax_issues or (not write_payload and commit_rejection_gate != "rewrite_guard"):
        blocked_syntax_issues = syntax_issues or original_syntax_issues
        for path in {str(item.get("path") or "") for item in write_payload}:
          staged_files.pop(path, None)
          changed_paths.discard(path)
        commit_rejection_gate = "syntax" if commit_rejection_gate != "rewrite_guard" else commit_rejection_gate
        emit(
          "commit.rejected",
          f"Commit blocked: syntax issues in {len(blocked_syntax_issues)} file(s)",
          status="failed",
          detail={"issues": blocked_syntax_issues[:8], "gate": commit_rejection_gate or "syntax"},
        )
        emit(
          "gate.syntax.commit_blocked",
          f"Blocked commit for {len(blocked_syntax_issues)} syntax issue(s) — fix code before saving",
          status="failed",
          detail={
            "issues": blocked_syntax_issues[:8],
            "category": "syntax",
            "code": "syntax_commit_blocked",
            "user_message": "File save blocked due to syntax errors. Fix the listed issues and retry.",
            "files_committed": False,
          },
        )
        write_payload = []
    if (
      write_payload
      and not worker_id
      and not skip_build_gate
      # Website updates should not lose valid staged edits to the automation
      # gate before they are saved. They run the post-update build/QA gate
      # after persistence below, while greenfield generation can still use
      # precommit normalization before the first project write.
      and intent == "website_generation"
      and hasattr(tool_context.store, "create_version")
    ):
      try:
        from .streaming_visual_qa import run_precommit_automation_gate

        raise_if_runtime_cancelled()
        candidate_map = dict(files_before_map)
        candidate_map.update({str(item["path"]): str(item["content"]) for item in write_payload})
        precommit_attempted = True
        skip_visual_precommit = (
          scope_request_kind == "style_reference_update"
          and all(
            str(path).startswith(("src/pages/", "src/components/"))
            for path in changed_paths
          )
        )
        precommit_build_result, precommit_visual_result = run_precommit_automation_gate(
          project_id=project_id,
          user=user,
          tool_context=tool_context,
          candidate_files=[
            {"path": path, "content": content}
            for path, content in sorted(candidate_map.items())
          ],
          changed_paths=sorted(changed_paths),
          operation="update" if intent == "website_update" else "generation",
          prompt=prompt,
          chat_session_id=chat_session_id,
          agent_run_id=agent_run_id,
          emit_progress=emit,
          skip_visual_qa=skip_visual_precommit,
        )
        raise_if_runtime_cancelled()
        if (
          str(precommit_build_result.get("status") or "") != "ready"
          or str((precommit_visual_result or {}).get("status") or "") != "passed"
        ):
          commit_rejection_gate = "precommit"
          emit(
            "commit.rejected",
            "Commit blocked: staged build or visual QA did not pass",
            status="failed",
            detail={
              "gate": "precommit",
              "build_status": precommit_build_result.get("status"),
              "visual_status": (precommit_visual_result or {}).get("status"),
            },
          )
          write_payload = []
          changed_paths.clear()
        else:
          normalized_candidates = list(precommit_build_result.get("candidate_files") or [])
          normalized_map = {
            str(item.get("path") or ""): str(item.get("content") or "")
            for item in normalized_candidates
            if isinstance(item, dict) and item.get("path")
          }
          for path in precommit_build_result.get("normalization_paths") or []:
            if path in normalized_map:
              staged_files[path] = normalized_map[path]
              changed_paths.add(path)
          write_payload = [
            {"path": path, "content": content}
            for path, content in sorted(normalized_map.items())
            if files_before_map.get(path) != content
          ]
          changed_paths = {str(item["path"]) for item in write_payload}
      except Exception as exc:
        precommit_attempted = True
        precommit_build_result = {"status": "failed", "error": str(exc), "precommit": True}
        commit_rejection_gate = "precommit"
        emit(
          "commit.rejected",
          f"Commit blocked: precommit automation failed ({exc})",
          status="failed",
          detail={"gate": "precommit", "error": str(exc)},
        )
        emit(
          "automation.precommit.failed",
          f"Automated pre-commit testing failed: {exc}",
          status="failed",
          detail={"error": str(exc), "files_committed": False},
        )
        write_payload = []
        changed_paths.clear()
    if write_payload:
      raise_if_runtime_cancelled()
      emit("files.persisting", f"Saving {len(staged_files)} changed files")
    write_result: dict[str, Any] = {}
    if write_payload:
      try:
        write_result = upsert_project_files_tool(
          tool_context,
          user,
          {
            "project_id": project_id,
            "files": write_payload,
            "reason": "streaming_file_agent",
            "intent": intent,
            "request_kind": scope_request_kind,
          },
        )
      except Exception as exc:
        raise_if_runtime_cancelled()
        emit(
          "files.persist.failed",
          f"Final validated save failed: {exc}",
          status="completed",
          detail={"error": str(exc), "paths": [item["path"] for item in write_payload]},
        )
        if not changed_paths:
          raise
      if isinstance(write_result.get("local_sync"), dict):
        last_local_sync = write_result["local_sync"]
      persisted_files = write_payload
      emit(
        "files.persisted",
        f"Saved {len(write_payload)} files",
        status="completed",
        detail={
          "file_count": len(write_payload),
          "paths": [item["path"] for item in write_payload],
          "files": write_payload,
        },
      )
      _emit_cumulative_staged_patch_diff(
        emit=emit,
        intent=intent,
        changed_paths=changed_paths,
        staged_files=staged_files,
        files_before_map=files_before_map,
        persisted=True,
      )
      emit(
        "files.materialized",
        f"Materialized {len(write_payload)} files",
        status="completed",
        detail={"files": write_payload, "paths": [item["path"] for item in write_payload]},
      )
      try:
        from ..code_index.incremental import maybe_reindex_after_persist
      except ImportError:
        from agents.code_index.incremental import maybe_reindex_after_persist
      maybe_reindex_after_persist(
        project_id,
        write_payload,
        changed_paths=[item["path"] for item in write_payload],
      )

  if changed_paths:
    try:
      try:
        from ...code_diff import build_project_diff
      except ImportError:
        from code_diff import build_project_diff
      before_files = [{"path": path, "content": files_before_map.get(path, "")} for path in sorted(changed_paths)]
      after_files = [{"path": path, "content": staged_files.get(path, files_before_map.get(path, ""))} for path in sorted(changed_paths)]
      diff_payload = build_project_diff(before_files, after_files, compare_mode="changed_only")
      if diff_payload.get("file_count"):
        emit(
          "file.diff.ready",
          f"Prepared code diff: {diff_payload.get('file_count', 0)} files, +{diff_payload.get('added', 0)} / -{diff_payload.get('removed', 0)}",
          status="completed",
          detail=diff_payload,
        )
    except Exception:
      pass

  build_gate_result: dict[str, Any] | None = precommit_build_result
  visual_qa_result: dict[str, Any] | None = precommit_visual_result
  if (
    changed_paths
    and persist_to_store
    and not worker_id
    and not skip_build_gate
    and not precommit_attempted
    and intent in {"website_update", "website_generation"}
  ):
    try:
      from .build_gate import post_update_build_gate_enabled, run_post_update_build_gate

      if post_update_build_gate_enabled():
        raise_if_runtime_cancelled()
        build_gate_result = run_post_update_build_gate(
          project_id=project_id,
          user=user,
          tool_context=tool_context,
          prompt=prompt,
          intent=intent,
          artifact_provider=artifact_provider,
          emit_progress=emit,
          changed_paths=sorted(changed_paths),
        )
        if build_gate_result.get("repair_attempts"):
          for path in tool_context.store.list_files(project_id, user):
            if not isinstance(path, dict):
              continue
            file_path = str(path.get("path") or "")
            content = str(path.get("content") or "")
            if file_path in changed_paths or file_path in staged_files:
              staged_files[file_path] = content
              changed_paths.add(file_path)
          persisted_files = [{"path": p, "content": staged_files[p]} for p in sorted(changed_paths)]
        if build_gate_result.get("status") == "ready":
          try:
            from .streaming_visual_qa import run_post_update_visual_qa

            raise_if_runtime_cancelled()
            visual_qa_result = run_post_update_visual_qa(
              project_id=project_id,
              user=user,
              tool_context=tool_context,
              build_gate_result=build_gate_result,
              emit_progress=emit,
              changed_paths=sorted(changed_paths),
              chat_session_id=chat_session_id,
              agent_run_id=agent_run_id,
              prompt=prompt,
              operation="update" if intent == "website_update" else "generation",
            )
            raise_if_runtime_cancelled()
          except Exception as exc:
            raise_if_runtime_cancelled()
            emit(
              "gate.visual_qa.failed",
              f"Post-update visual QA error: {exc}",
              status="failed",
              detail={
                "error": str(exc),
                "category": "visual_qa",
                "code": "visual_qa_failed",
                "user_message": "Files were saved locally. Visual QA did not pass — open Preview to review layout and styling.",
                "files_committed": True,
                "suggested_actions": [
                  "Open the preview and describe what looks wrong.",
                  "Ask the agent to fix layout, styling, or missing sections.",
                ],
              },
            )
        elif str(build_gate_result.get("status") or "").lower() not in {"ready", "skipped"}:
          try:
            from .commit_policy import should_rollback_after_build_gate
            from .streaming_parity import _rollback_changed_paths

            if should_rollback_after_build_gate(build_gate_result):
              _rollback_changed_paths(
                tool_context=tool_context,
                user=user,
                project_id=project_id,
                changed_paths=sorted(changed_paths),
                files_before_map=files_before_map,
                emit_progress=emit,
                build_gate_result=build_gate_result,
                persist_reason="streaming_file_agent",
              )
              persisted_files = []
              changed_paths.clear()
          except Exception:
            pass
    except Exception as exc:
      raise_if_runtime_cancelled()
      try:
        from .commit_policy import BUILD_FAILED_FILES_COMMITTED_MESSAGE
      except ImportError:
        from agents.streaming.commit_policy import BUILD_FAILED_FILES_COMMITTED_MESSAGE
      emit(
        "gate.build.failed",
        f"Post-update build gate error: {exc}",
        status="failed",
        detail={
          "error": str(exc),
          "category": "preview_build",
          "code": "build_gate_failed",
          "files_committed": True,
          "user_message": BUILD_FAILED_FILES_COMMITTED_MESSAGE,
          "suggested_actions": [
            "Your updated files are already saved — open them in the file tree.",
            "Retry Preview when your network or build environment is stable.",
          ],
        },
      )
  elif changed_paths:
    validation_issues = _diagnose_changed_source_files(
      [{"path": path, "content": staged_files.get(path, files_before_map.get(path, ""))} for path in sorted(changed_paths)]
    )
    if validation_issues:
      emit(
        "error.diagnosed",
        "Possible syntax issues in changed files. Run Preview to build and verify in the browser.",
        status="completed",
        detail={"issues": validation_issues, "changed_paths": sorted(changed_paths)},
      )
    else:
      emit(
        "gate.passed",
        "Changed source files passed basic syntax checks. Run Preview for a full build verification.",
        status="completed",
        detail={"changed_paths": sorted(changed_paths), "validation": "basic_syntax"},
      )

  artifact_title = project_name or "Generated Website"
  generated_website = _build_generated_website(persisted_files or [], summary=output_text, title=artifact_title)
  if not persisted_files and changed_paths:
    generated_website = _build_generated_website(
      [{"path": path, "content": staged_files.get(path, files_before_map.get(path, ""))} for path in sorted(changed_paths)],
      summary=output_text or "Updated project files from your prompt.",
      title=artifact_title,
    )
  elif not persisted_files and intent not in {"website_update", "website_generation"}:
    store_files = tool_context.store.list_files(project_id, user)
    fallback = [
      {"path": str(item.get("path") or ""), "content": str(item.get("content") or "")}
      for item in store_files
      if isinstance(item, dict) and item.get("path")
    ]
    if fallback:
      generated_website = _build_generated_website(
        fallback,
        summary=output_text or "No file changes were required.",
        title=artifact_title,
      )

  files_after_map = dict(files_before_map)
  files_after_map.update(staged_files)
  update_validation = None
  fallback_applied = False
  if intent == "website_update":
    from .update_validation import apply_brand_rename_fallback, extract_rename_target, validate_brand_rename

    update_validation = validate_brand_rename(
      prompt,
      files_before=files_before_map,
      files_after=files_after_map,
      changed_paths=sorted(changed_paths),
    )
    if (
      persist_to_store
      and not worker_id
      and update_validation
      and not update_validation.get("applied")
    ):
      target = extract_rename_target(prompt)
      if target:
        fallback_payload, fallback_paths = apply_brand_rename_fallback(files_after_map, target_name=target)
        if fallback_payload:
          emit(
            "agent.fallback.brand_rename",
            f"Applying deterministic brand rename to {len(fallback_paths)} file(s)",
            status="completed",
            detail={"paths": fallback_paths, "target": target},
          )
          try:
            raise_if_runtime_cancelled()
            write_result = upsert_project_files_tool(
              tool_context,
              user,
              {
                "project_id": project_id,
                "files": fallback_payload,
                "reason": "brand_rename_fallback",
                "intent": intent,
                "request_kind": "brand_name_update",
              },
            )
            if isinstance(write_result.get("local_sync"), dict):
              last_local_sync = write_result["local_sync"]
            for item in fallback_payload:
              staged_files[item["path"]] = item["content"]
              changed_paths.add(item["path"])
            files_after_map.update({item["path"]: item["content"] for item in fallback_payload})
            persisted_files = fallback_payload
            generated_website = _build_generated_website(
              fallback_payload,
              summary=f"Renamed site to {target}",
              title=target or artifact_title,
            )
            update_validation = validate_brand_rename(
              prompt,
              files_before=files_before_map,
              files_after=files_after_map,
              changed_paths=sorted(changed_paths),
            )
            update_validation["fallback_applied"] = True
            fallback_applied = True
          except Exception as exc:
            raise_if_runtime_cancelled()
            emit(
              "files.persist.failed",
              f"Brand rename fallback failed: {exc}",
              status="failed",
              detail={"error": str(exc)},
            )

  preview_status = "skipped"
  if build_gate_result:
    preview_status = str(build_gate_result.get("status") or "failed")
  elif persisted_files:
    preview_status = "built"

  final_output: dict[str, Any] = {
    "preview_status": preview_status,
    "preview_url": (build_gate_result or {}).get("preview_url"),
  }
  if visual_qa_result:
    final_output["visual_qa_status"] = visual_qa_result.get("status")

  empty_update = (
    intent == "website_update"
    and persist_to_store
    and not worker_id
    and not persisted_files
  )
  if empty_update and not empty_patch_after_retry:
    tool_failures.append("website update did not persist any file edits")
    prior_summary = str(output_text or "").strip()
    output_text = (
      "Targeted update could not be applied safely because no effective file changes passed the commit gates. "
      f"request_kind={scope_request_kind or 'unknown'}; "
      f"candidate_files={_short_list_for_failure(scoped_target_paths)}; "
      f"target_files={_short_list_for_failure(scope_target_files)}; "
      f"changed_paths={_short_list_for_failure(sorted(changed_paths))}."
    )
    if prior_summary:
      output_text += f" Previous agent summary: {prior_summary[:300]}"

  update_scope_payload: dict[str, Any] = {}
  if resolved_scope is not None:
    try:
      update_scope_payload = resolved_scope.to_update_analysis()
    except Exception:
      update_scope_payload = {}
  if not update_scope_payload:
    update_scope_payload = {
      "candidate_files": list(scoped_target_paths),
      "candidate_new_files": list(scope_new_files),
      "target_files": list(scope_target_files),
      "reference_files": list(scope_reference_files),
      "request_kind": scope_request_kind,
      "scope_rationale": scope_rationale,
    }

  requirement_validation: dict[str, Any] | None = None
  requirement_failed = False
  if intent == "website_update" and persist_to_store and not worker_id:
    try:
      from ..update_engine.requirement_validation import validate_update_requirement
    except ImportError:
      from agents.update_engine.requirement_validation import validate_update_requirement
    requirement_validation = validate_update_requirement(
      prompt=prompt,
      files_before_map=files_before_map,
      files_after_map=files_after_map,
      changed_paths=sorted(changed_paths),
      update_scope=update_scope_payload,
      preview_status=preview_status,
    )
    requirement_failed = requirement_validation.get("status") == "failed"
    if requirement_failed:
      issue_codes = [
        str(item.get("code") or "requirement_issue")
        for item in list(requirement_validation.get("issues") or [])
        if isinstance(item, dict)
      ]
      issue_text = ", ".join(issue_codes) or "requirement_not_met"
      validation_message = (
        "Website update did not pass requirement validation "
        f"({issue_text}). No success message will be shown until the requested change is applied and verified."
      )
      tool_failures.append(validation_message)
      output_text = output_text or validation_message
      emit(
        "update.requirement_validation.failed",
        validation_message,
        status="failed",
        detail=requirement_validation,
      )
    else:
      emit(
        "update.requirement_validation.completed",
        "Update requirement validation passed",
        status="completed",
        detail=requirement_validation,
      )

  loop_status = str(loop_result.get("status") or ("partial" if loop_error else "completed"))
  run_state = _streaming_run_state(
    intent=intent,
    persisted_files=persisted_files,
    empty_update=empty_update,
    requirement_failed=requirement_failed,
    build_gate_result=build_gate_result,
    visual_qa_result=visual_qa_result,
    loop_status=loop_status,
  )
  visual_contract_status = _visual_qa_contract_status(visual_qa_result)
  if visual_contract_status != "skipped":
    final_output["visual_qa_status"] = visual_contract_status
  final_output["run_state"] = run_state
  final_output["files_saved"] = bool(persisted_files)

  runtime = {
    "engine": "streaming_file_agent",
    "status": "failed" if (empty_update or requirement_failed) else loop_status,
    "run_state": run_state,
    "tool_calls": loop_result.get("tool_calls") or [],
    "changed_paths": sorted(changed_paths),
    "steps": list(loop_result.get("steps") or []) if isinstance(loop_result.get("steps"), list) else _runtime_steps_from_tool_calls(loop_result.get("tool_calls") if isinstance(loop_result, dict) else [], intent=intent),
    "output_text": output_text,
    "tool_source_of_truth": bool(staged_files),
    "local_sync": last_local_sync,
    "loop_error": loop_error,
    "tool_failures": tool_failures,
    "rejected_writes": rejected_writes,
    "error_repair_mode": error_repair,
    "worker_id": worker_id,
    "persist_to_store": persist_to_store,
    "final_output": final_output,
    "diagnostic_report": {
      "query_class": "website_update" if intent == "website_update" else intent,
      "selected_path": "local_first_direct_update" if deterministic_preflight_applied else "direct_project_update",
      "mutation_allowed": intent in {"website_update", "website_generation", "simple_code"},
      "model_used": not deterministic_preflight_applied,
      "model_skipped_reason": "local deterministic patch applied" if deterministic_preflight_applied else "",
      "target_files": sorted(scope_target_files or scoped_target_paths),
      "candidate_files": sorted(scoped_target_paths),
      "saved_paths": [str(item.get("path") or "") for item in persisted_files if item.get("path")],
      "save_status": "saved" if persisted_files else "not_saved",
      "preview_status": preview_status,
      "visual_qa_status": visual_contract_status,
      "run_state": run_state,
      "target_resolution": target_resolution,
    },
    "no_code_changes": empty_update,
    "requirement_not_met": requirement_failed,
    "project_file_count": len(files_before_map),
  }
  if build_gate_result:
    runtime["build_gate"] = build_gate_result
  if visual_qa_result:
    runtime["visual_qa"] = visual_qa_result
  if update_validation:
    runtime["update_validation"] = update_validation
  if requirement_validation:
    runtime["requirement_validation"] = requirement_validation
  if fallback_applied:
    runtime["fallback_applied"] = True

  try:
    from ..update_engine.commit_pipeline import commit_result_from_runtime
  except ImportError:
    from agents.update_engine.commit_pipeline import commit_result_from_runtime
  commit_result = commit_result_from_runtime(
    saved_paths=[str(item.get("path") or "") for item in persisted_files if item.get("path")],
    rejected_writes=rejected_writes,
    agent_summary=output_text,
    scope_rationale=scope_rationale,
    preview_status=preview_status,
    rejection_gate=commit_rejection_gate,
  )
  runtime["commit_result"] = {
    "saved_paths": commit_result.saved_paths,
    "rejected_writes": commit_result.rejected_writes,
    "persisted": commit_result.persisted,
    "user_message": commit_result.user_message,
    "preview_status": commit_result.preview_status,
    "scope_rationale": scope_rationale,
    "rejection_gate": commit_result.rejection_gate,
    "rejection_reason": commit_result.rejection_reason,
  }
  if resolved_scope is not None:
    runtime["update_scope"] = {
      "candidate_files": list(resolved_scope.candidate_files),
      "candidate_new_files": list(resolved_scope.candidate_new_files),
      "target_files": list(resolved_scope.target_files),
      "reference_files": list(resolved_scope.reference_files),
      "request_kind": resolved_scope.request_kind,
      "scope_rationale": resolved_scope.scope_rationale,
      "preflight_source": resolved_scope.preflight_source,
      "llm_analysis_used": resolved_scope.llm_analysis_used,
    }

  emit(
    "streaming.file_agent.completed",
    output_text or "Streaming file agent finished",
    status="failed" if (empty_update or requirement_failed) else "completed",
    detail={"changed_paths": sorted(changed_paths), "tool_call_count": len(runtime["tool_calls"])},
  )
  emit(
    "agent.runtime.loop.failed" if (empty_update or requirement_failed) else "agent.runtime.loop.completed",
    "Streaming file agent did not satisfy the requested update" if requirement_failed else "Streaming file agent produced no persisted file patch" if empty_update else "Streaming file agent completed",
    status="failed" if (empty_update or requirement_failed) else "completed",
  )

  artifact_response_payload = dict(loop_result) if isinstance(loop_result, dict) else {"summary": str(loop_result or "")}
  artifact_response_payload["changed_paths"] = sorted(changed_paths)
  artifact_response_payload["changed_file_paths"] = sorted(changed_paths)
  if update_validation:
    artifact_response_payload["update_validation"] = update_validation
  if requirement_validation:
    artifact_response_payload["requirement_validation"] = requirement_validation
  if rejected_writes:
    artifact_response_payload["rejected_writes"] = rejected_writes
  artifact_response_payload["commit_result"] = runtime.get("commit_result")
  if runtime.get("update_scope"):
    artifact_response_payload["update_scope"] = runtime["update_scope"]

  return {
    "generated_website": generated_website,
    "artifact_response": artifact_response_payload,
    "runtime": runtime,
  }
