from backend.agents.memory.episodes_api import (
  delete_memory_episode_payload,
  list_memory_episodes_payload,
  serialize_memory_episode,
)
from backend.storage import UserContext
from backend.api import memory_episodes as memory_episodes_facade


class MemoryEpisodeStore:
  def __init__(self):
    self.projects = {"project-1": {"id": "project-1", "name": "Demo"}}
    self.episodes: list[dict] = []
    self.session_states: dict[str, dict] = {}

  def get_project(self, project_id, user):
    return self.projects.get(project_id)

  def insert_memory_episode(self, user, **kwargs):
    row = {
      "id": f"ep-{len(self.episodes) + 1}",
      "created_at": "2026-06-27T12:00:00Z",
      "updated_at": "2026-06-27T12:00:00Z",
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

  def delete_memory_episode(self, user, *, episode_id, project_id):
    before = len(self.episodes)
    self.episodes = [
      row for row in self.episodes if not (row.get("id") == episode_id and row.get("project_id") == project_id)
    ]
    return len(self.episodes) < before

  def get_memory_chat_session_state(self, user, *, chat_session_id):
    return self.session_states.get(chat_session_id)


def _seed_episodes(store: MemoryEpisodeStore, user: UserContext) -> None:
  store.insert_memory_episode(
    user,
    project_id="project-1",
    chat_session_id="session-1",
    generation_run_id="run-1",
    scope="personal",
    memory_type="update_checkpoint",
    title="Navbar spacing update",
    searchable_summary="Intent: website_update\nOutcome: completed\nUser request: tighten navbar spacing",
    outcome="completed",
    changed_paths=["src/App.jsx"],
    metadata={"intent": "website_update", "chat_session_id": "session-1", "prompt": "tighten navbar spacing"},
  )
  store.insert_memory_episode(
    user,
    project_id="project-1",
    chat_session_id="session-1",
    generation_run_id="run-2",
    scope="personal",
    memory_type="workflow",
    title="Landing page generation",
    searchable_summary="Intent: website_generation\nOutcome: completed\nUser request: build landing page",
    outcome="completed",
    changed_paths=["src/pages/Home.jsx"],
    metadata={"intent": "website_generation", "chat_session_id": "session-1", "prompt": "build landing page"},
  )
  store.session_states["session-1"] = {
    "chat_session_id": "session-1",
    "rolling_summary": "Built landing page, then tightened navbar spacing.",
    "update_count": 2,
    "last_changed_paths_json": ["src/App.jsx"],
    "last_preview_status": "ready",
  }


def test_list_memory_episodes_payload_includes_session_state_and_injection_flags():
  store = MemoryEpisodeStore()
  user = UserContext(id="user-1", email="u@example.com", role="owner", display_name="User")
  _seed_episodes(store, user)
  payload = list_memory_episodes_payload(
    user,
    store,
    project_id="project-1",
    chat_session_id="session-1",
    prompt="navbar spacing",
  )
  assert payload["schema"] == "worktual.memory-episodes.v1"
  assert len(payload["episodes"]) == 2
  assert payload["session_memory_state"]["update_count"] == 2
  assert any(item["injected_into_agent_context"] for item in payload["episodes"])


def test_memory_episodes_api_facade_imports_backend_package():
  assert memory_episodes_facade.list_memory_episodes_payload is list_memory_episodes_payload
  assert memory_episodes_facade.delete_memory_episode_payload is delete_memory_episode_payload


def test_delete_memory_episode_payload():
  store = MemoryEpisodeStore()
  user = UserContext(id="user-1", email="u@example.com", role="owner", display_name="User")
  _seed_episodes(store, user)
  episode_id = store.episodes[0]["id"]
  payload = delete_memory_episode_payload(user, store, episode_id=episode_id, project_id="project-1")
  assert payload["deleted"] is True
  remaining = list_memory_episodes_payload(
    user,
    store,
    project_id="project-1",
    chat_session_id="session-1",
  )
  assert len(remaining["episodes"]) == 1


def test_serialize_memory_episode_exposes_summary():
  row = {
    "id": "ep-1",
    "content": "Intent: website_update\nUser request: fix navbar",
    "metadata_json": {"intent": "website_update", "outcome": "completed", "changed_paths": ["src/App.jsx"]},
  }
  payload = serialize_memory_episode(row, injected_into_agent_context=True)
  assert payload["injected_into_agent_context"] is True
  assert "fix navbar" in payload["searchable_summary"]
