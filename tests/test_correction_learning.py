from backend.agents.memory.context import build_unified_memory_context_block
from backend.agents.memory.correction_learning import (
  build_platform_correction_context_block,
  extract_correction_preferences,
  persist_turn_correction_learning,
  persist_turn_learning,
)
from backend.storage import UserContext
from backend.storage.memory_framework import build_platform_pattern_key


class _LearningStore:
  def __init__(self):
    self.messages: list[dict] = []
    self.preferences: list[dict] = []
    self.platform_patterns: dict[str, dict] = {}
    self.platform_events: list[dict] = []

  def list_project_chat_messages(self, project_id, user, *, limit=200, chat_session_id=None):
    rows = [row for row in self.messages if row.get("chat_session_id") == chat_session_id]
    return rows[:limit]

  def list_memory_preferences(self, user, *, limit=50):
    return [row for row in self.preferences if row.get("user_id") == user.id][:limit]

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
      "user_id": user.id,
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
      if not (
        item.get("user_id") == user.id
        and item.get("category") == category
        and item.get("preference") == preference
      )
    ]
    self.preferences.append(row)
    return row

  def upsert_memory_platform_pattern(self, **kwargs):
    key = build_platform_pattern_key(
      domain=kwargs.get("domain", "general"),
      module=kwargs.get("module", "general"),
      pattern_type=kwargs.get("pattern_type", "general"),
      title=kwargs.get("title", "pattern"),
    )
    existing = self.platform_patterns.get(key)
    metadata = kwargs.get("metadata") or {}
    if existing:
      existing.update(kwargs)
      existing["metadata_json"] = metadata
      existing["source_count"] = int(existing.get("source_count") or 0) + 1
      existing["confidence_score"] = min(0.99, float(existing.get("confidence_score") or 0.6) + 0.05)
      return existing
    row = {
      "id": f"pat-{len(self.platform_patterns) + 1}",
      "pattern_key": key,
      "source_count": 1,
      "confidence_score": 0.6,
      "metadata_json": metadata,
      **kwargs,
    }
    self.platform_patterns[key] = row
    return row

  def list_memory_platform_patterns(self, *, domain=None, module=None, pattern_type=None, limit=8):
    rows = list(self.platform_patterns.values())
    if domain:
      rows = [row for row in rows if row.get("domain") == domain]
    if module:
      rows = [row for row in rows if row.get("module") == module]
    if pattern_type:
      rows = [row for row in rows if row.get("pattern_type") == pattern_type]
    rows.sort(key=lambda row: (int(row.get("source_count") or 0), float(row.get("confidence_score") or 0)), reverse=True)
    return rows[:limit]

  def record_platform_pattern_event(self, **kwargs):
    row = {"id": f"event-{len(self.platform_events) + 1}", **kwargs}
    self.platform_events.append(row)
    return row


def _neon_correction_messages(chat_session_id: str) -> list[dict]:
  return [
    {
      "role": "user",
      "content": "write a code for neon number",
      "chat_session_id": chat_session_id,
    },
    {
      "role": "assistant",
      "content": "Here is a Python neon number solution using one function.",
      "chat_session_id": chat_session_id,
    },
    {
      "role": "user",
      "content": "no i want in java",
      "chat_session_id": chat_session_id,
    },
    {
      "role": "assistant",
      "content": "Here is the Java version.",
      "chat_session_id": chat_session_id,
    },
    {
      "role": "user",
      "content": "change the python code from single function to double function",
      "chat_session_id": chat_session_id,
    },
  ]


def _neon_two_function_without_language_messages(chat_session_id: str) -> list[dict]:
  return [
    {
      "role": "user",
      "content": "write a code for neon number",
      "chat_session_id": chat_session_id,
    },
    {
      "role": "assistant",
      "content": "Generated the requested standalone code file.",
      "chat_session_id": chat_session_id,
    },
    {
      "role": "user",
      "content": "write a code for neon number with 2 function",
      "chat_session_id": chat_session_id,
    },
  ]


def _armstrong_simplified_messages(chat_session_id: str) -> list[dict]:
  return [
    {
      "role": "user",
      "content": "write a code for armstrong number",
      "chat_session_id": chat_session_id,
    },
    {
      "role": "assistant",
      "content": "Generated the requested standalone code file.",
      "chat_session_id": chat_session_id,
    },
    {
      "role": "user",
      "content": "now i want simplyfied version of this code",
      "chat_session_id": chat_session_id,
    },
  ]


def _generic_update_messages(chat_session_id: str) -> list[dict]:
  return [
    {
      "role": "user",
      "content": "write a python code for palindrome number",
      "chat_session_id": chat_session_id,
    },
    {
      "role": "assistant",
      "content": "Generated the requested standalone code file.",
      "chat_session_id": chat_session_id,
    },
    {
      "role": "user",
      "content": "add input validation and show a clear invalid number message",
      "chat_session_id": chat_session_id,
    },
  ]


def _generation_messages(chat_session_id: str) -> list[dict]:
  return [
    {
      "role": "user",
      "content": "write a python code for perfect number",
      "chat_session_id": chat_session_id,
    },
  ]


def test_extracts_neon_number_two_function_correction() -> None:
  prefs = extract_correction_preferences(_neon_correction_messages("session-1"))

  assert len(prefs) == 1
  assert "explicitly asks for two functions" in prefs[0]["preference"]
  assert "preserve that structure" in prefs[0]["preference"]
  assert prefs[0]["metadata"]["topic"] == "neon_number"
  assert prefs[0]["metadata"]["language"] == "python"
  assert prefs[0]["metadata"]["function_count"] == 2


def test_turn_correction_infers_language_from_changed_python_path() -> None:
  store = _LearningStore()
  user = UserContext(id="user-1", email="u@example.com", role="user")
  store.messages = _neon_two_function_without_language_messages("session-1")

  result = persist_turn_correction_learning(
    store,
    user,
    project_id="project-1",
    chat_session_id="session-1",
    changed_paths=["neon_number.py"],
  )

  assert result["status"] == "stored"
  assert len(store.preferences) == 1
  assert "explicitly asks for two functions" in store.preferences[0]["preference"]
  assert store.preferences[0]["metadata_json"]["language"] == "python"
  assert store.preferences[0]["metadata_json"]["function_count"] == 2


def test_turn_correction_stores_simplified_code_requirement() -> None:
  store = _LearningStore()
  user = UserContext(id="user-1", email="u@example.com", role="user")
  store.messages = _armstrong_simplified_messages("session-1")

  result = persist_turn_correction_learning(
    store,
    user,
    project_id="project-1",
    chat_session_id="session-1",
    changed_paths=["armstrong_number.py"],
  )

  assert result["status"] == "stored"
  assert len(store.preferences) == 1
  assert store.preferences[0]["category"] == "code_simplicity"
  assert "explicitly asks for a simplified or beginner-friendly version" in store.preferences[0]["preference"]
  assert store.preferences[0]["metadata_json"]["correction_kind"] == "code_simplicity"
  assert store.preferences[0]["metadata_json"]["language"] == "python"
  assert store.preferences[0]["metadata_json"]["topic"] == "armstrong_number"


def test_turn_learning_stores_generic_update_without_keyword_gate() -> None:
  store = _LearningStore()
  user = UserContext(id="user-1", email="u@example.com", role="user")
  store.messages = _generic_update_messages("session-1")

  result = persist_turn_learning(
    store,
    user,
    project_id="project-1",
    chat_session_id="session-1",
    changed_paths=["palindrome_number.py"],
  )

  assert result["status"] == "stored"
  assert len(store.preferences) == 1
  assert store.preferences[0]["category"] == "code_quality"
  assert "input validation" in store.preferences[0]["preference"]
  assert "explicitly asks" in store.preferences[0]["preference"]
  assert store.preferences[0]["metadata_json"]["source"] == "turn_learning"
  assert store.preferences[0]["metadata_json"]["correction_kind"] == "input_validation"


def test_turn_learning_stores_generation_prompt_without_changed_paths() -> None:
  store = _LearningStore()
  user = UserContext(id="user-1", email="u@example.com", role="user")
  store.messages = _generation_messages("session-1")

  result = persist_turn_learning(
    store,
    user,
    project_id="project-1",
    chat_session_id="session-1",
    outcome="completed",
  )

  assert result["status"] == "skipped"
  assert result["reason"] == "no_turn_learning"
  assert store.preferences == []


def test_turn_learning_stores_error_correction_turn() -> None:
  store = _LearningStore()
  user = UserContext(id="user-1", email="u@example.com", role="user")
  store.messages = _generic_update_messages("session-1")

  result = persist_turn_learning(
    store,
    user,
    project_id="project-1",
    chat_session_id="session-1",
    changed_paths=["palindrome_number.py"],
    outcome="failed",
    error_category="syntax_error",
  )

  assert result["status"] == "stored"
  assert store.preferences[0]["metadata_json"]["error_category"] == "syntax_error"
  assert store.preferences[0]["metadata_json"]["outcome"] == "failed"


def test_simplified_code_requirement_is_available_in_fresh_chat_context() -> None:
  store = _LearningStore()
  user = UserContext(id="user-1", email="u@example.com", role="user")
  store.messages = _armstrong_simplified_messages("session-1")

  persist_turn_correction_learning(
    store,
    user,
    project_id="project-1",
    chat_session_id="session-1",
    changed_paths=["armstrong_number.py"],
  )

  block = build_unified_memory_context_block(
    store,
    user,
    project_id="project-2",
    prompt="write a python code for armstrong number",
    chat_session_id="session-2",
    ideology_only=True,
  )

  assert "simplified or beginner-friendly" not in block
  assert "Greenfield project" in block


def test_turn_correction_is_available_in_fresh_chat_context() -> None:
  store = _LearningStore()
  user = UserContext(id="user-1", email="u@example.com", role="user")
  store.messages = _neon_correction_messages("session-1")

  result = persist_turn_correction_learning(
    store,
    user,
    project_id="project-1",
    chat_session_id="session-1",
  )

  assert result["status"] == "stored"
  assert len(store.preferences) == 1

  python_block = build_unified_memory_context_block(
    store,
    user,
    project_id="project-2",
    prompt="write a python code in neon number",
    chat_session_id="session-2",
    ideology_only=True,
  )
  explicit_python_block = build_unified_memory_context_block(
    store,
    user,
    project_id="project-2",
    prompt="write a python code in neon number with 2 functions",
    chat_session_id="session-2",
    ideology_only=True,
  )
  java_block = build_unified_memory_context_block(
    store,
    user,
    project_id="project-2",
    prompt="write a java code in neon number",
    chat_session_id="session-2",
    ideology_only=True,
  )

  assert "explicitly asks for two functions" not in python_block
  assert "Greenfield project" in python_block
  assert "explicitly asks for two functions" in explicit_python_block
  assert "explicitly asks for two functions" not in java_block


def test_platform_correction_is_soft_after_first_user_and_strengthens_after_second() -> None:
  store = _LearningStore()
  first_user = UserContext(id="user-1", email="one@example.com", role="user")
  second_user = UserContext(id="user-2", email="two@example.com", role="user")
  store.messages = _neon_correction_messages("session-1")

  persist_turn_correction_learning(
    store,
    first_user,
    project_id="project-1",
    chat_session_id="session-1",
  )
  one_user_block = build_platform_correction_context_block(
    store,
    prompt="write python code for neon number with 2 functions",
    min_source_count=2,
  )

  persist_turn_correction_learning(
    store,
    first_user,
    project_id="project-1",
    chat_session_id="session-1",
  )
  still_one_user_block = build_platform_correction_context_block(
    store,
    prompt="write python code for neon number with 2 functions",
    min_source_count=2,
  )

  store.messages = _neon_correction_messages("session-2")
  persist_turn_correction_learning(
    store,
    second_user,
    project_id="project-2",
    chat_session_id="session-2",
  )
  two_user_block = build_platform_correction_context_block(
    store,
    prompt="write python code for neon number with 2 functions",
    min_source_count=2,
  )

  assert "soft platform lesson" in one_user_block
  assert "explicitly asks for two functions" in one_user_block
  assert "soft platform lesson" in still_one_user_block
  assert "explicitly asks for two functions" in two_user_block
  assert "single-function" in two_user_block
  assert "recommended platform pattern" in two_user_block
