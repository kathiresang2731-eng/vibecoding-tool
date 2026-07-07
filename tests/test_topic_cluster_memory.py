from __future__ import annotations

from typing import Any

from backend.agents.memory.context import build_agent_flow_memory_block
from backend.agents.memory.episodic import select_episodic_memories_for_prompt
from backend.agents.memory.topic_clustering import (
  filter_chat_messages_for_topic,
  resolve_chat_topic,
  update_chat_topic_after_run,
)
from backend.storage import UserContext


class _TopicStore:
  def __init__(self) -> None:
    self.clock = 0
    self.topics: list[dict[str, Any]] = []
    self.messages: list[dict[str, Any]] = []
    self.episodes: list[dict[str, Any]] = []
    self.preferences: list[dict[str, Any]] = []

  def _next_time(self) -> str:
    self.clock += 1
    return f"2026-07-04T00:00:{self.clock:02d}Z"

  def create_memory_chat_topic(
    self,
    user,
    *,
    project_id,
    chat_session_id,
    label,
    intent_family,
    memory_scope="topic",
    topic_tags="",
    rolling_summary="",
    related_paths=None,
    related_modules=None,
    last_prompt="",
    last_changed_paths=None,
    status="active",
    confidence=0.0,
    metadata=None,
  ):
    row = {
      "id": f"topic-{len(self.topics) + 1}",
      "project_id": project_id,
      "user_id": user.id,
      "chat_session_id": chat_session_id,
      "label": label,
      "intent_family": intent_family,
      "memory_scope": memory_scope,
      "topic_tags": topic_tags,
      "rolling_summary": rolling_summary,
      "related_paths_json": list(related_paths or []),
      "related_modules_json": list(related_modules or []),
      "last_prompt": last_prompt,
      "last_changed_paths_json": list(last_changed_paths or []),
      "status": status,
      "confidence": confidence,
      "metadata_json": metadata or {},
      "updated_at": self._next_time(),
    }
    self.topics.append(row)
    return row

  def list_memory_chat_topics(self, user, *, project_id, chat_session_id, limit=16, status=None):
    rows = [
      topic
      for topic in self.topics
      if topic["project_id"] == project_id
      and topic["chat_session_id"] == chat_session_id
      and topic["user_id"] == user.id
      and (status is None or topic["status"] == status)
    ]
    rows.sort(key=lambda item: item["updated_at"], reverse=True)
    return rows[:limit]

  def get_memory_chat_topic(self, user, *, chat_topic_id):
    for topic in self.topics:
      if topic["id"] == chat_topic_id and topic["user_id"] == user.id:
        return topic
    return None

  def update_memory_chat_topic(self, user, *, chat_topic_id, **updates):
    topic = self.get_memory_chat_topic(user, chat_topic_id=chat_topic_id)
    if topic is None:
      return None
    key_map = {
      "related_paths": "related_paths_json",
      "related_modules": "related_modules_json",
      "last_changed_paths": "last_changed_paths_json",
      "metadata": "metadata_json",
    }
    for key, value in updates.items():
      target = key_map.get(key, key)
      if target in {"related_paths_json", "related_modules_json", "last_changed_paths_json"}:
        topic[target] = list(value or [])
      elif target == "metadata_json":
        topic[target] = value or {}
      elif value is not None:
        topic[target] = value
    topic["updated_at"] = self._next_time()
    return topic

  def list_project_chat_messages(
    self,
    project_id,
    user,
    *,
    limit=80,
    chat_session_id=None,
    chat_topic_id=None,
  ):
    rows = [
      message
      for message in self.messages
      if message.get("project_id") == project_id
      and message.get("chat_session_id") == chat_session_id
      and message.get("user_id") == user.id
    ]
    if chat_topic_id:
      rows = [message for message in rows if message.get("chat_topic_id") == chat_topic_id]
    return rows[-limit:]

  def list_memory_episodes(
    self,
    user,
    *,
    project_id=None,
    chat_session_id=None,
    chat_topic_id=None,
    scope=None,
    limit=12,
  ):
    rows = [
      episode
      for episode in self.episodes
      if episode.get("project_id") == project_id
      and episode.get("chat_session_id") == chat_session_id
      and (scope is None or episode.get("scope") == scope)
      and episode.get("user_id") == user.id
    ]
    if chat_topic_id:
      rows = [episode for episode in rows if episode.get("chat_topic_id") == chat_topic_id]
    return rows[:limit]

  def list_memory_preferences(self, user, *, limit=8):
    return self.preferences[:limit]


def _user() -> UserContext:
  return UserContext(id="user-1", email="user@example.com", role="user")


def _project_files() -> list[dict[str, str]]:
  return [
    {"path": "src/App.jsx"},
    {"path": "src/index.css"},
    {"path": "src/pages/Auth.jsx"},
    {"path": "src/pages/Onboarding.jsx"},
    {"path": "src/pages/Dashboard.jsx"},
    {"path": "src/pages/Deals.jsx"},
    {"path": "tailwind.config.js"},
  ]


class _TopicLLMProvider:
  def __init__(self, payload: dict[str, Any]) -> None:
    self.payload = payload
    self.calls: list[dict[str, Any]] = []

  def generate_json(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
    self.calls.append({"prompt": prompt, **kwargs})
    return self.payload


def test_topic_resolver_separates_unrelated_website_update_tasks() -> None:
  store = _TopicStore()
  user = _user()

  first = resolve_chat_topic(
    store=store,
    user=user,
    project_id="project-1",
    chat_session_id="session-1",
    prompt="change the website theme to red and black",
    project_files=_project_files(),
    adaptive_route={"route": "targeted_update"},
    routing_result={"intent": "website_update"},
  )
  second = resolve_chat_topic(
    store=store,
    user=user,
    project_id="project-1",
    chat_session_id="session-1",
    prompt="update the flow Auth -> onboarding -> dashboard after signin",
    project_files=_project_files(),
    adaptive_route={"route": "targeted_update"},
    routing_result={"intent": "website_update"},
  )

  assert first["topic_action"] == "new"
  assert second["topic_action"] == "new"
  assert first["chat_topic_id"] != second["chat_topic_id"]
  assert len(store.topics) == 2
  assert any("Auth.jsx" in path for path in second["related_paths"])
  assert any("Onboarding.jsx" in path for path in second["related_paths"])


def test_topic_resolver_uses_llm_assignment_for_non_keyword_continuation() -> None:
  store = _TopicStore()
  user = _user()
  store.create_memory_chat_topic(
    user,
    project_id="project-1",
    chat_session_id="session-1",
    label="Theme work",
    intent_family="website_update",
    topic_tags="visual polish",
    rolling_summary="User was changing visual branding.",
    related_paths=["src/index.css"],
  )
  flow_topic = store.create_memory_chat_topic(
    user,
    project_id="project-1",
    chat_session_id="session-1",
    label="Entry journey",
    intent_family="feature_update",
    topic_tags="entry journey",
    rolling_summary="User wants the entry journey fixed before reaching the workspace.",
    related_paths=["src/App.jsx", "src/pages/Auth.jsx", "src/pages/Onboarding.jsx"],
  )
  provider = _TopicLLMProvider(
    {
      "topic_action": "reuse",
      "chat_topic_id": flow_topic["id"],
      "label": "Entry journey",
      "intent_family": "feature_update",
      "memory_scope": "topic",
      "confidence": 0.91,
      "reason": "The request continues the prior entry-journey task, not the visual-branding task.",
      "related_paths": ["src/App.jsx", "src/pages/Auth.jsx", "src/pages/Onboarding.jsx"],
      "related_modules": ["Auth", "Onboarding"],
      "topic_tags": ["entry", "journey"],
    }
  )

  result = resolve_chat_topic(
    store=store,
    user=user,
    project_id="project-1",
    chat_session_id="session-1",
    prompt="carry forward that entry sequence correction",
    project_files=_project_files(),
    adaptive_route={"route": "targeted_update"},
    routing_result={"intent": "website_update"},
    llm_provider=provider,
  )

  assert provider.calls
  assert result["resolution_source"] == "llm"
  assert result["topic_action"] == "reuse"
  assert result["chat_topic_id"] == flow_topic["id"]
  assert result["intent_family"] == "feature_update"


def test_topic_resolver_reuses_active_topic_for_confirmation() -> None:
  store = _TopicStore()
  user = _user()
  resolve_chat_topic(
    store=store,
    user=user,
    project_id="project-1",
    chat_session_id="session-1",
    prompt="change the website theme to red and black",
    project_files=_project_files(),
    adaptive_route={"route": "targeted_update"},
    routing_result={"intent": "website_update"},
  )
  flow = resolve_chat_topic(
    store=store,
    user=user,
    project_id="project-1",
    chat_session_id="session-1",
    prompt="update the flow Auth -> onboarding -> dashboard after signin",
    project_files=_project_files(),
    adaptive_route={"route": "targeted_update"},
    routing_result={"intent": "website_update"},
  )

  confirmation = resolve_chat_topic(
    store=store,
    user=user,
    project_id="project-1",
    chat_session_id="session-1",
    prompt="yes",
    project_files=_project_files(),
    adaptive_route={"route": "targeted_update"},
    routing_result={"intent": "website_update"},
  )

  assert confirmation["topic_action"] == "reuse"
  assert confirmation["chat_topic_id"] == flow["chat_topic_id"]


def test_simple_code_request_starts_new_topic_without_website_memory() -> None:
  store = _TopicStore()
  user = _user()
  website = resolve_chat_topic(
    store=store,
    user=user,
    project_id="project-1",
    chat_session_id="session-1",
    prompt="update website dashboard cards",
    project_files=_project_files(),
    adaptive_route={"route": "targeted_update"},
    routing_result={"intent": "website_update"},
  )

  simple_code = resolve_chat_topic(
    store=store,
    user=user,
    project_id="project-1",
    chat_session_id="session-1",
    prompt="write a simple python program to add two numbers",
    project_files=_project_files(),
    adaptive_route={"route": "small_code"},
    routing_result={"intent": "simple_code"},
  )

  assert simple_code["topic_action"] == "new"
  assert simple_code["intent_family"] == "simple_code"
  assert simple_code["chat_topic_id"] != website["chat_topic_id"]


def test_chat_continuity_filters_messages_to_selected_topic() -> None:
  messages = [
    {
      "role": "user",
      "content": "change the website theme to red and black",
      "metadata_json": {"chat_topic_id": "topic-theme"},
    },
    {
      "role": "user",
      "content": "update the flow Auth -> onboarding -> dashboard",
      "metadata_json": {"chat_topic_id": "topic-flow"},
    },
  ]

  filtered = filter_chat_messages_for_topic(messages, chat_topic_id="topic-flow", prompt="continue that")

  assert len(filtered) == 1
  assert "Auth" in filtered[0]["content"]


def test_agent_flow_memory_injects_same_topic_history_only() -> None:
  store = _TopicStore()
  user = _user()
  theme_topic = store.create_memory_chat_topic(
    user,
    project_id="project-1",
    chat_session_id="session-1",
    label="Theme update",
    intent_family="website_update",
    topic_tags="theme red black",
    rolling_summary="Theme request: red and black palette.",
  )
  flow_topic = store.create_memory_chat_topic(
    user,
    project_id="project-1",
    chat_session_id="session-1",
    label="Auth onboarding flow",
    intent_family="website_update",
    topic_tags="auth onboarding dashboard",
    rolling_summary="Flow request: Auth must lead to onboarding then dashboard.",
  )
  store.messages.extend(
    [
      {
        "project_id": "project-1",
        "user_id": user.id,
        "chat_session_id": "session-1",
        "chat_topic_id": theme_topic["id"],
        "role": "user",
        "content": "change the website theme to red and black",
      },
      {
        "project_id": "project-1",
        "user_id": user.id,
        "chat_session_id": "session-1",
        "chat_topic_id": flow_topic["id"],
        "role": "user",
        "content": "update the flow Auth -> onboarding -> dashboard",
      },
    ]
  )

  block = build_agent_flow_memory_block(
    store,
    user,
    project_id="project-1",
    prompt="continue that update",
    chat_session_id="session-1",
    chat_topic_id=flow_topic["id"],
  )

  assert "Auth must lead to onboarding then dashboard" in block
  assert "red and black palette" not in block
  assert "change the website theme to red and black" not in block


def test_episodic_memory_retrieval_filters_by_chat_topic_id() -> None:
  store = _TopicStore()
  user = _user()
  store.episodes.extend(
    [
      {
        "id": "ep-theme",
        "project_id": "project-1",
        "user_id": user.id,
        "chat_session_id": "session-1",
        "chat_topic_id": "topic-theme",
        "scope": "personal",
        "memory_type": "update_checkpoint",
        "searchable_summary": "Theme request changed red and black colors",
        "outcome": "completed",
        "metadata_json": {
          "intent": "website_update",
          "chat_session_id": "session-1",
          "chat_topic_id": "topic-theme",
        },
      },
      {
        "id": "ep-flow",
        "project_id": "project-1",
        "user_id": user.id,
        "chat_session_id": "session-1",
        "chat_topic_id": "topic-flow",
        "scope": "personal",
        "memory_type": "update_checkpoint",
        "searchable_summary": "Flow request changed Auth to onboarding to dashboard",
        "outcome": "completed",
        "metadata_json": {
          "intent": "website_update",
          "chat_session_id": "session-1",
          "chat_topic_id": "topic-flow",
        },
      },
    ]
  )

  selected = select_episodic_memories_for_prompt(
    store,
    user,
    project_id="project-1",
    prompt="continue auth onboarding dashboard update",
    chat_session_id="session-1",
    chat_topic_id="topic-flow",
  )

  assert len(selected) == 1
  assert selected[0]["metadata_json"]["chat_topic_id"] == "topic-flow"
  assert "Auth to onboarding" in selected[0]["content"]


def test_topic_summary_updates_after_run_with_changed_paths() -> None:
  store = _TopicStore()
  user = _user()
  topic = store.create_memory_chat_topic(
    user,
    project_id="project-1",
    chat_session_id="session-1",
    label="Auth onboarding flow",
    intent_family="website_update",
    rolling_summary="Initial flow task.",
  )

  updated = update_chat_topic_after_run(
    store=store,
    user=user,
    chat_topic_id=topic["id"],
    prompt="update Auth -> onboarding -> dashboard",
    outcome="completed",
    changed_paths=["src/App.jsx", "src/pages/Auth.jsx"],
    metadata={"run_id": "run-1"},
  )

  assert updated is not None
  assert "Latest request (completed)" in updated["rolling_summary"]
  assert updated["last_changed_paths_json"] == ["src/App.jsx", "src/pages/Auth.jsx"]
  assert updated["metadata_json"]["run_id"] == "run-1"
