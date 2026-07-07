from __future__ import annotations

from types import SimpleNamespace

from backend.api.generation_parts.preflight import prepare_generation_pipeline_inputs
from backend.storage import UserContext


class _ReferentialStore:
  def __init__(self) -> None:
    self.topic = {
      "id": "topic-apj",
      "project_id": "project-1",
      "chat_session_id": "session-1",
      "user_id": "user-1",
      "label": "APJ Abdul Kalam history",
      "intent_family": "read_only",
      "memory_scope": "topic",
      "confidence": 0.9,
      "topic_tags": "apj abdul kalam history biography",
      "rolling_summary": "Current topic is about A.P.J. Abdul Kalam and the user is asking for historical details.",
      "related_paths_json": [],
      "related_modules_json": [],
      "last_changed_paths_json": [],
      "updated_at": "2026-07-06T12:00:00Z",
      "last_prompt": "i want to know history of APJ kalam",
      "metadata_json": {"last_resolution_reason": "same-topic referential follow-up"},
    }
    self.messages = [
      {
        "role": "user",
        "content": "i want to know history of APJ kalam",
        "chat_topic_id": "topic-apj",
        "metadata_json": {"chat_topic_id": "topic-apj"},
      },
      {
        "role": "model",
        "content": "Dr. A.P.J. Abdul Kalam was an Indian aerospace scientist and the 11th President of India.",
        "chat_topic_id": "topic-apj",
        "metadata_json": {"chat_topic_id": "topic-apj"},
      },
      {
        "role": "user",
        "content": "i want more detailed information about him",
        "chat_topic_id": "topic-apj",
        "metadata_json": {"chat_topic_id": "topic-apj"},
      },
    ]

  def list_files(self, project_id, user):
    return []

  def list_memory_chat_topics(self, user, *, project_id, chat_session_id, limit=16, status="active"):
    return [self.topic]

  def create_memory_chat_topic(self, user, **kwargs):
    self.topic = {**self.topic, **kwargs}
    return self.topic

  def update_memory_chat_topic(self, user, *, chat_topic_id, **updates):
    assert chat_topic_id == self.topic["id"]
    self.topic = {**self.topic, **updates}
    return self.topic

  def list_project_chat_messages(self, project_id, user, *, limit=120, chat_session_id=None, chat_topic_id=None):
    rows = list(self.messages)
    if chat_topic_id:
      rows = [row for row in rows if row.get("chat_topic_id") == chat_topic_id]
    return rows[:limit]

  def get_memory_chat_topic(self, user, *, chat_topic_id):
    return self.topic if chat_topic_id == self.topic["id"] else None

  def get_memory_chat_session_state(self, user, *, project_id=None, chat_session_id=None, chat_topic_id=None):
    return {
      "chat_session_id": chat_session_id,
      "project_id": project_id,
      "user_id": user.id,
      "rolling_summary": "Topic continuity for APJ Abdul Kalam.",
      "last_changed_paths_json": [],
      "update_count": 2,
    }

  def list_memory_preferences(self, user, *, limit=50):
    return []

  def list_memory_platform_patterns(self, **kwargs):
    return []

  def list_memory_learning_events(self, user, **kwargs):
    return []

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
    return [
      {
        "id": "episode-apj",
        "project_id": project_id,
        "chat_session_id": chat_session_id,
        "chat_topic_id": chat_topic_id,
        "scope": "personal",
        "title": "APJ Abdul Kalam history",
        "searchable_summary": "A.P.J. Abdul Kalam was an aerospace scientist, author, and former President of India.",
        "metadata_json": {"intent": "general_query", "chat_topic_id": chat_topic_id},
      }
    ]


def test_preflight_enriches_referential_pdf_followup_with_same_topic_context() -> None:
  store = _ReferentialStore()
  context = SimpleNamespace(store=store, settings=SimpleNamespace())
  user = UserContext(id="user-1", email="user@example.com", role="editor")

  preflight = prepare_generation_pipeline_inputs(
    context=context,
    project_id="project-1",
    prompt="give me this detailed as pdf",
    user=user,
    project={},
    normalized_attachments=[],
    resolved_chat_session_id="session-1",
    request_class=None,
    estimated_credit_reservation=0,
    model="gemini-test",
    artifact_model="gemini-test",
    model_policy="default",
    progress_callback=None,
    telemetry=None,
    system_name=None,
    confirmation_action=None,
    topic_llm_provider=None,
  )

  assert preflight["chat_topic_id"] == "topic-apj"
  assert "A.P.J. Abdul Kalam" in preflight["prompt_for_agents"]
  assert "resolve referential phrases" in preflight["prompt_for_agents"]
  assert "give me this detailed as pdf" in preflight["effective_prompt"]


def test_preflight_keeps_simple_greeting_minimal_even_with_project_files() -> None:
  class _GreetingStore:
    def list_files(self, project_id, user):
      return [{"path": "src/App.jsx", "content": "export default function App() { return null; }"}]

    def list_memory_chat_topics(self, user, *, project_id, chat_session_id, limit=16, status="active"):
      return []

    def create_memory_chat_topic(self, user, **kwargs):
      return kwargs

    def update_memory_chat_topic(self, user, *, chat_topic_id, **updates):
      return {"id": chat_topic_id, **updates}

    def list_project_chat_messages(self, project_id, user, *, limit=120, chat_session_id=None, chat_topic_id=None):
      return [
        {"role": "user", "content": "previous website update", "metadata_json": {}},
        {"role": "model", "content": "previous response", "metadata_json": {}},
      ]

    def get_memory_chat_session_state(self, user, *, project_id=None, chat_session_id=None, chat_topic_id=None):
      return {}

    def list_memory_preferences(self, user, *, limit=50):
      return []

    def list_memory_platform_patterns(self, **kwargs):
      return []

    def list_memory_learning_events(self, user, **kwargs):
      return []

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
      return []

  store = _GreetingStore()
  context = SimpleNamespace(store=store, settings=SimpleNamespace())
  user = UserContext(id="user-1", email="user@example.com", role="editor")

  preflight = prepare_generation_pipeline_inputs(
    context=context,
    project_id="project-1",
    prompt="hi",
    user=user,
    project={},
    normalized_attachments=[],
    resolved_chat_session_id="session-1",
    request_class=None,
    estimated_credit_reservation=0,
    model="gemini-test",
    artifact_model="gemini-test",
    model_policy="default",
    progress_callback=None,
    telemetry=None,
    system_name=None,
    confirmation_action=None,
    topic_llm_provider=None,
  )

  assert preflight["adaptive_route"]["route"] == "tiny_chat"
  assert preflight["tiny_chat_fast_context"] is True
  assert preflight["raw_chat_history"] == []
  assert preflight["agents_md_block"] == ""
  assert preflight["memory_context"] == ""
  assert preflight["effective_prompt"] == "hi"


def test_preflight_keeps_project_info_prompt_clean_while_preserving_project_context() -> None:
  class _ProjectInfoStore:
    def list_files(self, project_id, user):
      return [
        {"path": "src/App.jsx", "content": "export default function App() { return <main>ApexFlow AI</main>; }"},
        {"path": "reports/operations_report.pdf", "content": "old generated artifact"},
      ]

    def list_memory_chat_topics(self, user, *, project_id, chat_session_id, limit=16, status="active"):
      return []

    def create_memory_chat_topic(self, user, **kwargs):
      return kwargs

    def update_memory_chat_topic(self, user, *, chat_topic_id, **updates):
      return {"id": chat_topic_id, **updates}

    def list_project_chat_messages(self, project_id, user, *, limit=120, chat_session_id=None, chat_topic_id=None):
      return [
        {"role": "user", "content": "Explain the full project", "metadata_json": {}},
        {"role": "model", "content": "Previous project summary", "metadata_json": {}},
      ]

    def get_memory_chat_session_state(self, user, *, project_id=None, chat_session_id=None, chat_topic_id=None):
      return {}

    def list_memory_preferences(self, user, *, limit=50):
      return []

    def list_memory_platform_patterns(self, **kwargs):
      return []

    def list_memory_learning_events(self, user, **kwargs):
      return []

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
      return []

  store = _ProjectInfoStore()
  context = SimpleNamespace(store=store, settings=SimpleNamespace())
  user = UserContext(id="user-1", email="user@example.com", role="editor")

  preflight = prepare_generation_pipeline_inputs(
    context=context,
    project_id="project-1",
    prompt="explain about this project",
    user=user,
    project={},
    normalized_attachments=[],
    resolved_chat_session_id="session-1",
    request_class=None,
    estimated_credit_reservation=0,
    model="gemini-test",
    artifact_model="gemini-test",
    model_policy="default",
    progress_callback=None,
    telemetry=None,
    system_name=None,
    confirmation_action=None,
    topic_llm_provider=None,
  )

  assert preflight["adaptive_route"]["route"] == "conversation"
  assert preflight["adaptive_route"]["use_project_context"] is True
  assert preflight["read_only_project_info_context"] is True
  assert preflight["raw_chat_history"] != []
  assert preflight["agents_md_block"] == ""
  assert preflight["memory_context"] == ""
  assert preflight["skills_block"] == ""
  assert preflight["effective_prompt"] == "explain about this project"
