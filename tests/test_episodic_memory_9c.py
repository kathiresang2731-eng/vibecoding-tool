import os
from unittest.mock import patch

from backend.agents.memory.episodic import list_episodic_memories
from backend.agents.memory.legacy_episodic import migrate_legacy_episodic_items_to_episodes
from backend.agents.runtime_config import episodic_hybrid_retrieval_enabled, legacy_episodic_read_enabled
from backend.storage import UserContext


class _LegacyStore:
  def __init__(self):
    self.items: list[dict] = []
    self.episodes: list[dict] = []

  def list_memory_items(self, user, *, project_id=None, namespace=None, kind=None, limit=12):
    rows = [
      item
      for item in self.items
      if item.get("namespace") == namespace and item.get("project_id") == project_id and item.get("kind") == kind
    ]
    return rows[:limit]

  def list_memory_episodes(self, user, *, project_id=None, chat_session_id=None, scope=None, limit=12):
    return []

  def insert_memory_episode(self, user, **kwargs):
    row = {"id": f"ep-{len(self.episodes) + 1}", **kwargs}
    self.episodes.append(row)
    return row

  def find_memory_episode_by_run_id(self, user, *, project_id, chat_session_id, generation_run_id):
    for row in self.episodes:
      if row.get("generation_run_id") == generation_run_id:
        return row
    return None


def test_legacy_episodic_read_disabled_by_default():
  with patch.dict(os.environ, {}, clear=False):
    os.environ.pop("ENABLE_LEGACY_EPISODIC_READ", None)
    assert legacy_episodic_read_enabled() is False


def test_list_episodic_memories_skips_legacy_without_structured_rows_by_default():
  store = _LegacyStore()
  user = UserContext(id="user-1", email="u@example.com", role="user")
  store.items.append(
    {
      "project_id": "project-1",
      "namespace": "project",
      "kind": "episodic",
      "content": "Intent: website_update\nUser request: fix navbar",
      "metadata_json": {"intent": "website_update", "chat_session_id": "session-1"},
    }
  )
  with patch.dict(os.environ, {"ENABLE_LEGACY_EPISODIC_READ": "false"}, clear=False):
    rows = list_episodic_memories(store, user, project_id="project-1", chat_session_id="session-1")
  assert rows == []


def test_migrate_legacy_episodic_items_to_episodes():
  store = _LegacyStore()
  user = UserContext(id="user-1", email="u@example.com", role="user")
  store.items.append(
    {
      "project_id": "project-1",
      "namespace": "project",
      "kind": "episodic",
      "key": "session-1-run-legacy",
      "content": "Intent: website_update\nUser request: fix navbar",
      "metadata_json": {
        "intent": "website_update",
        "chat_session_id": "session-1",
        "run_id": "run-legacy",
        "changed_paths": ["src/App.jsx"],
      },
    }
  )
  result = migrate_legacy_episodic_items_to_episodes(
    store,
    user,
    project_id="project-1",
    chat_session_id="session-1",
  )
  assert result["status"] == "completed"
  assert result["migrated"] == 1
  assert len(store.episodes) == 1
  assert store.episodes[0]["metadata"]["source"] == "legacy_memory_items_migration"


def test_episodic_hybrid_retrieval_enabled_by_default():
  with patch.dict(os.environ, {}, clear=False):
    os.environ.pop("ENABLE_EPISODIC_HYBRID_RETRIEVAL", None)
    assert episodic_hybrid_retrieval_enabled() is True
