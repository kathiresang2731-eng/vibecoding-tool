from __future__ import annotations

import os
import re

from .request_complexity import (
  ADAPTIVE_ROUTE_FULL_GENERATION,
  ADAPTIVE_ROUTE_LARGE_PROJECT,
  classify_adaptive_request_route,
)


def agentic_parity_target() -> int:
  raw = str(os.getenv("AGENTIC_PARITY_TARGET", "48")).strip()
  try:
    value = int(raw)
  except ValueError:
    return 48
  return max(0, min(value, 100))


def high_agentic_parity_enabled() -> bool:
  return agentic_parity_target() >= 90


def env_bool(name: str, *, legacy_default: bool, parity_default: bool | None = None) -> bool:
  raw = str(os.getenv(name, "")).strip().lower()
  if raw in {"1", "true", "yes", "on"}:
    return True
  if raw in {"0", "false", "no", "off"}:
    return False
  if high_agentic_parity_enabled() and parity_default is not None:
    return parity_default
  return legacy_default


def unified_update_engine_enabled() -> bool:
  return env_bool("ENABLE_UNIFIED_UPDATE_ENGINE", legacy_default=True, parity_default=True)


def code_index_enabled() -> bool:
  return env_bool("ENABLE_CODE_INDEX", legacy_default=True, parity_default=True)


def legacy_parallel_updates_enabled() -> bool:
  """When false, website intents use unified streaming agent only."""
  return env_bool("ENABLE_LEGACY_PARALLEL_UPDATES", legacy_default=False, parity_default=False)


def unified_website_updates_active() -> bool:
  """Default website update path: ScopeEngine + single streaming agent (no legacy parallel/LangGraph)."""
  return unified_update_engine_enabled() and not legacy_parallel_updates_enabled()


def runtime_engine() -> str:
  raw = str(os.getenv("RUNTIME_ENGINE", "")).strip().lower()
  if raw in {"langgraph", "legacy_python_loop"}:
    return raw
  return "langgraph"


def full_dynamic_generation_enabled() -> bool:
  return env_bool("ENABLE_FULL_DYNAMIC_GENERATION", legacy_default=False, parity_default=True)


def gemini_supervisor_enabled() -> bool:
  return env_bool("ENABLE_GEMINI_SUPERVISOR", legacy_default=False, parity_default=True)


def dynamic_agent_tool_loop_enabled() -> bool:
  return env_bool("ENABLE_DYNAMIC_AGENT_TOOL_LOOP", legacy_default=False, parity_default=True)


def langgraph_checkpoint_enabled() -> bool:
  return env_bool("LANGGRAPH_CHECKPOINT_ENABLED", legacy_default=False, parity_default=True)


def runtime_parallel_actions_enabled() -> bool:
  return env_bool("ENABLE_RUNTIME_PARALLEL_ACTIONS", legacy_default=True, parity_default=True)


def parallel_stream_orchestrator_enabled() -> bool:
  if not legacy_parallel_updates_enabled():
    return False
  return env_bool("ENABLE_PARALLEL_STREAM_ORCHESTRATOR", legacy_default=True, parity_default=True)


def streaming_file_agent_enabled() -> bool:
  return env_bool("ENABLE_STREAMING_FILE_AGENT", legacy_default=True, parity_default=True)


def parallel_file_workers_enabled() -> bool:
  if not legacy_parallel_updates_enabled():
    return False
  return env_bool("ENABLE_PARALLEL_FILE_WORKERS", legacy_default=True, parity_default=True)


def parallel_website_generation_default() -> bool:
  """Prefer parallel file workers over sequential LangGraph for website intents."""
  if not legacy_parallel_updates_enabled():
    return False
  return env_bool("ENABLE_PARALLEL_WEBSITE_GENERATION", legacy_default=True, parity_default=True)


def parallel_greenfield_generation_enabled() -> bool:
  """Run many parallel workers for empty/greenfield projects.

  Disabled by default: one streaming agent is cheaper (~10-15 calls) and produces
  coherent imports. Parallel greenfield can exceed 50 model calls for a CRM build.
  """
  return env_bool("ENABLE_PARALLEL_GREENFIELD_GENERATION", legacy_default=False, parity_default=False)


def greenfield_parallel_workers_enabled() -> bool:
  """Parallel page workers for website_generation only — independent of legacy update paths."""
  if parallel_greenfield_generation_enabled():
    return True
  return env_bool("ENABLE_GREENFIELD_PARALLEL_WORKERS", legacy_default=True, parity_default=True)


def adaptive_parallel_updates_enabled() -> bool:
  return env_bool("ENABLE_ADAPTIVE_PARALLEL_UPDATES", legacy_default=True, parity_default=True)


def should_use_parallel_website_workflow(*, intent: str, prompt: str) -> bool:
  adaptive_route = classify_adaptive_request_route(prompt, intent=intent)
  if adaptive_route.route in {ADAPTIVE_ROUTE_LARGE_PROJECT, ADAPTIVE_ROUTE_FULL_GENERATION}:
    return True
  if intent != "website_update" or not adaptive_parallel_updates_enabled():
    return False

  normalized = str(prompt or "").strip().lower()
  if not normalized:
    return False

  broad_update_signals = (
    "entire website",
    "whole website",
    "all pages",
    "every page",
    "complete website",
    "redesign",
    "rebuild",
    "regenerate",
    "single static page",
    "static page",
    "missing module",
    "missing modules",
    "not based on requirement",
    "failed to generate",
    "new feature",
    "add feature",
    "authentication flow",
    "dashboard flow",
    "responsive across",
    "site-wide",
    "sitewide",
    "refactor",
    "migration",
  )
  if any(signal in normalized for signal in broad_update_signals):
    return True

  mentioned_paths = set(
    re.findall(
      r"\b(?:src/)?[a-z0-9_.-]+(?:/[a-z0-9_.-]+)+\.(?:js|jsx|ts|tsx|css|html|json|py)\b",
      normalized,
    )
  )
  if len(mentioned_paths) >= 3:
    return True

  scope_terms = {
    token
    for token in re.findall(r"[a-z0-9]+", normalized)
    if token in {"frontend", "backend", "database", "api", "routing", "navigation", "layout", "theme"}
  }
  return len(scope_terms) >= 3


def parallel_file_worker_max() -> int:
  raw = str(os.getenv("PARALLEL_FILE_WORKER_MAX", "6")).strip()
  try:
    return max(1, min(int(raw), 12))
  except ValueError:
    return 6


def parallel_greenfield_max_tasks() -> int:
  raw = str(os.getenv("PARALLEL_GREENFIELD_MAX_TASKS", "8")).strip()
  try:
    return max(4, min(int(raw), 20))
  except ValueError:
    return 8


def parallel_model_call_budget(*, intent: str) -> int:
  env_name = "PARALLEL_UPDATE_MODEL_CALL_BUDGET" if intent == "website_update" else "PARALLEL_GENERATION_MODEL_CALL_BUDGET"
  # Three greenfield workers may each own several files. Keep enough calls for
  # one write per planned path plus a small verification margin.
  fallback = 12 if intent == "website_update" else 40
  raw = str(os.getenv(env_name, str(fallback))).strip()
  try:
    value = int(raw)
  except ValueError:
    value = fallback
  return max(4, min(value, 80))


def parallel_update_preflight_enabled() -> bool:
  return env_bool("ENABLE_PARALLEL_UPDATE_PREFLIGHT", legacy_default=True, parity_default=True)


def parallel_update_llm_analysis_enabled() -> bool:
  return env_bool("ENABLE_PARALLEL_UPDATE_LLM_ANALYSIS", legacy_default=True, parity_default=True)


def parallel_update_llm_timeout_seconds() -> int:
  raw = str(os.getenv("PARALLEL_UPDATE_LLM_TIMEOUT_SECONDS", "45")).strip()
  try:
    return max(10, min(int(raw), 120))
  except ValueError:
    return 45


def parallel_worker_timeout_seconds() -> int:
  raw = str(os.getenv("PARALLEL_WORKER_TIMEOUT_SECONDS", "180")).strip()
  try:
    return max(30, int(raw))
  except ValueError:
    return 180


def streaming_path_parity_enabled() -> bool:
  return env_bool("ENABLE_STREAMING_PATH_PARITY", legacy_default=True, parity_default=True)


def post_update_build_gate_enabled() -> bool:
  return env_bool("ENABLE_POST_UPDATE_BUILD_GATE", legacy_default=True, parity_default=True)


def build_gate_rollback_on_failure() -> bool:
  """When False (default), syntax-clean files stay committed even if preview build fails."""
  return env_bool("BUILD_GATE_ROLLBACK_ON_FAILURE", legacy_default=False, parity_default=False)


def post_update_visual_qa_enabled() -> bool:
  return env_bool("ENABLE_POST_UPDATE_VISUAL_QA", legacy_default=True, parity_default=True)


def streaming_fast_path_enabled() -> bool:
  return env_bool("ENABLE_STREAMING_FAST_PATH", legacy_default=False, parity_default=False)


def langgraph_runtime_default() -> bool:
  if streaming_fast_path_enabled():
    return False
  return env_bool("RUNTIME_DEFAULT_LANGGRAPH", legacy_default=False, parity_default=True)


def use_v1_runs_stream() -> bool:
  return env_bool("USE_V1_RUNS_STREAM", legacy_default=False, parity_default=False)


def patch_approval_enabled() -> bool:
  return env_bool("ENABLE_PATCH_APPROVAL", legacy_default=False, parity_default=False)


def platform_pattern_min_source_count() -> int:
  raw = str(os.getenv("PLATFORM_PATTERN_MIN_SOURCE_COUNT", "2")).strip()
  try:
    value = int(raw)
  except ValueError:
    return 2
  return max(1, min(value, 10))


def platform_failed_run_learning_enabled() -> bool:
  return env_bool("ENABLE_PLATFORM_FAILED_RUN_LEARNING", legacy_default=True, parity_default=True)


def legacy_episodic_read_enabled() -> bool:
  return env_bool("ENABLE_LEGACY_EPISODIC_READ", legacy_default=False, parity_default=False)


def episodic_hybrid_retrieval_enabled() -> bool:
  return env_bool("ENABLE_EPISODIC_HYBRID_RETRIEVAL", legacy_default=True, parity_default=True)


def episodic_vector_search_enabled() -> bool:
  try:
    from .memory.episode_vector_store import episodic_vector_search_enabled as _enabled
  except ImportError:
    from agents.memory.episode_vector_store import episodic_vector_search_enabled as _enabled

  return _enabled()


def qdrant_episode_search_enabled() -> bool:
  try:
    from .memory.episode_vector_store import qdrant_episode_search_enabled as _enabled
  except ImportError:
    from agents.memory.episode_vector_store import qdrant_episode_search_enabled as _enabled

  return _enabled()


def runtime_graph_topology() -> str:
  raw = str(os.getenv("RUNTIME_GRAPH_TOPOLOGY", "")).strip().lower()
  if raw in {"flat", "hierarchical"}:
    return raw
  if high_agentic_parity_enabled():
    return "hierarchical"
  return "flat"


def langgraph_website_runtime_enabled() -> bool:
  """LangGraph for website intents — off by default under unified engine."""
  if unified_update_engine_enabled() and not legacy_parallel_updates_enabled():
    return env_bool("ENABLE_LANGGRAPH_WEBSITE_RUNTIME", legacy_default=False, parity_default=False)
  return langgraph_runtime_default()
