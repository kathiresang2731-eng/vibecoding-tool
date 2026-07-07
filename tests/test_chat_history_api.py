from backend.api.chat import (
  apply_confirmation_overrides,
  build_conversation_state,
  list_project_chat_payload,
  record_project_chat_payload,
  serialize_chat_message_for_api,
)


class FakeChatStore:
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

  def list_chat_sessions(self, project_id, user, *, limit=20):
    return [item for item in self.sessions if item["project_id"] == project_id and item["user_id"] == user.id][:limit]

  def ensure_active_chat_session(self, project_id, user):
    sessions = self.list_chat_sessions(project_id, user, limit=1)
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

  def list_project_chat_messages(self, project_id, user, *, limit=80, chat_session_id=None):
    resolved = self.resolve_chat_session_id(project_id, user, chat_session_id)
    return [
      item
      for item in self.messages
      if item["project_id"] == project_id and item["user_id"] == user.id and item.get("chat_session_id") == resolved
    ][:limit]

  def record_project_chat_message(self, project_id, user, *, role, content, metadata=None, chat_session_id=None, emit_event=True):
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

  def list_memory_items(self, user, *, project_id, namespace, limit=12, kind=None):
    rows = [item for item in self.memory_items if item.get("project_id") == project_id]
    if namespace:
      rows = [item for item in rows if item.get("namespace") == namespace]
    if kind:
      rows = [item for item in rows if item.get("kind") == kind]
    return rows[:limit]

  def upsert_memory_item(self, user, *, project_id, namespace, key, kind, content, metadata=None):
    item = {
      "project_id": project_id,
      "namespace": namespace,
      "key": key,
      "kind": kind,
      "content": content,
      "metadata_json": metadata or {},
      "updated_at": "2026-06-26T12:00:00+00:00",
    }
    self.memory_items.insert(0, item)
    return item


class FakeUser:
  id = "user-1"
  email = "dev@vibe.local"
  role = "admin"


def test_serialize_chat_message_uses_display_content():
  row = {
    "id": "m1",
    "role": "model",
    "content": "memory summary only",
    "metadata_json": {"display_content": "Hello from assistant"},
    "created_at": "2026-06-26T12:00:00+00:00",
  }
  payload = serialize_chat_message_for_api(row)
  assert payload["role"] == "assistant"
  assert payload["content"] == "Hello from assistant"


def test_list_project_chat_payload_includes_conversation_state():
  store = FakeChatStore()
  user = FakeUser()
  session = store.ensure_active_chat_session("project-1", user)
  store.record_project_chat_message(
    "project-1",
    user,
    role="user",
    content="Build a landing page",
    metadata={"source": "generation_api"},
    chat_session_id=session["id"],
  )
  store.record_project_chat_message(
    "project-1",
    user,
    role="model",
    content="memory",
    metadata={"display_content": "I will build that landing page.", "intent": "website_generation"},
    chat_session_id=session["id"],
  )
  store.upsert_memory_item(
    user,
    project_id="project-1",
    namespace="project",
    key="run-1",
    kind="episodic",
    content="Intent: website_generation\nOutcome: completed",
    metadata={"intent": "website_generation", "outcome": "completed"},
  )

  payload = list_project_chat_payload("project-1", store, user)
  assert payload["conversation"]["message_count"] == 2
  assert payload["conversation"]["last_intent"] == "website_generation"
  assert payload["messages"][1]["content"] == "I will build that landing page."


def test_apply_confirmation_overrides_marks_cancelled():
  messages = [
    {"role": "assistant", "content": "brief", "confirmation": {"status": "pending"}},
    {"role": "user", "content": "Cancel the pending execution brief."},
  ]
  updated = apply_confirmation_overrides(messages)
  assert updated[0]["confirmation"]["status"] == "cancelled"


def test_record_project_chat_payload_accepts_assistant_role():
  store = FakeChatStore()
  user = FakeUser()
  payload = record_project_chat_payload(
    "project-1",
    store,
    user,
    role="assistant",
    content="Imported local folder.",
    metadata={"source": "browser_ui"},
  )
  assert payload["message"]["role"] == "assistant"
  assert store.messages[-1]["role"] == "model"


def test_build_conversation_state_includes_relative_resume_hint():
  messages = [
    {
      "role": "user",
      "content": "Update the hero section copy",
      "created_at": "2026-06-20T10:00:00+00:00",
    }
  ]
  episodic = [
    {
      "metadata_json": {
        "intent": "website_update",
        "outcome": "completed",
        "changed_paths": ["src/App.jsx", "src/styles.css"],
      }
    }
  ]
  conversation = build_conversation_state(
    messages,
    episodic,
    chat_session={"id": "session-1", "status": "active", "updated_at": "2026-06-20T10:05:00+00:00"},
  )
  assert "website update" in conversation["resume_hint"].lower()
  assert "src/App.jsx" in conversation["resume_hint"]
  assert conversation["last_activity_at"]
