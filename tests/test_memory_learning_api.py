from backend.agents.memory.learning_events_api import (
  list_learning_events_payload,
  why_injected_payload,
)
from backend.api import memory_learning as memory_learning_facade
from backend.storage import UserContext


class _LearningApiStore:
  def __init__(self):
    self.events = [
      {
        "id": "learn-1",
        "user_id": "user-1",
        "project_id": "project-1",
        "chat_session_id": "session-1",
        "run_id": "run-1",
        "request_text_hash": "hash-only",
        "normalized_intent": "website_generation",
        "domain": "crm",
        "task_type": "full_generation",
        "changed_paths_json": ["src/App.jsx"],
        "validation_status": "passed",
        "mistake_type": "single_static_page",
        "extracted_lesson": "Generate route-backed CRM modules.",
        "scope": "soft_platform",
        "confidence": 0.78,
        "metadata_json": {
          "source": "memory_learning_events",
          "contains_raw_request": False,
        },
        "created_at": "2026-07-01T10:00:00Z",
      }
    ]
    self.patterns = [
      {
        "id": "pattern-1",
        "pattern_key": "crm-blueprint",
        "domain": "crm",
        "module": "leads",
        "pattern_type": "generation_blueprint",
        "memory_type": "workflow",
        "title": "CRM blueprint",
        "summary": "Reusable CRM generation blueprint.",
        "improved_behavior": "Generate route-backed CRM modules.",
        "avoid": "Avoid one static dashboard.",
        "source_count": 1,
        "confidence_score": 0.6,
        "metadata_json": {
          "promotion_status": "soft_platform_lesson",
          "confidence_tier": "soft_platform_lesson",
          "last_applied_run_id": "run-1",
          "contains_chat": False,
        },
      }
    ]

  def list_memory_learning_events(
    self,
    user,
    *,
    project_id=None,
    chat_session_id=None,
    run_id=None,
    scope=None,
    limit=50,
    include_all_users=False,
  ):
    rows = list(self.events)
    if not include_all_users:
      rows = [row for row in rows if row["user_id"] == user.id]
    if project_id:
      rows = [row for row in rows if row["project_id"] == project_id]
    if chat_session_id:
      rows = [row for row in rows if row["chat_session_id"] == chat_session_id]
    if run_id:
      rows = [row for row in rows if row["run_id"] == run_id]
    if scope:
      rows = [row for row in rows if row["scope"] == scope]
    return rows[:limit]

  def list_memory_platform_patterns(self, *, domain=None, module=None, pattern_type=None, limit=25):
    rows = list(self.patterns)
    if domain:
      rows = [row for row in rows if row["domain"] == domain]
    if module:
      rows = [row for row in rows if row["module"] == module]
    if pattern_type:
      rows = [row for row in rows if row["pattern_type"] == pattern_type]
    return rows[:limit]


def test_learning_events_payload_exposes_structured_data_without_raw_request():
  store = _LearningApiStore()
  user = UserContext(id="user-1", email="one@example.com", role="user")

  payload = list_learning_events_payload(store, user, project_id="project-1")

  assert payload["schema"] == "worktual.memory-learning-events.v1"
  assert payload["stats"]["listed"] == 1
  event = payload["events"][0]
  assert event["request_text_hash"] == "hash-only"
  assert event["metadata"]["contains_raw_request"] is False
  assert "request_preview" not in event["metadata"]


def test_why_injected_payload_links_run_to_event_and_platform_pattern():
  store = _LearningApiStore()
  admin = UserContext(id="admin-1", email="admin@example.com", role="admin")

  payload = why_injected_payload(store, admin, run_id="run-1")

  assert payload["schema"] == "worktual.memory-why-injected.v1"
  assert payload["learning_events"][0]["id"] == "learn-1"
  assert payload["matching_platform_patterns"][0]["id"] == "pattern-1"
  assert payload["injection_rules"]["current_request_overrides_memory"] is True


def test_memory_learning_api_facade_exports_payload_builders():
  assert memory_learning_facade.list_learning_events_payload is list_learning_events_payload
  assert memory_learning_facade.why_injected_payload is why_injected_payload
