from backend.api.chat import (
  create_project_chat_session_payload,
  ensure_project_chat_session,
  list_project_chat_payload,
  list_project_chat_sessions_payload,
)


class FakeSessionStore:
  def __init__(self):
    self.projects = {"project-1": {"id": "project-1", "local_path": ""}}
    self.sessions = []
    self.messages = []
    self.memory_items = []

  def get_project(self, project_id, user):
    return self.projects.get(project_id)

  def create_chat_session(self, project_id, user, *, title="", status="active"):
    session = {
      "id": f"session-{len(self.sessions) + 1}",
      "project_id": project_id,
      "user_id": user.id,
      "title": title,
      "status": status,
      "created_at": "2026-06-26T12:00:00+00:00",
      "updated_at": "2026-06-26T12:00:00+00:00",
    }
    self.sessions.append(session)
    return session

  def get_chat_session(self, session_id, user):
    for session in self.sessions:
      if session["id"] == session_id:
        return session
    return None

  def list_chat_sessions(self, project_id, user, *, limit=20, status=None):
    sessions = [
      item
      for item in self.sessions
      if item["project_id"] == project_id and item["user_id"] == user.id
    ]
    if status:
      sessions = [item for item in sessions if item.get("status") == status]
    sessions.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
    return sessions[:limit]

  def close_active_chat_sessions(self, project_id, user, *, except_session_id=None):
    for session in self.sessions:
      if session["project_id"] != project_id or session["user_id"] != user.id:
        continue
      if session.get("status") != "active":
        continue
      if except_session_id and session["id"] == except_session_id:
        continue
      session["status"] = "closed"

  def ensure_active_chat_session(self, project_id, user):
    sessions = self.list_chat_sessions(project_id, user, limit=1, status="active")
    if sessions:
      return sessions[0]
    return self.create_chat_session(project_id, user)

  def _attach_legacy_messages_to_session(self, project_id, user, session_id):
    for message in self.messages:
      if message["project_id"] == project_id and message["user_id"] == user.id and not message.get("chat_session_id"):
        message["chat_session_id"] = session_id

  def resolve_chat_session_id(self, project_id, user, chat_session_id=None):
    if chat_session_id:
      session = self.get_chat_session(chat_session_id, user)
      if not session or session["project_id"] != project_id:
        raise ValueError("Chat session not found for this project.")
      return session["id"]
    session = self.ensure_active_chat_session(project_id, user)
    self._attach_legacy_messages_to_session(project_id, user, session["id"])
    return session["id"]

  def touch_chat_session(self, session_id):
    return None

  def record_project_chat_message(self, project_id, user, *, role, content, metadata=None, chat_session_id=None):
    resolved = self.resolve_chat_session_id(project_id, user, chat_session_id)
    row = {
      "id": f"msg-{len(self.messages) + 1}",
      "project_id": project_id,
      "user_id": user.id,
      "chat_session_id": resolved,
      "role": role,
      "content": content,
      "metadata_json": metadata or {},
      "created_at": "2026-06-26T12:00:00+00:00",
    }
    self.messages.append(row)
    return row

  def list_project_chat_messages(self, project_id, user, *, limit=80, chat_session_id=None):
    resolved = self.resolve_chat_session_id(project_id, user, chat_session_id)
    return [
      item
      for item in self.messages
      if item["project_id"] == project_id and item["user_id"] == user.id and item.get("chat_session_id") == resolved
    ][:limit]

  def list_memory_items(self, user, *, project_id, namespace, limit=12, kind=None):
    rows = [item for item in self.memory_items if item.get("project_id") == project_id]
    if namespace:
      rows = [item for item in rows if item.get("namespace") == namespace]
    if kind:
      rows = [item for item in rows if item.get("kind") == kind]
    return rows[:limit]


class FakeUser:
  id = "user-abc-123"
  email = "dev@vibe.local"
  role = "admin"


def test_create_and_list_chat_sessions_per_user():
  store = FakeSessionStore()
  user = FakeUser()
  created = create_project_chat_session_payload("project-1", store, user, title="Landing page chat")
  listed = list_project_chat_sessions_payload("project-1", store, user)
  assert created["user_id"] == "user-abc-123"
  assert listed["count"] == 1
  assert listed["sessions"][0]["id"] == created["session"]["id"]


def test_chat_messages_are_scoped_to_session():
  store = FakeSessionStore()
  user = FakeUser()
  session_a = create_project_chat_session_payload("project-1", store, user)["session"]["id"]
  store.record_project_chat_message(
    "project-1",
    user,
    role="user",
    content="Build a landing page",
    chat_session_id=session_a,
  )
  session_b = create_project_chat_session_payload("project-1", store, user)["session"]["id"]
  payload_a = list_project_chat_payload("project-1", store, user, chat_session_id=session_a)
  payload_b = list_project_chat_payload("project-1", store, user, chat_session_id=session_b)
  assert payload_a["user_id"] == "user-abc-123"
  assert payload_a["chat_session"]["id"] == session_a
  assert len(payload_a["messages"]) == 1
  assert len(payload_b["messages"]) == 0


def test_ensure_active_chat_session_returns_existing():
  store = FakeSessionStore()
  user = FakeUser()
  first = ensure_project_chat_session("project-1", store, user)
  second = ensure_project_chat_session("project-1", store, user)
  assert first["id"] == second["id"]


def test_create_chat_session_closes_previous_active_sessions():
  store = FakeSessionStore()
  user = FakeUser()
  first = create_project_chat_session_payload("project-1", store, user, title="First")["session"]
  second = create_project_chat_session_payload("project-1", store, user, title="Second")["session"]
  assert first["id"] != second["id"]
  assert store.get_chat_session(first["id"], user)["status"] == "closed"
  assert store.get_chat_session(second["id"], user)["status"] == "active"
