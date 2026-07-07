from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

try:
  from ...runtime_control import submit_with_runtime_context
except ImportError:
  from runtime_control import submit_with_runtime_context
from .model_agents import run_review_agent


def run_parallel_tasks(
  tasks: dict[str, Callable[[], Any]],
  *,
  max_workers: int | None = None,
  engine: str = "thread_pool",
) -> dict[str, Any]:
  if not tasks:
    return {}
  worker_count = max_workers or min(4, len(tasks))
  results: dict[str, Any] = {}
  with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="worktual-parallel") as pool:
    futures = {key: submit_with_runtime_context(pool, worker) for key, worker in tasks.items()}
    for key, future in futures.items():
      results[key] = future.result()
  results["parallel_execution_engine"] = engine
  return results


def run_parallel_review_agents(
  control_provider: Any,
  *,
  state: dict[str, Any],
) -> dict[str, Any]:
  return run_parallel_tasks(
    {
      "ux_review": lambda: run_review_agent(
        control_provider,
        trace_label="ux_review_agent",
        system_instruction="You are a UX review agent. Return strict JSON only.",
        prompt="Review the website plan for user workflow, conversion clarity, responsive layout, and missing content.",
        state=state,
      ),
      "accessibility_review": lambda: run_review_agent(
        control_provider,
        trace_label="accessibility_review_agent",
        system_instruction="You are an accessibility review agent. Return strict JSON only.",
        prompt="Review the website plan for color contrast, semantic structure, keyboard flow, and mobile text fit.",
        state=state,
      ),
    },
    max_workers=2,
    engine="thread_pool_reviews",
  )


def bootstrap_read_result(ctx: Any) -> dict[str, Any]:
  from .actions.project_io import build_project_read_result

  return build_project_read_result(ctx)


def bootstrap_memory_result(ctx: Any) -> dict[str, Any]:
  from .actions.project_io import build_project_memory_result

  return build_project_memory_result(ctx)


def run_parallel_project_bootstrap(ctx: Any) -> dict[str, Any]:
  # Read + memory load both mutate ctx.state; keep sequential to avoid dict iteration races.
  return {
    "read_result": bootstrap_read_result(ctx),
    "memory_result": bootstrap_memory_result(ctx),
  }
