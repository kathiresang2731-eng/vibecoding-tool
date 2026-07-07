from __future__ import annotations

from typing import Any

from backend.agents.prompt_context import current_user_prompt


AGENTIC_PLATFORM_KNOWLEDGE: dict[str, dict[str, Any]] = {
  "codex": {
    "strengths": [
      "workspace-aware code edits",
      "terminal and test driven verification",
      "patch review with file-level safety",
    ],
    "decision_style": "Inspect the repository, apply scoped changes, verify with commands, and report concrete files.",
  },
  "cursor": {
    "strengths": [
      "current-file and multi-file context",
      "fast targeted refactors",
      "developer-in-the-loop editing",
    ],
    "decision_style": "Use open file, selected text, and nearby symbols to keep edits focused on the user's active task.",
  },
  "claude": {
    "strengths": [
      "large-context reasoning",
      "artifact-style implementation plans",
      "careful explanation and review",
    ],
    "decision_style": "Preserve broader intent, explain tradeoffs, and produce coherent artifacts or plans when code is not enough.",
  },
}


QUERY_CLASS_POLICIES: dict[str, dict[str, Any]] = {
  "conversation": {
    "handles": ["greeting", "question", "general_query", "project_info"],
    "policy": "Answer directly; do not mutate project files.",
  },
  "clarification": {
    "handles": ["needs_more_detail", "needs_confirmation"],
    "policy": "Ask for the missing decision before spending artifact tokens or editing files.",
  },
  "simple_code": {
    "handles": ["simple_code"],
    "policy": "Generate or update the smallest standalone code artifact.",
  },
  "website_generation": {
    "handles": ["website_generation"],
    "policy": "Build a complete runnable project with validation, preview, and persistence gates.",
  },
  "website_update": {
    "handles": ["website_update"],
    "policy": "Use existing project files, memory, scoped code anchors, local save, then post-update QA.",
  },
}


def _paths_summary(project_files: list[dict[str, Any]] | None, *, limit: int = 8) -> list[str]:
  paths = [
    str(item.get("path") or "").strip()
    for item in (project_files or [])
    if isinstance(item, dict) and str(item.get("path") or "").strip()
  ]
  return paths[:limit]


def _select_capabilities(*, prompt: str, intent: str, adaptive_route: dict[str, Any]) -> list[str]:
  lowered = current_user_prompt(prompt).lower()
  route = str(adaptive_route.get("route") or "")
  capabilities: list[str] = ["semantic_intent_routing", "request_understanding"]
  if intent in {"website_update", "website_generation", "simple_code"}:
    capabilities.extend(["project_file_awareness", "tool_execution", "code_validation"])
  if intent == "website_update":
    capabilities.extend(["topic_memory", "direct_project_update_planning", "post_update_visual_qa"])
  if route in {"large_project", "feature_update"}:
    capabilities.append("multi_agent_file_group_planning")
  if any(term in lowered for term in ("button", "click", "modal", "popup", "route", "navigate")):
    capabilities.append("interaction_contract_reasoning")
  if any(term in lowered for term in ("test", "bug", "error", "failed", "traceback", "debug")):
    capabilities.append("debug_and_test_repair")
  if intent in {"question", "general_query", "project_info"}:
    capabilities.append("read_only_answering")
  if intent == "project_info":
    capabilities.extend(["project_context_inspection", "context_reference_resolution"])
    if "button" in lowered and any(term in lowered for term in ("count", "total", "how many", "what are", "list")):
      capabilities.append("exact_ui_fact_counting")
  return list(dict.fromkeys(capabilities))


def _execution_plan_for_query(
  *,
  prompt: str,
  intent: str,
  adaptive_route: dict[str, Any],
  routing_result: dict[str, Any],
) -> dict[str, Any]:
  lowered = current_user_prompt(prompt).lower()
  request_kind = str(routing_result.get("request_kind") or routing_result.get("update_kind") or "").strip()
  route = str(adaptive_route.get("route") or "").strip()
  target_resolution = routing_result.get("target_resolution") if isinstance(routing_result.get("target_resolution"), dict) else {}
  interaction_like = any(term in lowered for term in ("button", "click", "modal", "popup", "pop up", "alert", "redirect", "navigate"))
  if intent in {"greeting", "question", "general_query", "project_info"}:
    return {
      "query_class": "answer_only",
      "mutation_allowed": False,
      "primary_path": "conversation_response",
      "model_use": "answer_synthesis_only",
      "qa_policy": "not_applicable",
      "target_resolution": target_resolution,
      "reason": "The user is asking for information, not a project file change.",
    }
  if intent in {"needs_more_detail", "needs_confirmation"}:
    return {
      "query_class": "clarification",
      "mutation_allowed": False,
      "primary_path": "clarify_before_execution",
      "model_use": "clarification_only",
      "qa_policy": "not_applicable",
      "target_resolution": target_resolution,
      "reason": "The request is underspecified or requires confirmation before work starts.",
    }
  if intent == "website_update":
    local_first = request_kind == "interaction_wiring_update" or interaction_like
    return {
      "query_class": "website_update",
      "mutation_allowed": True,
      "primary_path": "local_first_direct_update" if local_first else "direct_project_update",
      "fallback_path": "direct_workspace_agent_then_bounded_recovery" if local_first else "bounded_recovery_after_no_patch",
      "model_use": "skip_for_safe_local_interaction_patch" if local_first else "project_memory_workspace_tools",
      "qa_policy": "save_first_post_update_qa_advisory",
      "reason": (
        "Interaction wiring can be patched directly from real code anchors before spending model patch tokens."
        if local_first
        else "The update should use project memory and live workspace files directly instead of a scoped patch cage."
      ),
      "adaptive_route": route,
      "request_kind": request_kind or "unknown",
      "target_resolution": target_resolution,
    }
  if intent == "website_generation":
    return {
      "query_class": "website_generation",
      "mutation_allowed": True,
      "primary_path": "full_project_generation",
      "model_use": "generation_and_validation",
      "qa_policy": "build_and_visual_qa_before_ready_preview",
      "target_resolution": target_resolution,
      "reason": "The user is asking for a new or substantially regenerated website.",
    }
  if intent == "simple_code":
    return {
      "query_class": "simple_code",
      "mutation_allowed": True,
      "primary_path": "standalone_code_artifact",
      "model_use": "small_code_generation",
      "qa_policy": "syntax_validation",
      "target_resolution": target_resolution,
      "reason": "The user is asking for a small standalone code artifact.",
    }
  if intent == "document_artifact":
    return {
      "query_class": "document_artifact",
      "mutation_allowed": True,
      "primary_path": "document_artifact_generation",
      "model_use": "document_generation",
      "qa_policy": "format_validation",
      "target_resolution": target_resolution,
      "reason": "The user is asking for a documentation, planning, research, CSV, TXT, or PDF-ready artifact.",
    }
  return {
    "query_class": "unknown",
    "mutation_allowed": False,
    "primary_path": "clarify_before_execution",
    "model_use": "routing_repair_or_clarification",
    "qa_policy": "not_applicable",
    "target_resolution": target_resolution,
    "reason": "The orchestrator could not safely classify this request.",
  }


def build_orchestrator_brain(
  *,
  prompt: str,
  routing_result: dict[str, Any],
  adaptive_route: dict[str, Any],
  project_files: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
  """Return a compact decision profile for the main Worktual orchestrator."""
  intent = str(routing_result.get("intent") or "unknown")
  route = str(adaptive_route.get("route") or "unknown")
  matching_policy = next(
    (
      {"query_class": name, **policy}
      for name, policy in QUERY_CLASS_POLICIES.items()
      if intent in set(policy.get("handles") or [])
    ),
    {
      "query_class": "unknown",
      "handles": [],
      "policy": "Prefer clarification over guessing when the request cannot be safely classified.",
    },
  )
  return {
    "name": "worktual-main-orchestrator-brain",
    "version": "2026-07-06",
    "decision_source": "orchestrator_brain_profile",
    "intent": intent,
    "adaptive_route": route,
    "query_policy": matching_policy,
    "execution_plan": _execution_plan_for_query(
      prompt=prompt,
      intent=intent,
      adaptive_route=adaptive_route,
      routing_result=routing_result,
    ),
    "target_resolution": (
      routing_result.get("target_resolution")
      if isinstance(routing_result.get("target_resolution"), dict)
      else {}
    ),
    "selected_capabilities": _select_capabilities(
      prompt=prompt,
      intent=intent,
      adaptive_route=adaptive_route,
    ),
    "agentic_platform_knowledge": AGENTIC_PLATFORM_KNOWLEDGE,
    "decision_principles": [
      "Route every turn before spending artifact tokens.",
      "Prefer read-only answers for questions and project-info requests.",
      "Resolve contextual references such as that page, this screen, or the current module from recent chat before answering.",
      "For exact project-info questions, prefer parsed live-file facts over model inference.",
      "For existing website updates, use actual files, memory, and code anchors before editing.",
      "Save validated local edits before post-update QA so useful patches are not lost.",
      "Treat infrastructure QA crashes as validation signals, not proof that code was not written.",
      "Ask for clarification when the user goal is underspecified or unsafe to infer.",
    ],
    "project_context": {
      "file_count": len(project_files or []),
      "sample_paths": _paths_summary(project_files),
    },
  }
