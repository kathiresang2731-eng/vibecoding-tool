from __future__ import annotations

from backend.agents.memory.consistency_worker import process_due_consistency_jobs
from backend.agents.memory.context import build_unified_memory_context_block
from backend.agents.memory.project_knowledge import persist_project_ui_knowledge
from backend.storage import UserContext


INITIAL_FILES = [
  {
    "path": "src/App.jsx",
    "content": (
      "import Analytics from './pages/Analytics.jsx';\n"
      "import Auth from './pages/Auth.jsx';\n"
      "export default function App() { return <Routes>"
      "<Route path=\"/analytics\" element={<Analytics />} />"
      "<Route path=\"/auth\" element={<Auth />} />"
      "</Routes>; }\n"
    ),
  },
  {
    "path": "src/pages/Analytics.jsx",
    "content": (
      "export default function Analytics() {\n"
      "  return <main><h1>Advanced Analytics Portal</h1>"
      "<button type=\"button\">Start Onboarding Walkthrough</button></main>;\n"
      "}\n"
    ),
  },
  {
    "path": "src/pages/Auth.jsx",
    "content": "export default function Auth() { return <main><h1>Password Reset</h1></main>; }\n",
  },
]


UPDATED_FILES = [
  INITIAL_FILES[0],
  {
    "path": "src/pages/Analytics.jsx",
    "content": (
      "export default function Analytics() {\n"
      "  return <main><h1>Advanced Analytics Portal</h1>"
      "<button type=\"button\">Begin Onboarding</button></main>;\n"
      "}\n"
    ),
  },
  INITIAL_FILES[2],
]


class _FlowStore:
  def __init__(self) -> None:
    self.files = list(INITIAL_FILES)
    self.memory_items: list[dict] = []
    self.jobs: list[dict] = []
    self.completed: list[str] = []
    self.failed: list[tuple[str, str]] = []
    self.topic = {
      "id": "topic-analytics",
      "project_id": "project-1",
      "chat_session_id": "session-1",
      "user_id": "user-1",
      "label": "Analytics page walkthrough button",
      "intent_family": "website_update",
      "last_changed_paths_json": ["src/pages/Analytics.jsx"],
      "rolling_summary": (
        "User is working on the Advanced Analytics Portal page. "
        "The Start Onboarding Walkthrough button lives in src/pages/Analytics.jsx."
      ),
    }
    self.session_state = {
      "chat_session_id": "session-1",
      "project_id": "project-1",
      "user_id": "user-1",
      "state_scope_key": "",
      "rolling_summary": "Unrelated auth task: Password Reset page copy was updated.",
      "last_changed_paths_json": ["src/pages/Auth.jsx"],
      "update_count": 1,
    }
    self.episodes = [
      {
        "id": "episode-analytics",
        "project_id": "project-1",
        "chat_session_id": "session-1",
        "chat_topic_id": "topic-analytics",
        "scope": "personal",
        "title": "Analytics walkthrough button",
        "searchable_summary": "Start Onboarding Walkthrough button belongs to src/pages/Analytics.jsx.",
        "metadata_json": {"intent": "website_update", "changed_paths": ["src/pages/Analytics.jsx"]},
      },
      {
        "id": "episode-auth",
        "project_id": "project-1",
        "chat_session_id": "session-1",
        "chat_topic_id": "topic-auth",
        "scope": "personal",
        "title": "Auth page reset",
        "searchable_summary": "Password Reset page lives in src/pages/Auth.jsx.",
        "metadata_json": {"intent": "website_update", "changed_paths": ["src/pages/Auth.jsx"]},
      },
    ]

  def list_files(self, project_id, user):
    return list(self.files)

  def upsert_memory_item(self, user, **payload):
    row = {
      "id": "memory-ui",
      **payload,
      "metadata_json": payload.get("metadata") or {},
    }
    self.memory_items = [row]
    return row

  def list_memory_items(self, user, *, project_id, namespace, kind=None, limit=12):
    rows = [item for item in self.memory_items if item.get("project_id") == project_id]
    if namespace:
      rows = [item for item in rows if item.get("namespace") == namespace]
    if kind:
      rows = [item for item in rows if item.get("kind") == kind]
    return rows[:limit]

  def get_memory_chat_topic(self, user, *, chat_topic_id):
    return self.topic if chat_topic_id == self.topic["id"] else None

  def get_memory_chat_session_state(self, user, **kwargs):
    return self.session_state

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
    rows = list(self.episodes)
    if project_id:
      rows = [row for row in rows if row.get("project_id") == project_id]
    if chat_session_id:
      rows = [row for row in rows if row.get("chat_session_id") == chat_session_id]
    if chat_topic_id:
      rows = [row for row in rows if row.get("chat_topic_id") == chat_topic_id]
    if scope:
      rows = [row for row in rows if row.get("scope") == scope]
    return rows[:limit]

  def enqueue_ui_refresh(self, *, chat_topic_id="topic-analytics"):
    self.jobs.append(
      {
        "id": f"job-{len(self.jobs) + 1}",
        "project_id": "project-1",
        "user_id": "user-1",
        "job_type": "project_ui_knowledge_refresh",
        "attempt_count": 0,
        "payload_json": {
          "chat_session_id": "session-1",
          "chat_topic_id": chat_topic_id,
          "changed_paths": ["src/pages/Analytics.jsx"],
        },
      }
    )

  def list_due_consistency_jobs(self, *, limit, user_id=None):
    return [
      job
      for job in self.jobs
      if job["id"] not in self.completed and (not user_id or job.get("user_id") == user_id)
    ][:limit]

  def mark_consistency_job_processing(self, *, job_id):
    return any(job["id"] == job_id for job in self.jobs)

  def complete_consistency_job(self, *, job_id):
    self.completed.append(job_id)
    return True

  def fail_consistency_job(self, *, job_id, error, retry_seconds):
    self.failed.append((job_id, error))
    return True


def test_update_that_page_flow_uses_same_topic_memory_and_fresh_ui_knowledge(monkeypatch) -> None:
  monkeypatch.setenv("ENABLE_EPISODIC_VECTOR_SEARCH", "false")
  store = _FlowStore()
  user = UserContext(id="user-1", email="u@example.com", role="editor")

  persisted = persist_project_ui_knowledge(
    store,
    user,
    project_id="project-1",
    files=store.list_files("project-1", user),
    chat_session_id="session-1",
    chat_topic_id="topic-analytics",
  )
  assert persisted["status"] == "stored"

  first_context = build_unified_memory_context_block(
    store,
    user,
    project_id="project-1",
    prompt="on that page Start Onboarding Walkthrough button should redirect to onboarding",
    chat_session_id="session-1",
    chat_topic_id="topic-analytics",
    files=store.list_files("project-1", user),
  )

  assert "src/pages/Analytics.jsx" in first_context
  assert "Start Onboarding Walkthrough" in first_context
  assert "Chat topic continuity memory" in first_context
  assert "episode-analytics" in first_context
  assert "Password Reset page copy" not in first_context
  assert "episode-auth" not in first_context

  store.files = list(UPDATED_FILES)
  store.enqueue_ui_refresh()
  result = process_due_consistency_jobs(store, user)

  assert result == {"seen": 1, "completed": 1, "failed": 0, "skipped": 0}
  assert store.failed == []
  assert store.memory_items[0]["metadata_json"]["chat_topic_id"] == "topic-analytics"

  follow_up_context = build_unified_memory_context_block(
    store,
    user,
    project_id="project-1",
    prompt="make that button label Begin Onboarding stand out",
    chat_session_id="session-1",
    chat_topic_id="topic-analytics",
    files=store.list_files("project-1", user),
  )

  assert "Begin Onboarding" in follow_up_context
  assert "src/pages/Analytics.jsx" in follow_up_context
  assert "Password Reset" not in follow_up_context


def test_read_only_referential_followup_uses_same_topic_memory(monkeypatch) -> None:
  monkeypatch.setenv("ENABLE_EPISODIC_VECTOR_SEARCH", "false")
  store = _FlowStore()
  user = UserContext(id="user-1", email="u@example.com", role="editor")

  context = build_unified_memory_context_block(
    store,
    user,
    project_id="project-1",
    prompt="tell me more detailed information about him",
    chat_session_id="session-1",
    chat_topic_id="topic-analytics",
    files=store.list_files("project-1", user),
  )

  assert "Chat topic continuity memory" in context
  assert "Advanced Analytics Portal" in context
  assert "Start Onboarding Walkthrough" in context
  assert "Password Reset page copy" not in context
