from __future__ import annotations

import json
import os
from queue import Empty, Queue
from threading import Thread
from typing import Any

try:
  from ...audit_logging import current_telemetry_context, log_query_event, run_with_telemetry_context
except ImportError:
  from audit_logging import current_telemetry_context, log_query_event, run_with_telemetry_context

from ..adk_mapping import format_adk_mapping_for_prompt
from ..domain_research import build_domain_research_context, enrich_brief_with_domain_research
from ..prompts import build_domain_research_prompt, build_website_prompt
from .compaction import (
  compact_existing_files,
  compact_files_for_prompt,
  compact_memories_for_prompt,
  compact_prepared_sections_for_artifact,
  compact_value_for_artifact_prompt,
  select_update_files_for_prompt,
)
from .prompts import build_planner_runtime_prompt, build_prompt_analyst_runtime_prompt, build_review_agent_prompt
from .state import runtime_operation_from_routing
from .timeouts import artifact_call_soft_timeout_seconds
from .values import object_value, string_list, text_or_default


def run_review_agent(
  control_provider: Any,
  *,
  trace_label: str,
  system_instruction: str,
  prompt: str,
  state: dict[str, Any],
) -> dict[str, Any]:
  try:
    response = control_provider.generate_json(
      build_review_agent_prompt(
        prompt=prompt,
        brief=object_value(state.get("brief")),
        plan=object_value(state.get("plan")),
      ),
      system_instruction=system_instruction,
      trace_label=trace_label,
    )
  except Exception as exc:
    return deterministic_review_fallback(trace_label=trace_label, error=exc)
  if not isinstance(response, dict):
    response = {}
  return {
    "status": text_or_default(response.get("status"), "reviewed"),
    "issues": string_list(response.get("issues"), []),
    "recommendations": string_list(response.get("recommendations"), []),
  }

def run_prompt_analyst_agent(
  control_provider: Any,
  prompt: str,
  routing_result: dict[str, Any],
  read_result: dict[str, Any],
  memory_result: dict[str, Any],
) -> dict[str, Any]:
  operation = runtime_operation_from_routing(routing_result)
  agent_prompt = build_prompt_analyst_runtime_prompt(
    operation=operation,
    user_prompt=prompt,
    routing_result=routing_result,
    file_index=read_result.get("file_index", []),
    existing_files=compact_files_for_prompt(read_result.get("files", []), max_files=8, max_content_chars=700),
    memories=compact_memories_for_prompt(memory_result.get("memories", []), max_items=6, max_content_chars=700),
  )
  try:
    response = control_provider.generate_json(
      agent_prompt,
      system_instruction="You are a prompt analyst agent. Return strict JSON only.",
      trace_label="prompt_analyst_agent",
    )
  except Exception as exc:
    brief = deterministic_prompt_brief_fallback(prompt, operation=operation, error=exc)
  else:
    brief = normalize_brief(response, prompt)
  brief["operation"] = operation
  if operation == "update" and not brief.get("update_goal"):
    brief["update_goal"] = prompt
  domain_research = build_runtime_domain_research_context(
    control_provider,
    prompt,
    memories=list(memory_result.get("memories") or []),
    brief=brief,
  )
  brief = enrich_brief_with_domain_research(prompt, brief, domain_research)
  return brief


def build_runtime_domain_research_context(
  control_provider: Any,
  prompt: str,
  *,
  memories: list[dict[str, Any]],
  brief: dict[str, Any],
) -> dict[str, Any]:
  fallback = build_domain_research_context(prompt, memories=memories, brief=brief)
  if not gemini_google_search_enabled():
    return fallback
  generator = getattr(control_provider, "generate_json_with_search", None)
  if not callable(generator):
    return fallback
  try:
    searched = generator(
      build_domain_research_prompt(prompt, fallback),
      system_instruction="You are a website domain research agent. Return strict JSON only.",
      trace_label="domain_research_agent",
    )
  except Exception as exc:
    enriched_fallback = dict(fallback)
    enriched_fallback["search_status"] = "fallback"
    enriched_fallback["search_error"] = str(exc)[:400]
    return enriched_fallback
  normalized = normalize_domain_research_response(searched, fallback=fallback)
  if normalized.get("status") != "applied":
    return fallback
  return normalized


def gemini_google_search_enabled() -> bool:
  raw = os.getenv("ENABLE_GEMINI_GOOGLE_SEARCH", "true").strip().lower()
  return raw not in {"0", "false", "no", "off"}


def normalize_domain_research_response(response: Any, *, fallback: dict[str, Any]) -> dict[str, Any]:
  if not isinstance(response, dict):
    return fallback
  normalized = dict(fallback)
  for key in (
    "status",
    "source",
    "domain",
    "display_name",
    "confidence",
    "reason",
    "web_search_query",
    "audience",
    "goal",
    "style",
  ):
    value = response.get(key)
    if isinstance(value, str) and value.strip():
      normalized[key] = value.strip()
  for key in ("assumptions", "required_sections", "interactions", "content_requirements"):
    value = response.get(key)
    if isinstance(value, list) and value:
      normalized[key] = [str(item).strip() for item in value if str(item).strip()]
  sample_products = response.get("sample_products")
  if isinstance(sample_products, list) and sample_products:
    normalized["sample_products"] = [item for item in sample_products if isinstance(item, dict)]
  sources = response.get("sources")
  if isinstance(sources, list):
    normalized["sources"] = [
      {
        "title": text_or_default(object_value(item).get("title"), ""),
        "url": text_or_default(object_value(item).get("url"), ""),
      }
      for item in sources
      if isinstance(item, dict)
    ]
  normalized["source"] = "gemini_google_search"
  normalized["search_status"] = "applied"
  return normalized


def run_planner_agent(
  control_provider: Any,
  prompt: str,
  brief: dict[str, Any],
  prepared_sections: dict[str, Any],
  memory_result: dict[str, Any],
) -> dict[str, Any]:
  operation = text_or_default(brief.get("operation"), "generate")
  agent_prompt = build_planner_runtime_prompt(
    operation=operation,
    user_prompt=prompt,
    brief=brief,
    memories=compact_memories_for_prompt(memory_result.get("memories", []), max_items=6, max_content_chars=700),
    prepared_section_keys=list(prepared_sections.keys()),
  )
  try:
    response = control_provider.generate_json(
      agent_prompt,
      system_instruction="You are a website planning agent. Return strict JSON only.",
      trace_label="planner_agent",
    )
  except Exception as exc:
    return deterministic_plan_fallback(brief, error=exc)
  return normalize_plan(response, brief)


def run_code_agent(
  artifact_provider: Any,
  *,
  prompt: str,
  operation: str,
  brief: dict[str, Any],
  plan: dict[str, Any],
  prepared_sections: dict[str, Any],
  read_result: dict[str, Any],
  memory_result: dict[str, Any],
  previous_error: str | None,
) -> dict[str, Any]:
  compact_prepared_sections = compact_prepared_sections_for_artifact(prepared_sections)
  if operation == "update":
    existing_files_context, context_budget = select_update_files_for_prompt(
      read_result.get("files", []),
      prompt=prompt,
      update_analysis=object_value(prepared_sections.get("update_analysis")),
    )
  else:
    existing_files_context = compact_existing_files(read_result.get("files", [])[:12])
    context_budget = {
      "mode": "generation",
      "max_files": 12,
      "selected_file_count": len(existing_files_context),
      "candidate_file_count": len(read_result.get("files", []) or []),
    }
  log_query_event(
    "artifact_prompt.context_budget",
    payload={
      "operation": operation,
      **context_budget,
    },
  )
  pipeline_context = {
    **compact_prepared_sections,
    "real_agent_runtime": {
      "operation": operation,
      "brief": compact_value_for_artifact_prompt(brief, max_chars=36_000),
      "plan": compact_value_for_artifact_prompt(plan, max_chars=24_000),
      "domain_research": object_value(brief.get("domain_research")),
      "project_file_index": read_result.get("file_index", []),
      "existing_files": existing_files_context,
      "context_budget": context_budget,
      "relevant_memory": compact_memories_for_prompt(
        memory_result.get("memories", []),
        max_items=12,
        max_content_chars=1_800,
      ),
      "unified_memory_context": text_or_default(memory_result.get("unified_context"), "")[:16_000],
      "previous_build_error": previous_error,
      "tool_policy": "Return artifact JSON only. The runtime will validate, stage-preview, commit files, and repair through tools.",
    },
  }
  if previous_error:
    prompt = (
      f"{prompt}\n\nRepair the generated website so validation, staged preview, and visual QA pass. "
      f"Previous failure:\n{previous_error[:8_000]}"
    )
  trace_label = "repair_website_artifact" if previous_error else "update_website_artifact" if operation == "update" else "generate_website_artifact"
  artifact_prompt = build_website_prompt(
    prompt,
    adk_mapping=format_adk_mapping_for_prompt(),
    pipeline_context=json.dumps(pipeline_context, indent=2),
    artifact_mode="website_update" if operation == "update" else "website_generation",
  )
  response = run_artifact_provider_with_soft_timeout(
    artifact_provider,
    artifact_prompt,
    trace_label=trace_label,
    prompt_fragments_used=[
      "user_prompt",
      "brief",
      "plan",
      "project_file_index",
      "selected_files",
      "relevant_memory",
      "artifact_policy",
    ],
    selected_files=[
      str(file_item.get("path") or "")
      for file_item in existing_files_context
      if isinstance(file_item, dict) and str(file_item.get("path") or "")
    ],
    memory_items_used=len(memory_result.get("memories", []) or []),
  )
  if isinstance(response, dict):
    response["_context_budget"] = context_budget
  return response


def run_artifact_provider_with_soft_timeout(
  artifact_provider: Any,
  prompt: str,
  *,
  trace_label: str,
  system_instruction: str | None = None,
  response_schema: dict[str, Any] | None = None,
  max_output_tokens: int | None = None,
  timeout_seconds: int | None = None,
  prompt_fragments_used: list[str] | None = None,
  selected_files: list[str] | None = None,
  memory_items_used: int = 0,
) -> dict[str, Any]:
  timeout_seconds = artifact_call_soft_timeout_seconds(trace_label) if timeout_seconds is None else timeout_seconds
  if timeout_seconds <= 0:
    return artifact_provider.generate_json(
      prompt,
      system_instruction=system_instruction,
      trace_label=trace_label,
      response_schema=response_schema,
      max_output_tokens=max_output_tokens,
      prompt_fragments_used=prompt_fragments_used,
      selected_files=selected_files,
      memory_items_used=memory_items_used,
    )

  result_queue: Queue[tuple[str, Any]] = Queue(maxsize=1)
  telemetry = current_telemetry_context()

  def target() -> None:
    try:
      result_queue.put(
        (
          "ok",
          run_with_telemetry_context(
            telemetry,
            artifact_provider.generate_json,
            prompt,
            system_instruction=system_instruction,
            trace_label=trace_label,
            response_schema=response_schema,
            max_output_tokens=max_output_tokens,
            prompt_fragments_used=prompt_fragments_used,
            selected_files=selected_files,
            memory_items_used=memory_items_used,
          ),
        )
      )
    except Exception as exc:
      result_queue.put(("error", exc))

  worker = Thread(target=target, name=f"artifact-provider-{trace_label}", daemon=True)
  worker.start()
  worker.join(timeout_seconds)
  if worker.is_alive():
    raise RuntimeError(
      f"Artifact model call timed out after {timeout_seconds}s before a valid artifact was returned. "
      "Increase the artifact/repair model soft timeout env var or set it to 0 to disable this extra soft timeout."
    )
  try:
    status, value = result_queue.get_nowait()
  except Empty as exc:
    raise RuntimeError("Artifact model call finished without returning a result.") from exc
  if status == "error":
    raise value
  if not isinstance(value, dict):
    raise RuntimeError("Artifact model returned a non-JSON object response.")
  return value

def normalize_brief(response: Any, prompt: str) -> dict[str, Any]:
  if not isinstance(response, dict):
    response = {}
  operation = text_or_default(response.get("operation"), "")
  if not operation:
    operation = "update" if response.get("update_goal") or response.get("files_to_preserve") or response.get("likely_files_to_change") else "generate"
  return {
    "operation": operation if operation in {"generate", "update"} else "generate",
    "business_type": text_or_default(response.get("business_type"), "Website"),
    "audience": text_or_default(response.get("audience"), "Target users from the prompt"),
    "goal": text_or_default(response.get("goal"), prompt),
    "style": text_or_default(response.get("style"), "Modern, responsive, navy/teal Worktual-aligned UI"),
    "required_sections": string_list(response.get("required_sections"), ["Hero", "Features", "Contact"]),
    "missing_information": string_list(response.get("missing_information"), []),
    "update_goal": text_or_default(response.get("update_goal"), prompt) if operation == "update" else "",
    "files_to_preserve": string_list(response.get("files_to_preserve"), []) if operation == "update" else [],
    "likely_files_to_change": string_list(response.get("likely_files_to_change"), ["src/App.jsx"]) if operation == "update" else [],
  }


def deterministic_prompt_brief_fallback(prompt: str, *, operation: str, error: Exception) -> dict[str, Any]:
  brief = normalize_brief({}, prompt)
  brief["operation"] = operation
  if operation == "update":
    brief["update_goal"] = prompt
    brief["likely_files_to_change"] = ["src/App.jsx"]
  brief["control_fallback"] = {
    "source": "deterministic_prompt_analyst",
    "reason": str(error)[:240],
  }
  return brief


def normalize_plan(response: Any, brief: dict[str, Any]) -> dict[str, Any]:
  if not isinstance(response, dict):
    response = {}
  sections = response.get("sections")
  if not isinstance(sections, list) or not sections:
    sections = brief.get("required_sections") or ["Hero", "Features", "Contact"]
  operation = text_or_default(brief.get("operation"), "generate")
  return {
    "operation": operation,
    "sections": string_list(sections, ["Hero", "Features", "Contact"]),
    "layout_strategy": text_or_default(response.get("layout_strategy"), "Single-page responsive marketing website"),
    "interactions": string_list(response.get("interactions"), ["Primary CTA", "Responsive navigation"]),
    "quality_checks": string_list(response.get("quality_checks"), ["Vite build passes", "Mobile layout fits", "Accessible text contrast"]),
    "update_strategy": text_or_default(response.get("update_strategy"), "Apply requested changes while preserving unrelated project files.") if operation == "update" else "",
    "files_to_change": string_list(response.get("files_to_change"), brief.get("likely_files_to_change") or ["src/App.jsx"]) if operation == "update" else [],
    "preserve_rules": string_list(response.get("preserve_rules"), ["Do not remove unrelated existing files.", "Only override files returned by the artifact generator."]) if operation == "update" else [],
  }


def deterministic_plan_fallback(brief: dict[str, Any], *, error: Exception) -> dict[str, Any]:
  plan = normalize_plan({}, brief)
  plan["control_fallback"] = {
    "source": "deterministic_planner",
    "reason": str(error)[:240],
  }
  return plan

def deterministic_review_fallback(*, trace_label: str, error: Exception) -> dict[str, Any]:
  return {
    "status": "reviewed",
    "issues": [f"Gemini review unavailable: {str(error)[:240]}"],
    "recommendations": [
      "Use conservative responsive spacing, accessible contrast, semantic sections, and clear CTA hierarchy.",
      "Rely on artifact validation, staged Vite preview, and visual QA before committing generated files.",
    ],
    "control_fallback": {
      "source": f"deterministic_{trace_label}",
      "reason": str(error)[:240],
    },
  }
