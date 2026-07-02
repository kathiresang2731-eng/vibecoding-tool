from types import SimpleNamespace

from backend.agents.memory.preferences_api import (
  delete_memory_preference_payload,
  list_memory_preferences_payload,
  preference_is_injected,
  upsert_memory_preference_payload,
)
from backend.api import memory_preferences as memory_preferences_facade
from backend.storage import UserContext


class MemoryPreferenceStore:
  def __init__(self):
    self.preferences: list[dict] = []

  def list_memory_preferences(self, user, *, limit=50):
    return list(self.preferences)[:limit]

  def upsert_memory_preference(
    self,
    user,
    *,
    category,
    preference,
    polarity="positive",
    confidence=0.8,
    durability="long_term",
    reason="",
    metadata=None,
  ):
    row = {
      "id": f"pref-{len(self.preferences) + 1}",
      "category": category,
      "preference": preference,
      "polarity": polarity,
      "confidence": confidence,
      "durability": durability,
      "reason": reason,
      "metadata_json": metadata or {},
    }
    self.preferences = [
      item
      for item in self.preferences
      if not (item.get("category") == category and item.get("preference") == preference)
    ]
    self.preferences.append(row)
    return row

  def delete_memory_preference(self, user, *, preference_id):
    before = len(self.preferences)
    self.preferences = [item for item in self.preferences if item.get("id") != preference_id]
    return len(self.preferences) < before


def test_preference_is_injected_respects_confidence_and_durability():
  assert preference_is_injected({"confidence": 0.85, "durability": "long_term"}) is True
  assert preference_is_injected({"confidence": 0.4, "durability": "long_term"}) is False
  assert preference_is_injected({"confidence": 0.9, "durability": "ephemeral"}) is False
  assert preference_is_injected({"confidence": 0.9, "durability": "session"}) is False


def test_list_memory_preferences_payload():
  store = MemoryPreferenceStore()
  user = UserContext(id="user-1", email="u@example.com", role="owner", display_name="User")
  store.upsert_memory_preference(user, category="coding_style", preference="Use TypeScript", confidence=0.9)
  payload = list_memory_preferences_payload(user, store)
  assert payload["schema"] == "worktual.memory-preferences.v1"
  assert len(payload["preferences"]) == 1
  assert payload["preferences"][0]["injected_into_agent_context"] is True


def test_memory_preferences_api_facade_imports_backend_package():
  assert memory_preferences_facade.list_memory_preferences_payload is list_memory_preferences_payload
  assert memory_preferences_facade.upsert_memory_preference_payload is upsert_memory_preference_payload
  assert memory_preferences_facade.delete_memory_preference_payload is delete_memory_preference_payload


def test_upsert_memory_preference_payload():
  store = MemoryPreferenceStore()
  user = UserContext(id="user-1", email="u@example.com", role="owner", display_name="User")
  payload = upsert_memory_preference_payload(
    user,
    SimpleNamespace(
      category="stack",
      preference="Prefer Tailwind CSS",
      polarity="positive",
      confidence=0.85,
      durability="long_term",
      reason="",
      metadata=None,
    ),
    store,
  )
  assert payload["preference"]["category"] == "stack"
  assert payload["preference"]["injected_into_agent_context"] is True


def test_delete_memory_preference_payload():
  store = MemoryPreferenceStore()
  user = UserContext(id="user-1", email="u@example.com", role="owner", display_name="User")
  row = store.upsert_memory_preference(user, category="workflow", preference="Small focused diffs")
  payload = delete_memory_preference_payload(user, row["id"], store)
  assert payload["deleted"] is True
  assert list_memory_preferences_payload(user, store)["preferences"] == []
