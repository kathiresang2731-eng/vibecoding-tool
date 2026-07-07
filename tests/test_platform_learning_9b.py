import os
from unittest.mock import patch

from backend.agents.memory.context import build_platform_learning_context_block
from backend.agents.memory.platform_learning import (
  is_platform_learnable_run,
  maybe_promote_episode_to_platform_pattern,
  select_platform_patterns_for_prompt,
)
from backend.agents.memory.platform_patterns_api import list_platform_memory_patterns_payload
from backend.agents.memory.session_extraction import _extract_session_episode, extract_closed_session_memories
from backend.agents.memory.session_monitor import persist_generation_memory_checkpoint
from backend.agents.runtime_config import platform_pattern_min_source_count
from backend.storage import UserContext


class _PlatformStore:
  def __init__(self):
    self.projects = {"project-1": {"id": "project-1", "name": "CRM Demo"}}
    self.platform_patterns: dict[str, dict] = {}
    self.platform_events: list[dict] = []
    self.episodes: list[dict] = []
    self.session_states: dict[str, dict] = {}
    self.snapshots: list[dict] = []
    self.profiles: list[dict] = []
    self.messages: list[dict] = []
    self.preferences: list[dict] = []

  def get_project(self, project_id, user):
    return self.projects.get(project_id)

  def upsert_memory_user_profile(self, user, *, project_id, profile):
    row = {"id": "profile-1", "profile_json": profile}
    self.profiles.append(row)
    return row

  def get_memory_chat_session_state(self, user, *, chat_session_id):
    return self.session_states.get(chat_session_id)

  def insert_memory_session_snapshot(self, user, **kwargs):
    row = {"id": f"snap-{len(self.snapshots) + 1}", **kwargs}
    self.snapshots.append(row)
    return row

  def upsert_memory_chat_session_state(self, user, *, chat_session_id, rolling_summary, **kwargs):
    existing = self.session_states.get(chat_session_id)
    row = {
      "chat_session_id": chat_session_id,
      "rolling_summary": rolling_summary,
      "update_count": int((existing or {}).get("update_count") or 0) + 1,
      **kwargs,
    }
    self.session_states[chat_session_id] = row
    return row

  def insert_memory_episode(self, user, **kwargs):
    row = {"id": f"ep-{len(self.episodes) + 1}", **kwargs}
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

  def find_memory_episode_by_run_id(self, user, *, project_id, chat_session_id, generation_run_id):
    for row in reversed(self.episodes):
      if (
        row.get("project_id") == project_id
        and row.get("chat_session_id") == chat_session_id
        and row.get("generation_run_id") == generation_run_id
      ):
        return row
    return None

  def prune_memory_episodes(self, user, *, project_id, chat_session_id, keep=20):
    return 0

  def upsert_memory_platform_pattern(self, **kwargs):
    from backend.storage.memory_framework import build_platform_pattern_key

    key = build_platform_pattern_key(
      domain=kwargs.get("domain", "general"),
      module=kwargs.get("module", "general"),
      pattern_type=kwargs.get("pattern_type", "fix_pattern"),
      title=kwargs.get("title", "pattern"),
    )
    existing = self.platform_patterns.get(key)
    if existing:
      existing["source_count"] = int(existing.get("source_count") or 0) + 1
      existing["confidence_score"] = min(0.99, float(existing.get("confidence_score") or 0.6) + 0.05)
      return existing
    row = {
      "id": f"pat-{len(self.platform_patterns) + 1}",
      "pattern_key": key,
      "source_count": 1,
      "confidence_score": 0.6,
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
    rows.sort(key=lambda row: (float(row.get("confidence_score") or 0), int(row.get("source_count") or 0)), reverse=True)
    return rows[:limit]

  def record_platform_pattern_event(self, **kwargs):
    row = {"id": f"evt-{len(self.platform_events) + 1}", **kwargs}
    self.platform_events.append(row)
    return row

  def list_project_chat_messages(self, project_id, user, *, limit=200, chat_session_id=None):
    rows = [row for row in self.messages if row.get("chat_session_id") == chat_session_id]
    return rows[:limit]


def test_platform_pattern_min_source_count_defaults_to_two():
  with patch.dict(os.environ, {}, clear=False):
    os.environ.pop("PLATFORM_PATTERN_MIN_SOURCE_COUNT", None)
    assert platform_pattern_min_source_count() == 2


def test_platform_pattern_min_source_count_reads_env():
  with patch.dict(os.environ, {"PLATFORM_PATTERN_MIN_SOURCE_COUNT": "1"}, clear=False):
    assert platform_pattern_min_source_count() == 1


def test_failed_fix_pattern_run_is_platform_learnable():
  assert is_platform_learnable_run(
    memory_type="fix_pattern",
    intent="website_update",
    outcome="failed",
    error_category="syntax_error",
    changed_paths=["src/App.jsx"],
    preview_status="failed",
  )


def test_failed_run_learning_respects_feature_flag():
  with patch.dict(os.environ, {"ENABLE_PLATFORM_FAILED_RUN_LEARNING": "false"}, clear=False):
    assert not is_platform_learnable_run(
      memory_type="fix_pattern",
      intent="website_update",
      outcome="failed",
      error_category="syntax_error",
      changed_paths=["src/App.jsx"],
      preview_status="failed",
    )


def test_persist_checkpoint_promotes_failed_fix_pattern():
  store = _PlatformStore()
  user = UserContext(id="user-1", email="u@example.com", role="user")
  result = persist_generation_memory_checkpoint(
    store,
    user,
    project_id="project-1",
    chat_session_id="session-1",
    generation_run_id="run-failed",
    prompt="Fix syntax error in navbar component",
    intent="website_update",
    outcome="failed",
    changed_paths=["src/App.jsx"],
    preview_status="failed",
    error_category="syntax_error",
    project_name="CRM Demo",
  )
  assert result["status"] == "stored"
  assert result.get("platform_pattern_id") is not None


def test_select_platform_patterns_uses_configurable_threshold():
  store = _PlatformStore()
  episode = {
    "memory_type": "workflow",
    "title": "workflow · leads · website_generation",
    "searchable_summary": "Build CRM leads page",
    "situation": "Domain=crm",
    "improved_behavior": "Use parallel workers",
    "avoid": "",
    "outcome": "completed",
  }
  maybe_promote_episode_to_platform_pattern(
    store,
    episode=episode,
    domain="crm",
    modules=["leads"],
    intent="website_generation",
    changed_paths=["src/pages/Leads.jsx"],
    preview_status="ready",
  )
  with patch.dict(os.environ, {"PLATFORM_PATTERN_MIN_SOURCE_COUNT": "1"}, clear=False):
    selected = select_platform_patterns_for_prompt(store, prompt="build crm leads page", domain="crm", modules=["leads"])
  assert len(selected) == 1


def test_build_platform_learning_context_injects_first_source_as_soft_guidance():
  store = _PlatformStore()
  episode = {
    "memory_type": "workflow",
    "title": "workflow · leads · website_generation",
    "searchable_summary": "Build CRM leads page",
    "situation": "Domain=crm",
    "improved_behavior": "Use parallel workers",
    "avoid": "",
    "outcome": "completed",
  }
  maybe_promote_episode_to_platform_pattern(
    store,
    episode=episode,
    domain="crm",
    modules=["leads"],
    intent="website_generation",
    changed_paths=["src/pages/Leads.jsx"],
    preview_status="ready",
  )
  with patch.dict(os.environ, {"PLATFORM_PATTERN_MIN_SOURCE_COUNT": "2"}, clear=False):
    block_low = build_platform_learning_context_block(store, prompt="build crm leads page", domain="crm", modules=["leads"])
  assert "soft platform lesson" in block_low
  assert "Use parallel workers" in block_low
  with patch.dict(os.environ, {"PLATFORM_PATTERN_MIN_SOURCE_COUNT": "1"}, clear=False):
    block_high = build_platform_learning_context_block(store, prompt="build crm leads page", domain="crm", modules=["leads"])
  assert "Use parallel workers" in block_high


def test_list_platform_memory_patterns_payload():
  store = _PlatformStore()
  store.upsert_memory_platform_pattern(
    domain="crm",
    module="leads",
    pattern_type="fix_pattern",
    memory_type="fix_pattern",
    title="fix_pattern · crm/leads · syntax_error",
    summary="Pattern type: fix_pattern",
    situation="Domain=crm",
    improved_behavior="Minimal syntax fix",
    avoid="Do not regenerate whole project",
    stack_tags="vite,react,tailwind",
    metadata={"anonymized": True},
  )
  payload = list_platform_memory_patterns_payload(store, domain="crm")
  assert payload["schema"] == "worktual.platform-memory-patterns.v1"
  assert payload["stats"]["listed"] == 1
  assert payload["learning_rules"]["min_source_count"] >= 1


def test_extract_session_episode_prefers_llm_when_available():
  messages = [
    {"role": "user", "content": "Build a CRM landing page with Tailwind"},
    {"role": "assistant", "content": "Done"},
  ]

  def _fake_llm(_messages, *, settings):
    return {
      "memory_type": "workflow",
      "title": "CRM landing workflow",
      "searchable_summary": "Use Tailwind sections for CRM landing pages",
      "improved_behavior": "Scaffold hero, features, and CTA first",
      "avoid": "Do not regenerate unrelated pages",
      "outcome": "completed",
      "metadata": {"source": "session_close_llm_extraction"},
    }

  with patch("backend.agents.memory.session_extraction._llm_extract_episode", _fake_llm):
    episode, source = _extract_session_episode(
      messages,
      project_id="project-1",
      chat_session_id="session-1",
      settings=object(),
      use_llm=True,
    )
  assert source == "llm"
  assert "Tailwind" in episode["searchable_summary"]


def test_extract_closed_session_memories_reports_episode_source():
  store = _PlatformStore()
  user = UserContext(id="user-1", email="u@example.com", role="user")
  store.messages = [
    {"role": "user", "content": "Build a CRM with vitest tests", "chat_session_id": "session-1"},
    {"role": "assistant", "content": "Done", "chat_session_id": "session-1"},
    {"role": "user", "content": "Use tailwind and keep explanations concise", "chat_session_id": "session-1"},
  ]
  result = extract_closed_session_memories(
    store,
    user,
    project_id="project-1",
    chat_session_id="session-1",
    settings=None,
    use_llm=False,
  )
  assert result["status"] == "completed"
  assert result["episode_source"] == "heuristic"
