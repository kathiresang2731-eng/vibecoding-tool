from backend.agents.memory.context import build_user_preferences_context_block, build_unified_memory_context_block
from backend.agents.memory.session_extraction import extract_closed_session_memories
from backend.storage import UserContext


class _SessionStore:
  def __init__(self):
    self.preferences: list[dict] = []
    self.episodes: list[dict] = []
    self.messages: list[dict] = []
    self.session_states: dict[str, dict] = {}

  def list_memory_preferences(self, user, *, limit=50):
    return self.preferences[:limit]

  def upsert_memory_preference(self, user, *, category, preference, polarity="positive", confidence=0.8, durability="long_term", reason="", metadata=None):
    row = {
      "category": category,
      "preference": preference,
      "polarity": polarity,
      "confidence": confidence,
      "durability": durability,
    }
    self.preferences.append(row)
    return row

  def insert_memory_episode(self, user, **kwargs):
    row = {"id": f"ep-{len(self.episodes) + 1}", **kwargs}
    self.episodes.append(row)
    return row

  def list_project_chat_messages(self, project_id, user, *, limit=200, chat_session_id=None):
    rows = [row for row in self.messages if row.get("chat_session_id") == chat_session_id]
    return rows[:limit]

  def get_memory_chat_session_state(self, user, *, chat_session_id):
    return self.session_states.get(chat_session_id)

  def upsert_memory_chat_session_state(self, user, *, project_id, chat_session_id, rolling_summary, **kwargs):
    metadata = kwargs.get("metadata") or {}
    row = {
      "chat_session_id": chat_session_id,
      "rolling_summary": rolling_summary,
      "metadata_json": metadata,
      **kwargs,
    }
    self.session_states[chat_session_id] = row
    return row


def test_build_user_preferences_context_block_filters_low_confidence() -> None:
  store = _SessionStore()
  user = UserContext(id="user-1", email="u@example.com", role="user")
  store.preferences = [
    {"category": "style", "preference": "Use Tailwind utility classes", "confidence": 0.9, "durability": "long_term", "polarity": "positive"},
    {"category": "noise", "preference": "Ignore me", "confidence": 0.2, "durability": "long_term", "polarity": "positive"},
  ]
  block = build_user_preferences_context_block(store, user)
  assert "Tailwind" in block
  assert "Ignore me" not in block


def test_extract_closed_session_memories_is_idempotent() -> None:
  store = _SessionStore()
  user = UserContext(id="user-1", email="u@example.com", role="user")
  store.messages = [
    {"role": "user", "content": "Build a CRM with vitest tests", "chat_session_id": "session-1"},
    {"role": "assistant", "content": "Done", "chat_session_id": "session-1"},
    {"role": "user", "content": "Use tailwind and keep explanations concise", "chat_session_id": "session-1"},
  ]
  first = extract_closed_session_memories(
    store,
    user,
    project_id="project-1",
    chat_session_id="session-1",
    settings=None,
    use_llm=False,
  )
  second = extract_closed_session_memories(
    store,
    user,
    project_id="project-1",
    chat_session_id="session-1",
    settings=None,
    use_llm=False,
  )
  assert first["status"] == "completed"
  assert first["preference_count"] >= 1
  assert first["episode_saved"] is True
  assert second["status"] == "skipped"
  assert second["reason"] == "already_extracted"


def test_unified_memory_includes_user_preferences() -> None:
  store = _SessionStore()
  user = UserContext(id="user-1", email="u@example.com", role="user")
  store.preferences = [
    {"category": "workflow", "preference": "Keep responses concise", "confidence": 0.85, "durability": "long_term", "polarity": "positive"},
  ]
  store.session_states["session-1"] = {
    "chat_session_id": "session-1",
    "update_count": 1,
    "rolling_summary": "Updated navbar spacing",
  }
  block = build_unified_memory_context_block(
    store,
    user,
    project_id="project-1",
    prompt="update navbar",
    chat_session_id="session-1",
  )
  assert "Learned user requirements" in block
  assert "concise" in block.lower()
