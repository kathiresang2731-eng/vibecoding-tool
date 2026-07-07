from __future__ import annotations

from typing import Any

try:
  from backend.agents.chat_history import build_model_chat_memory_text
except ImportError:
  from backend.agents.chat_history import build_model_chat_memory_text


def append_orchestrator_context(
  prompt: str,
  *,
  error_context: str | None,
  enhancement_context: str | None,
  skills_block: str | None = None,
  episodic_context: str | None = None,
  agents_md_block: str | None = None,
) -> str:
  try:
    from backend.agents.chat_history import (
      primary_update_prompt,
      should_include_chat_continuity_for_prompt,
      should_include_error_context_for_prompt,
    )
  except ImportError:
    from agents.chat_history import (
      primary_update_prompt,
      should_include_chat_continuity_for_prompt,
      should_include_error_context_for_prompt,
    )

  latest_prompt = primary_update_prompt(prompt)
  if not should_include_error_context_for_prompt(latest_prompt):
    error_context = None
  if not should_include_chat_continuity_for_prompt(latest_prompt):
    enhancement_context = None

  context_blocks: list[str] = []
  if agents_md_block:
    context_blocks.append(agents_md_block.strip())
  if skills_block:
    context_blocks.append(skills_block.strip())
  if episodic_context:
    context_blocks.append(episodic_context.strip())
  if error_context:
    context_blocks.append(
      "Previous runtime/build error context available to the Chief Orchestrator:\n"
      f"{error_context}\n\n"
      "If this error context mentions local environment, local helper, terminal action, "
      "dependency installation, folder access, or workspace access, route the turn through "
      "the Universal Error Handling Agent with terminal handling instructions. Prefer using "
      "the user's local Worktual helper actions for git status, dependency install guidance, "
      "tests, and build validation before proposing code changes. Do not assume the server "
      "terminal can access another user's home directory."
    )
  if enhancement_context:
    context_blocks.append(
      "Previous enhancement-plan context available to the Chief Orchestrator:\n"
      f"{enhancement_context}"
    )
  if not context_blocks:
    return prompt
  return (
    f"{prompt}\n\n"
    "Additional conversation context for model routing and planning. "
    "Use it only if the current user request refers to or depends on it; otherwise ignore it.\n\n"
    + "\n\n".join(context_blocks)
  )


def generation_model_chat_metadata(
  generation: dict[str, Any],
  *,
  base_metadata: dict[str, Any] | None = None,
  local_sync: Any = None,
  local_sync_error: str | None = None,
) -> tuple[str, dict[str, Any]]:
  memory_content = build_model_chat_memory_text(
    generation,
    local_sync=local_sync,
    local_sync_error=local_sync_error,
  )
  metadata = dict(base_metadata or {})
  multi_agent = generation.get("multi_agent_system") if isinstance(generation, dict) else {}
  conversation = multi_agent.get("conversation_response") if isinstance(multi_agent, dict) else {}
  if isinstance(conversation, dict):
    display_content = str(conversation.get("message") or "").strip()
    if display_content:
      metadata["display_content"] = display_content
    confirmation = conversation.get("confirmation")
    if isinstance(confirmation, dict) and confirmation:
      metadata["confirmation"] = confirmation
  return memory_content, metadata
