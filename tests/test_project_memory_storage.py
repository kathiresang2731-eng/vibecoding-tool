from __future__ import annotations

import hashlib
import os

import pytest

os.environ.setdefault("ENABLE_CODE_INDEX", "true")

from backend.agents.code_index.indexer import chunk_project_files
from backend.agents.code_index.retriever import retrieve_code_context
from backend.agents.code_index.store import get_project_chunks, set_project_chunks
from backend.agents.memory.session_monitor import build_file_manifest
from backend.agents.memory.session_monitor import persist_generation_memory_checkpoint
from backend.storage.projects import (
  _normalize_project_file_records,
  _persist_project_code_index_after_reindex,
  _refresh_project_ui_knowledge_after_persist,
  _run_project_post_write_consistency,
)
from backend.storage import UserContext


def test_storage_normalizes_paths_payloads_and_hashes() -> None:
  files = _normalize_project_file_records(
    [
      {"path": "./Crm-Project-worktual/src/App.jsx", "code": "export default function App() { return null; }"},
      {"path": "src\\pages\\Home.jsx", "content": "export default function Home() { return null; }"},
    ]
  )

  by_path = {item["path"]: item for item in files}
  assert set(by_path) == {"src/App.jsx", "src/pages/Home.jsx"}
  assert by_path["src/App.jsx"]["content"].startswith("export default")
  assert by_path["src/App.jsx"]["content_hash"] == hashlib.sha256(
    by_path["src/App.jsx"]["content"].encode("utf-8")
  ).hexdigest()


def test_storage_rejects_duplicate_normalized_paths() -> None:
  with pytest.raises(Exception, match="Duplicate project file path"):
    _normalize_project_file_records(
      [
        {"path": "./src/App.jsx", "content": "first"},
        {"path": "src/App.jsx", "content": "second"},
      ]
    )


def test_storage_rejects_non_string_content() -> None:
  with pytest.raises(Exception, match="content must be a string"):
    _normalize_project_file_records([{"path": "src/data.json", "content": {"unsafe": True}}])


def test_file_manifest_reports_total_even_when_paths_are_truncated() -> None:
  files = [{"path": f"src/pages/Page{i}.jsx", "content": ""} for i in range(45)]

  manifest = build_file_manifest(files, limit=40)

  assert manifest["total"] == 45
  assert len(manifest["paths"]) == 40
  assert manifest["truncated"] is True
  assert manifest["counts"]["src"] == 45


def test_retrieve_code_context_rebuilds_stale_warm_index() -> None:
  project_id = "stale-index-project"
  old_files = [{"path": "src/pages/Cart.jsx", "content": "export default function Cart() { return <button>Old cart</button>; }"}]
  new_content = "export default function Cart() { return <button>New checkout panel</button>; }"
  new_files = [{"path": "src/pages/Cart.jsx", "content": new_content}]

  set_project_chunks(project_id, chunk_project_files(old_files, project_id=project_id))
  matches = retrieve_code_context("new checkout panel", new_files, project_id=project_id, limit=3)

  assert matches
  assert matches[0]["path"] == "src/pages/Cart.jsx"
  assert any("New checkout panel" in chunk.get("content", "") for chunk in get_project_chunks(project_id))


class _UiKnowledgeStore:
  def __init__(self) -> None:
    self.memory_items: list[dict] = []

  def list_files(self, project_id, user):
    return [
      {
        "path": "src/pages/Home.jsx",
        "content": "export default function Home() { return <main><button>Launch Flow</button></main>; }",
      }
    ]

  def upsert_memory_item(self, user, **payload):
    row = {"id": "memory-1", **payload, "metadata_json": payload.get("metadata") or {}}
    self.memory_items = [row]
    return row


def test_storage_refreshes_project_ui_knowledge_after_file_persist() -> None:
  store = _UiKnowledgeStore()

  _refresh_project_ui_knowledge_after_persist(
    store,
    "project-1",
    type("User", (), {"id": "user-1"})(),
    chat_session_id="session-1",
    chat_topic_id="topic-1",
  )

  assert store.memory_items
  row = store.memory_items[0]
  assert row["namespace"] == "project_knowledge"
  assert row["metadata_json"]["record_count"] == 1
  assert row["metadata_json"]["chat_topic_id"] == "topic-1"


def test_post_write_consistency_queues_ui_refresh_instead_of_inline(monkeypatch) -> None:
  class Store:
    def __init__(self) -> None:
      self.jobs: list[dict] = []

    def list_files(self, project_id, user):
      return [
        {
          "path": "src/App.jsx",
          "content": "export default function App(){return <button>Launch</button>}",
        }
      ]

    def upsert_memory_item(self, user, **payload):
      raise AssertionError("UI knowledge refresh should be queued, not run inline")

    def enqueue_consistency_job(self, user, **payload):
      self.jobs.append(payload)
      return {"id": f"job-{len(self.jobs)}", **payload}

  monkeypatch.delenv("WORKTUAL_INLINE_PROJECT_UI_KNOWLEDGE_REFRESH", raising=False)
  monkeypatch.setattr("backend.storage.projects._reindex_project_files_after_persist", lambda *_args, **_kwargs: True)
  monkeypatch.setattr("backend.storage.projects._persist_project_code_index_after_reindex", lambda *_args, **_kwargs: True)

  store = Store()
  _run_project_post_write_consistency(
    store,
    "project-1",
    UserContext(id="user-1", email="u@example.com", role="editor"),
    [{"path": "src/App.jsx", "content": "export default function App(){return null;}"}],
    changed_paths=["src/App.jsx"],
    chat_session_id="session-1",
    chat_topic_id="topic-1",
  )

  assert [job["job_type"] for job in store.jobs] == ["project_ui_knowledge_refresh"]
  assert store.jobs[0]["payload"]["chat_topic_id"] == "topic-1"


class _TopicStateStore:
  def __init__(self) -> None:
    self.states: dict[tuple[str, str], dict] = {}
    self.snapshots: list[dict] = []
    self.episodes: list[dict] = []
    self.learning_events: list[dict] = []
    self.get_calls: list[dict] = []

  def get_memory_chat_session_state(self, user, *, chat_session_id, chat_topic_id=None):
    self.get_calls.append({"chat_session_id": chat_session_id, "chat_topic_id": chat_topic_id})
    return self.states.get((chat_session_id, chat_topic_id or ""))

  def upsert_memory_chat_session_state(self, user, *, chat_session_id, rolling_summary, chat_topic_id=None, **kwargs):
    key = (chat_session_id, chat_topic_id or "")
    prior = self.states.get(key) or {}
    row = {
      "chat_session_id": chat_session_id,
      "chat_topic_id": chat_topic_id,
      "rolling_summary": rolling_summary,
      "update_count": int(prior.get("update_count") or 0) + 1,
      **kwargs,
    }
    self.states[key] = row
    return row

  def insert_memory_session_snapshot(self, user, **kwargs):
    self.snapshots.append(kwargs)
    return {"id": f"snapshot-{len(self.snapshots)}", **kwargs}

  def insert_memory_episode(self, user, **kwargs):
    self.episodes.append(kwargs)
    return {"id": f"episode-{len(self.episodes)}", **kwargs}

  def record_memory_learning_event(self, user, **kwargs):
    self.learning_events.append(kwargs)
    return {"id": f"event-{len(self.learning_events)}", **kwargs}


def test_generation_memory_checkpoint_uses_topic_scoped_session_state() -> None:
  store = _TopicStateStore()
  user = UserContext(id="user-1", email="u@example.com", role="editor")

  persist_generation_memory_checkpoint(
    store,
    user,
    project_id="project-1",
    chat_session_id="session-1",
    chat_topic_id="topic-theme",
    generation_run_id="run-1",
    prompt="Update the theme colors",
    intent="website_update",
    outcome="completed",
    changed_paths=["src/pages/Home.jsx"],
  )
  persist_generation_memory_checkpoint(
    store,
    user,
    project_id="project-1",
    chat_session_id="session-1",
    chat_topic_id="topic-auth",
    generation_run_id="run-2",
    prompt="Fix the auth flow",
    intent="website_update",
    outcome="completed",
    changed_paths=["src/pages/Auth.jsx"],
  )

  assert store.states[("session-1", "topic-theme")]["update_count"] == 1
  assert store.states[("session-1", "topic-auth")]["update_count"] == 1
  assert store.get_calls[0]["chat_topic_id"] == "topic-theme"
  assert store.get_calls[1]["chat_topic_id"] == "topic-auth"


class _RecordingCursor:
  def __init__(self) -> None:
    self.calls: list[tuple[str, tuple | None]] = []

  def execute(self, query, params=None):
    self.calls.append((" ".join(str(query).split()), params))


class _CodeIndexPersistenceStore:
  def __init__(self) -> None:
    self.cursor = _RecordingCursor()

  def _run_project_file_transaction(self, operation):
    return operation(self.cursor)


def test_persistent_code_index_replaces_project_chunks() -> None:
  project_id = "persistent-project"
  files = [{"path": "src/App.jsx", "content": "export default function App() { return <main>Home</main>; }"}]
  chunks = chunk_project_files(files, project_id=project_id)
  set_project_chunks(project_id, [{**chunk, "embedding": [0.1, 0.2]} for chunk in chunks])
  store = _CodeIndexPersistenceStore()

  _persist_project_code_index_after_reindex(store, project_id, files, replace_all=True)

  queries = [query for query, _ in store.cursor.calls]
  assert queries[0].startswith("delete from project_code_index_chunks where project_id")
  assert any(query.startswith("insert into project_code_index_chunks") for query in queries)
