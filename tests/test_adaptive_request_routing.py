from __future__ import annotations

from backend.agents.request_complexity import (
  ADAPTIVE_ROUTE_ROUTING_PENDING,
  ADAPTIVE_ROUTE_FEATURE_UPDATE,
  ADAPTIVE_ROUTE_FULL_GENERATION,
  ADAPTIVE_ROUTE_LARGE_PROJECT,
  ADAPTIVE_ROUTE_SMALL_CODE,
  ADAPTIVE_ROUTE_TARGETED_UPDATE,
  ADAPTIVE_ROUTE_TINY_CHAT,
  adaptive_route_dict,
  classify_adaptive_request_route,
)


def test_preflight_routes_simple_greeting_to_tiny_chat() -> None:
  route = classify_adaptive_request_route("hi")

  assert route.route == ADAPTIVE_ROUTE_TINY_CHAT
  assert route.use_model_for_conversation is True
  assert route.use_project_context is False
  assert route.use_chat_history is False

  routed = classify_adaptive_request_route("hi", intent="greeting")
  assert routed.route == ADAPTIVE_ROUTE_TINY_CHAT
  assert routed.use_project_context is False
  assert routed.use_chat_history is False


def test_brief_extended_greeting_still_routes_to_tiny_chat() -> None:
  route = classify_adaptive_request_route("hiiiiii")

  assert route.route == ADAPTIVE_ROUTE_TINY_CHAT
  assert route.use_project_context is False
  assert route.use_chat_history is False


def test_standalone_code_uses_small_code_route_without_website_context() -> None:
  route = classify_adaptive_request_route(
    "write a code for neon number in python",
    intent="simple_code",
  )

  assert route.route == ADAPTIVE_ROUTE_SMALL_CODE
  assert route.context_mode == "code_only_minimal"
  assert route.max_existing_files == 1
  assert route.use_parallel_workers is False


def test_project_summary_prompt_defers_to_llm_before_adaptive_route() -> None:
  route = classify_adaptive_request_route("explain about this project")

  assert route.route == ADAPTIVE_ROUTE_ROUTING_PENDING
  assert route.use_project_context is False
  assert route.use_chat_history is True


def test_standalone_code_followup_uses_small_code_route() -> None:
  route = classify_adaptive_request_route(
    "this is very complicated so give me the simplified version",
    intent="simple_code",
    project_files=[
      {
        "path": "neon_number.py",
        "content": "def is_neon_number(number):\n  return number >= 0\n",
      }
    ],
  )

  assert route.route == ADAPTIVE_ROUTE_SMALL_CODE
  assert route.context_mode == "code_only_minimal"
  assert route.max_existing_files == 1
  assert route.max_new_files == 1


def test_small_website_update_uses_targeted_patch_route() -> None:
  route = classify_adaptive_request_route(
    "fix sidebar spacing on mobile",
    intent="website_update",
  )

  assert route.route == ADAPTIVE_ROUTE_TARGETED_UPDATE
  assert route.workflow == "scoped_patch_only"
  assert route.max_existing_files == 4


def test_bounded_feature_update_uses_staged_patch_route() -> None:
  route = classify_adaptive_request_route(
    "add login form to the dashboard",
    intent="website_update",
  )

  assert route.route == ADAPTIVE_ROUTE_FEATURE_UPDATE
  assert route.workflow == "staged_scoped_patches"
  assert route.max_new_files == 2


def test_page_specific_visual_addition_defers_to_llm_before_adaptive_route() -> None:
  route = classify_adaptive_request_route(
    "In analytics page below the Timeline Growth Metrics & Projections chart provide one pie chart"
  )

  assert route.route == ADAPTIVE_ROUTE_ROUTING_PENDING
  assert route.use_project_context is False
  assert route.use_chat_history is True


def test_page_specific_visual_addition_uses_feature_scope_after_llm_intent() -> None:
  route = classify_adaptive_request_route(
    "In analytics page below the Timeline Growth Metrics & Projections chart provide one pie chart",
    intent="website_update",
  )

  assert route.route == ADAPTIVE_ROUTE_FEATURE_UPDATE
  assert route.use_project_context is True
  assert route.use_chat_history is False


def test_button_navigation_bug_uses_feature_update_scope() -> None:
  route = classify_adaptive_request_route(
    "Launch operation hub button is not working; clicking it opens no page",
    intent="website_update",
  )

  assert route.route == ADAPTIVE_ROUTE_FEATURE_UPDATE
  assert route.context_mode == "feature_selected_files"
  assert route.max_existing_files == 8


def test_adaptive_route_dict_reports_actual_file_count_separately_from_budget() -> None:
  route = adaptive_route_dict(
    "fix dashboard button",
    intent="website_update",
    project_files=[{"path": f"src/File{i}.jsx", "content": ""} for i in range(27)],
  )

  assert route["project_file_count"] == 27
  assert route["max_existing_files"] == 8
  assert "context limits" in route["context_budget_note"]


def test_large_update_uses_parallel_worker_route() -> None:
  route = classify_adaptive_request_route(
    "redesign all pages and refactor frontend routing, navigation, layout, and theme",
    intent="website_update",
  )

  assert route.route == ADAPTIVE_ROUTE_LARGE_PROJECT
  assert route.use_parallel_workers is True


def test_normal_generation_uses_full_generation_route() -> None:
  route = classify_adaptive_request_route(
    "build a CRM website",
    intent="website_generation",
  )

  assert route.route == ADAPTIVE_ROUTE_FULL_GENERATION
  assert route.use_parallel_workers is True
