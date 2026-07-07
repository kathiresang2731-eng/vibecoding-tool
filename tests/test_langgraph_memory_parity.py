from backend.agents.memory.runtime_memory import augment_memory_result_with_unified_context
from backend.storage import UserContext


class _Store:
  def __init__(self):
    self.preferences = [
      {
        "category": "style",
        "preference": "Use Tailwind utilities",
        "confidence": 0.9,
        "durability": "long_term",
        "polarity": "positive",
      }
    ]
    self.session_states = {
      "session-1": {
        "chat_session_id": "session-1",
        "update_count": 2,
        "rolling_summary": "Updated navbar spacing",
      }
    }

  def list_memory_preferences(self, user, *, limit=50):
    return self.preferences[:limit]

  def get_memory_chat_session_state(self, user, *, chat_session_id):
    return self.session_states.get(chat_session_id)

  def list_memory_episodes(self, user, *, project_id, chat_session_id, scope, limit):
    return []


def test_augment_memory_result_injects_unified_context() -> None:
  store = _Store()
  user = UserContext(id="user-1", email="u@example.com", role="user")
  events: list[str] = []

  result = augment_memory_result_with_unified_context(
    {"project_id": "project-1", "memories": [{"content": "legacy item"}], "memory_count": 1},
    store=store,
    user=user,
    project_id="project-1",
    prompt="update navbar spacing",
    chat_session_id="session-1",
    project_name="Demo Site",
    progress=lambda step, _message, **_kwargs: events.append(step),
  )

  assert result["memory_count"] >= 2
  assert "unified_context" in result
  assert "Learned user requirements" in result["unified_context"]
  assert "memory.context.injected" in events


def test_augment_memory_result_skips_without_session() -> None:
  store = _Store()
  user = UserContext(id="user-1", email="u@example.com", role="user")
  base = {"memories": [], "memory_count": 0}
  result = augment_memory_result_with_unified_context(
    base,
    store=store,
    user=user,
    project_id="project-1",
    prompt="hello",
    chat_session_id=None,
  )
  assert result == base
