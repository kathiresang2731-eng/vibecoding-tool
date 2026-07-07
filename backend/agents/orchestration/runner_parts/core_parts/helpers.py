from __future__ import annotations

import time
from typing import Any, Callable

from backend.agents.providers import ARTIFACT_PROVIDER_ROLE
from backend.agents.providers import CONTROL_PROVIDER_ROLE
from backend.agents.providers import GeminiProvider
from backend.agents.providers import LLMProvider
from backend.agents.providers import assert_provider_role
from backend.agents.orchestration.provider_utils import default_control_provider
from backend.agents.orchestration.provider_utils import provider_name
from backend.agents.orchestration.runtime_metadata import format_stage_name
from backend.agents.orchestration.runtime_metadata import summarize_stage_output
from backend.agents.orchestration.state import GenerationPipelineState


def resolve_control_provider(orchestrator: Any) -> Any:
  provider = orchestrator.control_provider or orchestrator.llm_provider or default_control_provider()
  assert_provider_role(provider, CONTROL_PROVIDER_ROLE)
  return provider


def resolve_artifact_provider(orchestrator: Any) -> Any:
  provider = orchestrator.artifact_provider or orchestrator.gemini_client or orchestrator.llm_provider or GeminiProvider()
  assert_provider_role(provider, ARTIFACT_PROVIDER_ROLE)
  return provider


def emit_progress(
  orchestrator: Any,
  step: str,
  message: str,
  *,
  status: str = "running",
  detail: dict[str, Any] | None = None,
  audit_detail: dict[str, Any] | None = None,
) -> None:
  if not orchestrator.progress_callback:
    return
  try:
    orchestrator.progress_callback(
      {
        "step": step,
        "message": message,
        "status": status,
        "detail": detail or {},
      }
    )
  except Exception:
    pass


def execute_stage(
  orchestrator: Any,
  stage_name: str,
  handler: Callable[[GenerationPipelineState], dict[str, Any]],
  state: GenerationPipelineState,
) -> None:
  started_at = time.time()
  emit_progress(orchestrator, f"stage.{stage_name}.started", f"Running {format_stage_name(stage_name)}")
  try:
    output = handler(state)
    duration_ms = round((time.time() - started_at) * 1000)
    summary = summarize_stage_output(output)
    state.stage_trace.append({"stage": stage_name, "status": "completed", "duration_ms": duration_ms, "summary": summary})
    emit_progress(
      orchestrator,
      f"stage.{stage_name}.completed",
      f"Completed {format_stage_name(stage_name)}",
      status="completed",
      detail={"duration_ms": duration_ms, "summary": summary},
    )
    if stage_name == "proactive_thinking" and state.response is not None:
      state.response["proactive_thinking"]["backend_execution"]["completed_stages"] = [
        entry for entry in state.stage_trace if entry["status"] == "completed"
      ]
  except Exception:
    duration_ms = round((time.time() - started_at) * 1000)
    state.stage_trace.append({"stage": stage_name, "status": "failed", "duration_ms": duration_ms})
    emit_progress(
      orchestrator,
      f"stage.{stage_name}.failed",
      f"Failed during {format_stage_name(stage_name)}",
      status="failed",
      detail={"duration_ms": duration_ms},
    )
    raise
