from __future__ import annotations

from typing import Any, Callable

from backend.agents.request_complexity import (
  ADAPTIVE_ROUTE_CONVERSATION,
  ADAPTIVE_ROUTE_FEATURE_UPDATE,
  ADAPTIVE_ROUTE_FULL_GENERATION,
  ADAPTIVE_ROUTE_LARGE_PROJECT,
  ADAPTIVE_ROUTE_ROUTING_PENDING,
  ADAPTIVE_ROUTE_SMALL_CODE,
  ADAPTIVE_ROUTE_TARGETED_UPDATE,
  classify_adaptive_request_route,
)


def resolve_adaptive_route(
  *,
  orchestrator: Any,
  initial_execution_prompt: str,
  execution_prompt: str,
  routing_result: dict[str, Any],
  project_files_for_routing: Callable[[], list[dict[str, Any]]],
) -> dict[str, Any]:
  restored_confirmed_request = execution_prompt != initial_execution_prompt
  if restored_confirmed_request:
    adaptive_route = classify_adaptive_request_route(
      execution_prompt,
      intent=routing_result.get("intent"),
      project_files=project_files_for_routing(),
      attachments=orchestrator.attachments,
    ).to_dict()
    adaptive_route["reclassified_after_confirmation"] = True
  else:
    final_adaptive_route = classify_adaptive_request_route(
      execution_prompt,
      intent=routing_result.get("intent"),
      project_files=project_files_for_routing(),
      attachments=orchestrator.attachments,
    ).to_dict()
    preflight_route = orchestrator.adaptive_route or {}
    preflight_route_name = str(preflight_route.get("route") or "")
    final_route_name = str(final_adaptive_route.get("route") or "")
    if (
      final_route_name == ADAPTIVE_ROUTE_CONVERSATION
      or preflight_route_name == ADAPTIVE_ROUTE_ROUTING_PENDING
      or (
        preflight_route_name in {ADAPTIVE_ROUTE_FULL_GENERATION, ADAPTIVE_ROUTE_LARGE_PROJECT}
        and final_route_name in {ADAPTIVE_ROUTE_SMALL_CODE, ADAPTIVE_ROUTE_TARGETED_UPDATE, ADAPTIVE_ROUTE_FEATURE_UPDATE}
      )
    ):
      adaptive_route = final_adaptive_route
      adaptive_route["reclassified_after_final_intent"] = True
      adaptive_route["previous_preflight_route"] = preflight_route_name
    else:
      adaptive_route = preflight_route or final_adaptive_route
  return adaptive_route
