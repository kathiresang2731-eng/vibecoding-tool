from __future__ import annotations

from typing import Any

from .phases import PLATFORM_PHASES, current_platform_phase

PLATFORM_PARITY_ITEMS: tuple[dict[str, Any], ...] = (
  {"id": "unified_run_api", "label": "Unified run API", "status": "partial", "touchpoint": "backend/api/v1/runs.py"},
  {"id": "streaming_events", "label": "Streaming event contract", "status": "partial", "touchpoint": "backend/api/v1/events.py"},
  {"id": "live_runtime_trace", "label": "Live runtime trace (source of truth)", "status": "done", "touchpoint": "backend/agents/orchestration/live_runtime_trace.py"},
  {"id": "hierarchical_mas", "label": "Hierarchical MAS orchestration", "status": "done", "touchpoint": "backend/agents/graph_runtime/hierarchical_runtime_graph.py"},
  {"id": "context_engine", "label": "Context engine (index + search)", "status": "partial", "touchpoint": "backend/context/search/"},
  {"id": "patch_first_edits", "label": "Patch-first file edits", "status": "partial", "touchpoint": "backend/execution/patch/, agent_runtime/patch_staging.py"},
  {"id": "terminal_sandbox", "label": "Terminal sandbox", "status": "partial", "touchpoint": "backend/execution/terminal/"},
  {"id": "git_tools", "label": "Git tools", "status": "partial", "touchpoint": "backend/execution/git/"},
  {"id": "test_runner", "label": "Test/build runner tools", "status": "partial", "touchpoint": "backend/agentic/tools/execution_tools.py"},
  {"id": "mcp_host", "label": "MCP host", "status": "missing", "touchpoint": "backend/execution/mcp/"},
  {"id": "skills_rules", "label": "Skills + rules injection", "status": "partial", "touchpoint": "backend/skills/, agents_md.py"},
  {"id": "human_approval", "label": "Human approval for high-risk actions", "status": "partial", "touchpoint": "backend/agents/requirement_confirmation/"},
  {"id": "episodic_memory", "label": "Episodic memory (Postgres)", "status": "done", "touchpoint": "backend/agents/memory/episodic.py"},
  {"id": "run_replay", "label": "Run replay + checkpoint resume", "status": "partial", "touchpoint": "backend/agents/graph_runtime/checkpointer.py"},
  {"id": "multi_client", "label": "Multi-client harness (web/cli/ide)", "status": "partial", "touchpoint": "backend/api/v1/runs.py"},
)


def platform_parity_status() -> list[dict[str, Any]]:
  return [dict(item) for item in PLATFORM_PARITY_ITEMS]


def platform_capabilities_payload() -> dict[str, Any]:
  try:
    from ..agents.runtime_config import (
      episodic_hybrid_retrieval_enabled,
      episodic_vector_search_enabled,
      langgraph_runtime_default,
      legacy_episodic_read_enabled,
      parallel_file_workers_enabled,
      parallel_stream_orchestrator_enabled,
      parallel_update_llm_analysis_enabled,
      parallel_update_llm_timeout_seconds,
      parallel_update_preflight_enabled,
      parallel_worker_timeout_seconds,
      patch_approval_enabled,
      platform_failed_run_learning_enabled,
      platform_pattern_min_source_count,
      post_update_build_gate_enabled,
      post_update_visual_qa_enabled,
      qdrant_episode_search_enabled,
      runtime_parallel_actions_enabled,
      streaming_fast_path_enabled,
      streaming_path_parity_enabled,
      use_v1_runs_stream,
    )
  except ImportError:
    from agents.runtime_config import (
      episodic_hybrid_retrieval_enabled,
      episodic_vector_search_enabled,
      langgraph_runtime_default,
      legacy_episodic_read_enabled,
      parallel_file_workers_enabled,
      parallel_stream_orchestrator_enabled,
      parallel_update_llm_analysis_enabled,
      parallel_update_llm_timeout_seconds,
      parallel_update_preflight_enabled,
      parallel_worker_timeout_seconds,
      patch_approval_enabled,
      platform_failed_run_learning_enabled,
      platform_pattern_min_source_count,
      post_update_build_gate_enabled,
      post_update_visual_qa_enabled,
      qdrant_episode_search_enabled,
      runtime_parallel_actions_enabled,
      streaming_fast_path_enabled,
      streaming_path_parity_enabled,
      use_v1_runs_stream,
    )

  parity = platform_parity_status()
  done = sum(1 for item in parity if item.get("status") == "done")
  partial = sum(1 for item in parity if item.get("status") == "partial")
  v1_stream = use_v1_runs_stream()
  return {
    "schema": "worktual.platform-capabilities.v1",
    "product": "worktual_codex",
    "strategy": "web_first",
    "current_phase": current_platform_phase(),
    "phases": [dict(phase) for phase in PLATFORM_PHASES],
    "parity": parity,
    "summary": {
      "done": done,
      "partial": partial,
      "missing": len(parity) - done - partial,
      "total": len(parity),
    },
    "architecture": {
      "layers": ["context", "agent_core", "tool_executor", "validation_gates", "persistence"],
      "orchestration": "hierarchical_supervisor",
      "source_of_truth": "backend/agents/agent_runtime_loop.py",
      "event_schema": "worktual.run-event.v1",
    },
    "stream": {
      "legacy_endpoint": "/api/projects/{project_id}/generate-stream",
      "v1_endpoint": "/api/v1/runs/stream",
      "v1_cancel_endpoint": "/api/v1/runs/cancel",
      "use_v1_runs_stream": v1_stream,
      "web_client_env": "VITE_USE_V1_RUNS_STREAM",
    },
    "runtime": {
      "default_engine": "langgraph" if langgraph_runtime_default() else "streaming",
      "langgraph_default": langgraph_runtime_default(),
      "streaming_fast_path": streaming_fast_path_enabled(),
      "patch_approval": patch_approval_enabled(),
      "user_preferences_api": "/api/users/me/memory/preferences",
      "episodes_api": "/api/users/me/memory/episodes",
      "platform_memory_patterns_api": "/api/v1/platform/memory/patterns",
      "platform_pattern_min_source_count": platform_pattern_min_source_count(),
      "platform_failed_run_learning": platform_failed_run_learning_enabled(),
      "episodic_hybrid_retrieval": episodic_hybrid_retrieval_enabled(),
      "episodic_vector_search": episodic_vector_search_enabled(),
      "qdrant_episode_search": qdrant_episode_search_enabled(),
      "legacy_episodic_read": legacy_episodic_read_enabled(),
      "migrate_legacy_episodes_api": "/api/v1/platform/memory/migrate-legacy-episodes",
      "runtime_parallel_actions": runtime_parallel_actions_enabled(),
      "parallel_stream_orchestrator": parallel_stream_orchestrator_enabled(),
      "parallel_file_workers": parallel_file_workers_enabled(),
      "parallel_update_preflight": parallel_update_preflight_enabled(),
      "parallel_update_llm_analysis": parallel_update_llm_analysis_enabled(),
      "parallel_update_llm_timeout_seconds": parallel_update_llm_timeout_seconds(),
      "streaming_path_parity": streaming_path_parity_enabled(),
      "post_update_build_gate": post_update_build_gate_enabled(),
      "post_update_visual_qa": post_update_visual_qa_enabled(),
      "parallel_worker_timeout_seconds": parallel_worker_timeout_seconds(),
    },
  }
