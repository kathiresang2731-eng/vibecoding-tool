from backend.app_platform.parity import platform_capabilities_payload


def test_v1_platform_capabilities_endpoint_payload():
  payload = platform_capabilities_payload()
  assert payload["schema"] == "worktual.platform-capabilities.v1"
  assert "parity" in payload
  assert "phases" in payload
  assert "stream" in payload
  assert payload["stream"]["v1_endpoint"] == "/api/v1/runs/stream"
  assert payload["stream"]["v1_cancel_endpoint"] == "/api/v1/runs/cancel"
  assert "use_v1_runs_stream" in payload["stream"]
  assert "runtime" in payload
  assert payload["runtime"]["default_engine"] in {"langgraph", "streaming"}
  assert "langgraph_default" in payload["runtime"]
  assert "streaming_fast_path" in payload["runtime"]
  assert "patch_approval" in payload["runtime"]
  assert payload["runtime"]["user_preferences_api"] == "/api/users/me/memory/preferences"
  assert payload["runtime"]["episodes_api"] == "/api/users/me/memory/episodes"
  assert payload["runtime"]["platform_memory_patterns_api"] == "/api/v1/platform/memory/patterns"
  assert payload["runtime"]["platform_pattern_min_source_count"] >= 1
  assert payload["runtime"]["platform_failed_run_learning"] is True or payload["runtime"]["platform_failed_run_learning"] is False
  assert payload["runtime"]["episodic_hybrid_retrieval"] is True
  assert payload["runtime"]["legacy_episodic_read"] is False
  assert payload["runtime"]["migrate_legacy_episodes_api"] == "/api/v1/platform/memory/migrate-legacy-episodes"
