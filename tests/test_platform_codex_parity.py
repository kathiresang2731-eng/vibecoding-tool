from backend.execution.patch import PatchEngineError, apply_patches_to_files, apply_unified_patch
from backend.platform import (
  current_platform_phase,
  failure_repair_route,
  platform_capabilities_payload,
  policy_tier_for_tool,
)
from backend.agentic.tools.registry import codex_tool_registry, execute_codex_tool, platform_tool_registry
from backend.agentic.tools.definitions import ToolRuntimeContext
from backend.storage import UserContext
from types import SimpleNamespace

def test_platform_capabilities_payload_matches_skill_schema():
  payload = platform_capabilities_payload()
  assert payload["schema"] == "worktual.platform-capabilities.v1"
  assert payload["current_phase"]["id"] in {0, 1}
  assert payload["summary"]["total"] >= 10
  assert any(item["id"] == "live_runtime_trace" and item["status"] == "done" for item in payload["parity"])


def test_policy_tier_for_apply_patch_is_medium():
  assert policy_tier_for_tool("APPLY_PATCH").value == "medium"
  assert policy_tier_for_tool("GIT_COMMIT").value == "high"


def test_failure_repair_route_for_recitation_blocks_model_retry_loop():
  route = failure_repair_route(category="model_blocked", code="gemini_recitation_filter", raw_error="finishReason RECITATION")
  assert route["retry_model"] is True
  assert route["retry_tool"] is False


def test_failure_repair_route_for_clarification_returns_to_user():
  route = failure_repair_route(category="needs_user_input", code="update_needs_clarification", raw_error="needs clarification")
  assert route["action"] == "return_to_user"
  assert route["route_agent"] == "Conversation Agent"


def test_apply_unified_patch_updates_content():
  original = "alpha\nbeta\ngamma\n"
  diff = """--- a/src/App.jsx
+++ b/src/App.jsx
@@ -1,3 +1,3 @@
 alpha
-beta
+beta-updated
 gamma
"""
  updated = apply_unified_patch(path="src/App.jsx", original_content=original, unified_diff=diff)
  assert "beta-updated" in updated
  assert "beta\n" not in updated or "beta-updated" in updated


def test_apply_unified_patch_rejects_context_mismatch():
  try:
    apply_unified_patch(
      path="src/App.jsx",
      original_content="one\ntwo\n",
      unified_diff="@@ -1,2 +1,2 @@\n wrong\n-two\n+three\n",
    )
  except PatchEngineError:
    return
  raise AssertionError("Expected PatchEngineError")


def test_platform_tool_registry_includes_apply_patch():
  names = set(platform_tool_registry())
  assert {"READ_FILE", "READ_FILE_RANGE", "LIST_DIR", "GLOB_SEARCH", "SEARCH_CODEBASE", "APPLY_PATCH"}.issubset(names)
  assert "APPLY_PATCH" in codex_tool_registry()


class _FakeStore:
  def list_files(self, project_id, user):
    return [{"path": "src/App.jsx", "content": "alpha\nbeta\ngamma\n"}]


def test_apply_patch_tool_stages_files_without_committing():
  context = ToolRuntimeContext(store=_FakeStore(), settings=None)
  user = UserContext(id="user-1", email="u@example.com", role="user")
  diff = """@@ -1,3 +1,3 @@
 alpha
-beta
+beta-updated
 gamma
"""
  result = execute_codex_tool(
    "APPLY_PATCH",
    context,
    user,
    {
      "project_id": "project-1",
      "patches": [{"path": "src/App.jsx", "unified_diff": diff}],
    },
  )
  assert result["status"] == "staged"
  assert result["patch_set"]["diff_stats"]["paths"] == ["src/App.jsx"]
  assert "beta-updated" in result["files"][0]["content"]
