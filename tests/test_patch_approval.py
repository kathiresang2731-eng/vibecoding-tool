from types import SimpleNamespace

from backend.agents.patch_approval.gate import require_patch_approval_before_commit, snapshot_from_runtime_state
from backend.agents.patch_approval.presentation import patch_approval_conversation_response, public_patch_approval_brief
from backend.agents.runtime_config import patch_approval_enabled


class MemoryStoreStub:
  def __init__(self):
    self.items = []

  def list_memory_items(self, user, *, project_id, namespace, limit=5):
    return [
      item
      for item in self.items
      if item.get("project_id") == project_id and item.get("namespace") == namespace
    ][:limit]

  def upsert_memory_item(self, user, *, project_id, namespace, key, kind, content, metadata=None):
    payload = {
      "project_id": project_id,
      "namespace": namespace,
      "key": key,
      "kind": kind,
      "content": content,
      "metadata_json": metadata or {},
    }
    self.items = [item for item in self.items if not (item.get("project_id") == project_id and item.get("key") == key)]
    self.items.append(payload)
    return payload


def test_patch_approval_enabled_defaults_false(monkeypatch):
  monkeypatch.delenv("ENABLE_PATCH_APPROVAL", raising=False)
  monkeypatch.setenv("AGENTIC_PARITY_TARGET", "48")
  assert patch_approval_enabled() is False


def test_snapshot_from_runtime_state_collects_candidate_files():
  state = {
    "candidate_files": [{"path": "src/App.jsx", "content": "export default function App(){}"}],
    "changed_file_paths": ["src/App.jsx"],
    "code_diff_summary": {"file_count": 1, "added": 2, "removed": 1, "diffs": [{"path": "src/App.jsx", "diff": "@@"}]},
    "prompt": "Update hero copy",
    "operation": "update",
  }
  snapshot = snapshot_from_runtime_state(state)
  assert snapshot["paths"] == ["src/App.jsx"]
  assert snapshot["candidate_files"][0]["path"] == "src/App.jsx"
  assert snapshot["diff_detail"]["file_count"] == 1


def test_require_patch_approval_before_commit_persists_and_pauses(monkeypatch):
  monkeypatch.setenv("ENABLE_PATCH_APPROVAL", "true")
  store = MemoryStoreStub()
  tool_context = SimpleNamespace(store=store, settings=SimpleNamespace())
  user = SimpleNamespace(id="user-1")
  state = {
    "candidate_files": [{"path": "src/App.jsx", "content": "export default function App(){ return 1; }"}],
    "changed_file_paths": ["src/App.jsx"],
    "code_diff_summary": {"file_count": 1, "added": 1, "removed": 1},
    "prompt": "Tweak App",
  }
  events = []

  blocked = require_patch_approval_before_commit(
    state,
    tool_context=tool_context,
    user=user,
    project_id="project-1",
    progress=lambda step, message, **kwargs: events.append({"step": step, **kwargs}),
    patch_action=None,
  )

  assert blocked is True
  assert state["awaiting_patch_approval"] is True
  assert any(event["step"] == "patch.approval.required" for event in events)
  assert store.items


def test_patch_approval_conversation_response_shape():
  pending = {
    "status": "pending",
    "paths": ["src/App.jsx"],
    "diff_detail": {"file_count": 1, "added": 1, "removed": 0, "diffs": [{"path": "src/App.jsx", "diff": "@@"}]},
  }
  response = patch_approval_conversation_response(pending)
  assert response["type"] == "awaiting_patch_approval"
  assert response["patch_approval"]["status"] == "pending"
  assert public_patch_approval_brief(pending)["paths"] == ["src/App.jsx"]
