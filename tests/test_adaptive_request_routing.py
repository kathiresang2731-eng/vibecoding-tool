from __future__ import annotations

from backend.agents.request_complexity import (
  ADAPTIVE_ROUTE_FEATURE_UPDATE,
  ADAPTIVE_ROUTE_FULL_GENERATION,
  ADAPTIVE_ROUTE_LARGE_PROJECT,
  ADAPTIVE_ROUTE_SMALL_CODE,
  ADAPTIVE_ROUTE_TARGETED_UPDATE,
  ADAPTIVE_ROUTE_TINY_CHAT,
  classify_adaptive_request_route,
)


def test_tiny_chat_uses_no_context_or_model() -> None:
  route = classify_adaptive_request_route("hi")

  assert route.route == ADAPTIVE_ROUTE_TINY_CHAT
  assert route.use_project_context is False
  assert route.use_chat_history is False
  assert route.use_model_for_conversation is False


def test_standalone_code_uses_small_code_route_without_website_context() -> None:
  route = classify_adaptive_request_route("write a code for neon number in python")

  assert route.route == ADAPTIVE_ROUTE_SMALL_CODE
  assert route.context_mode == "code_only_minimal"
  assert route.max_existing_files == 1
  assert route.use_parallel_workers is False


def test_standalone_code_followup_uses_small_code_route() -> None:
  route = classify_adaptive_request_route(
    "this is very complicated so give me the simplified version",
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


def test_large_update_uses_parallel_worker_route() -> None:
  route = classify_adaptive_request_route(
    "redesign all pages and refactor frontend routing, navigation, layout, and theme",
    intent="website_update",
  )

  assert route.route == ADAPTIVE_ROUTE_LARGE_PROJECT
  assert route.use_parallel_workers is True


def test_normal_generation_uses_full_generation_route() -> None:
  route = classify_adaptive_request_route("build a CRM website")

  assert route.route == ADAPTIVE_ROUTE_FULL_GENERATION
  assert route.use_parallel_workers is True
