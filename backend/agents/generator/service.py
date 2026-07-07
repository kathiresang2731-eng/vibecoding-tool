from __future__ import annotations

from typing import Any, Callable

try:
  from ...debug_trace import trace_function
except ImportError:
  from debug_trace import trace_function
from ..orchestrator import WorktualGenerationOrchestrator
from ..providers import LLMProvider


@trace_function(project_id=lambda *_args, project_id=None, **_kwargs: project_id or "-", provider=lambda *_args, control_provider=None, artifact_provider=None, **_kwargs: f"control={getattr(control_provider, 'name', '-')},artifact={getattr(artifact_provider, 'name', '-')}")
def generate_website(
  user_prompt: str,
  *,
  provider: LLMProvider | None = None,
  gemini_client: Any | None = None,
  control_provider: LLMProvider | None = None,
  artifact_provider: LLMProvider | None = None,
  progress_callback: Callable[[dict[str, Any]], None] | None = None,
  project_id: str | None = None,
  tool_context: Any | None = None,
  user: Any | None = None,
  allow_legacy_fallback: bool = False,
  agent_run_id: str | None = None,
  graph_thread_id: str | None = None,
  resume_graph: bool = False,
  confirmation_action: str | None = None,
  attachments: list[dict[str, Any]] | None = None,
  chat_session_id: str | None = None,
  chat_topic_id: str | None = None,
  project_name: str = "",
  patch_action: str | None = None,
  adaptive_route: dict[str, Any] | None = None,
) -> dict[str, Any]:
  orchestrator = WorktualGenerationOrchestrator(
    llm_provider=provider,
    gemini_client=gemini_client,
    control_provider=control_provider,
    artifact_provider=artifact_provider,
    progress_callback=progress_callback,
    project_id=project_id,
    tool_context=tool_context,
    user=user,
    allow_legacy_fallback=allow_legacy_fallback,
    agent_run_id=agent_run_id,
    graph_thread_id=graph_thread_id,
    resume_graph=resume_graph,
    confirmation_action=confirmation_action,
    attachments=attachments,
    chat_session_id=chat_session_id,
    chat_topic_id=chat_topic_id,
    project_name=project_name,
    patch_action=patch_action if patch_action in {"approve", "reject"} else None,
    adaptive_route=adaptive_route,
  )
  return orchestrator.run(user_prompt, confirmation_action=confirmation_action)
