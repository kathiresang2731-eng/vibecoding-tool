from backend.agents.memory.episodic import (
  EPISODIC_KIND,
  EPISODIC_NAMESPACE,
  build_episodic_context_block,
  build_episodic_run_key,
  filter_episodic_memories,
  list_episodic_memories,
  rank_episodic_memories,
  score_episodic_relevance,
  select_episodic_memories_for_prompt,
  should_write_episodic_episode,
  summarize_episodic_run,
)
from backend.storage import UserContext

import os
from unittest.mock import patch


class _MemoryStore:
  def __init__(self):
    self.items: list[dict] = []
    self.episodes: list[dict] = []

  def upsert_memory_item(self, user, *, project_id, namespace, key, kind, content, metadata=None):
    row = {
      "id": f"mem-{len(self.items) + 1}",
      "project_id": project_id,
      "namespace": namespace,
      "key": key,
      "kind": kind,
      "content": content,
      "metadata_json": metadata or {},
      "updated_at": metadata.get("recorded_at") if metadata else "",
    }
    self.items = [
      item
      for item in self.items
      if not (item["key"] == key and item["namespace"] == namespace and item["project_id"] == project_id)
    ]
    self.items.append(row)
    return row

  def list_memory_items(self, user, *, project_id=None, namespace=None, kind=None, limit=12):
    rows = [
      item
      for item in self.items
      if item.get("namespace") == namespace and item.get("project_id") == project_id
    ]
    if kind:
      rows = [item for item in rows if item.get("kind") == kind]
    rows.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
    return rows[:limit]

  def prune_memory_items(self, user, *, project_id, namespace, kind, keep):
    rows = [
      item
      for item in self.items
      if item.get("project_id") == project_id and item.get("namespace") == namespace and item.get("kind") == kind
    ]
    rows.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
    keep_ids = {item["id"] for item in rows[:keep]}
    before = len(self.items)
    self.items = [
      item
      for item in self.items
      if not (
        item.get("project_id") == project_id
        and item.get("namespace") == namespace
        and item.get("kind") == kind
        and item["id"] not in keep_ids
      )
    ]
    return before - len(self.items)

  def insert_memory_episode(self, user, **kwargs):
    row = {
      "id": f"ep-{len(self.episodes) + 1}",
      "updated_at": "2026-06-27T00:00:00Z",
      "created_at": "2026-06-27T00:00:00Z",
      **kwargs,
    }
    self.episodes.append(row)
    return row

  def list_memory_episodes(self, user, *, project_id=None, chat_session_id=None, scope=None, limit=12):
    rows = list(self.episodes)
    if project_id:
      rows = [row for row in rows if row.get("project_id") == project_id]
    if chat_session_id:
      rows = [row for row in rows if row.get("chat_session_id") == chat_session_id]
    if scope:
      rows = [row for row in rows if row.get("scope") == scope]
    return rows[:limit]


def _insert_test_episode(
  store: _MemoryStore,
  user: UserContext,
  *,
  project_id: str,
  chat_session_id: str,
  intent: str,
  prompt: str,
  outcome: str = "completed",
  run_id: str | None = None,
) -> dict:
  content = summarize_episodic_run(
    intent=intent,
    prompt=prompt,
    outcome=outcome,
    changed_paths=[],
  )
  return store.insert_memory_episode(
    user,
    project_id=project_id,
    chat_session_id=chat_session_id,
    generation_run_id=run_id,
    scope="personal",
    memory_type="update_checkpoint",
    title=f"{intent} run",
    searchable_summary=content,
    outcome=outcome,
    metadata={
      "intent": intent,
      "outcome": outcome,
      "run_id": run_id,
      "chat_session_id": chat_session_id,
      "source": "memory_episodes",
    },
  )


def test_summarize_episodic_run_includes_intent_and_paths():
  summary = summarize_episodic_run(
    intent="website_generation",
    prompt="Build a CRM website",
    outcome="completed",
    file_count=3,
    changed_paths=["src/App.jsx"],
    preview_status="ready",
  )
  assert "website_generation" in summary
  assert "src/App.jsx" in summary
  assert "ready" in summary


def test_persist_and_list_episodic_memories():
  store = _MemoryStore()
  user = UserContext(id="user-1", email="u@example.com", role="user")
  _insert_test_episode(
    store,
    user,
    project_id="project-1",
    chat_session_id="session-1",
    intent="website_generation",
    prompt="Build a farm website",
    run_id="run-1",
  )
  memories = list_episodic_memories(store, user, project_id="project-1", chat_session_id="session-1")
  assert len(memories) == 1
  assert memories[0]["kind"] == EPISODIC_KIND
  block = build_episodic_context_block(memories, prompt="farm website")
  assert "farm website" in block
  assert "episodic" in block


def test_filter_episodic_memories_is_strict_session_only():
  memories = [
    {"metadata_json": {"chat_session_id": "session-a", "intent": "a"}},
    {"metadata_json": {"intent": "project-wide"}},
    {"metadata_json": {"chat_session_id": "session-b", "intent": "other-session"}},
  ]
  filtered = filter_episodic_memories(memories, chat_session_id="session-a")
  assert len(filtered) == 1
  assert filtered[0]["metadata_json"]["intent"] == "a"
  assert filter_episodic_memories(memories, chat_session_id=None) == []
  assert filter_episodic_memories(memories, chat_session_id="session-missing") == []


def test_rank_episodic_memories_scores_prompt_overlap():
  memories = [
    {"content": "Intent: website_update\nUser request: change hero copy", "metadata_json": {"intent": "website_update"}},
    {"content": "Intent: greeting\nUser request: hello there", "metadata_json": {"intent": "greeting"}},
  ]
  ranked = rank_episodic_memories(memories, prompt="update the hero section")
  assert score_episodic_relevance(memories[0], "update the hero section") > score_episodic_relevance(
    memories[1], "update the hero section"
  )
  assert ranked[0]["metadata_json"]["intent"] == "website_update"


def test_select_episodic_memories_for_prompt_returns_session_scoped_results():
  store = _MemoryStore()
  user = UserContext(id="user-1", email="u@example.com", role="user")
  _insert_test_episode(
    store,
    user,
    project_id="project-1",
    chat_session_id="session-1",
    intent="website_update",
    prompt="Update navbar spacing",
    run_id="run-1",
  )
  _insert_test_episode(
    store,
    user,
    project_id="project-1",
    chat_session_id="session-2",
    intent="website_generation",
    prompt="Build landing page",
    run_id="run-2",
  )
  selected = select_episodic_memories_for_prompt(
    store,
    user,
    project_id="project-1",
    prompt="fix navbar spacing",
    chat_session_id="session-1",
  )
  assert len(selected) == 1
  assert selected[0]["metadata_json"]["intent"] == "website_update"


def test_list_episodic_requires_chat_session_id():
  store = _MemoryStore()
  user = UserContext(id="user-1", email="u@example.com", role="user")
  assert list_episodic_memories(store, user, project_id="project-1") == []


def test_list_episodic_prefers_structured_episodes():
  from backend.agents.memory.episodic import episode_to_memory_row, list_episodic_memories

  class _Store:
    def list_memory_episodes(self, user, *, project_id, chat_session_id, scope, limit):
      return [
        {
          "id": "ep-1",
          "chat_session_id": chat_session_id,
          "searchable_summary": "Intent: website_update\nUser request: fix navbar",
          "outcome": "completed",
          "memory_type": "update_checkpoint",
          "metadata_json": {"intent": "website_update", "chat_session_id": chat_session_id},
          "created_at": "2026-06-27T00:00:00Z",
        }
      ]

    def list_memory_items(self, *args, **kwargs):
      raise AssertionError("legacy memory_items should not be read when episodes exist")

  store = _Store()
  user = UserContext(id="user-1", email="u@example.com", role="user")
  rows = list_episodic_memories(store, user, project_id="p1", chat_session_id="session-1")
  assert len(rows) == 1
  assert rows[0]["metadata_json"]["source"] == "memory_episodes"
  adapted = episode_to_memory_row(rows[0])
  assert "fix navbar" in adapted.get("content", "") or "fix navbar" in rows[0].get("content", "")


def test_build_episodic_run_key_scopes_by_session():
  key = build_episodic_run_key(run_id="run-1", intent="website_update", chat_session_id="session-a")
  assert key.startswith("session-a-")


def test_legacy_fallback_reads_memory_items_when_legacy_read_enabled():
  store = _MemoryStore()
  user = UserContext(id="user-1", email="u@example.com", role="user")
  store.upsert_memory_item(
    user,
    project_id="project-1",
    namespace=EPISODIC_NAMESPACE,
    key=build_episodic_run_key(run_id="run-1", intent="website_update", chat_session_id="session-1"),
    kind=EPISODIC_KIND,
    content="Intent: website_update\nUser request: fix navbar",
    metadata={"intent": "website_update", "chat_session_id": "session-1", "recorded_at": "2026-06-27T00:00:00Z"},
  )
  with patch.dict(os.environ, {"ENABLE_LEGACY_EPISODIC_READ": "true"}, clear=False):
    rows = list_episodic_memories(store, user, project_id="project-1", chat_session_id="session-1")
  assert len(rows) == 1
  assert rows[0]["metadata_json"]["intent"] == "website_update"


def test_should_write_episodic_episode_skips_greeting_and_keeps_failed_updates():
  assert should_write_episodic_episode(intent="greeting", outcome="completed") is False
  assert should_write_episodic_episode(intent="project_info", outcome="completed") is False
  assert should_write_episodic_episode(
    intent="website_update",
    outcome="failed",
    error_category="syntax_error",
  ) is True
  assert should_write_episodic_episode(
    intent="website_update",
    outcome="completed",
    changed_paths=["src/App.jsx"],
  ) is True
