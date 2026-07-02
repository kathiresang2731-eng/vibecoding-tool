from backend.agents.chat_history import build_compact_chat_continuity_block
from backend.agents.memory.context import build_agent_flow_memory_block, build_unified_memory_context_block
from backend.agents.memory.platform_learning import (
  build_anonymized_platform_summary,
  is_platform_learnable_run,
  maybe_promote_episode_to_platform_pattern,
  select_platform_patterns_for_prompt,
)
from backend.agents.memory.session_monitor import (
  build_episode_from_run,
  infer_domain,
  infer_modules,
  persist_generation_memory_checkpoint,
)
from backend.storage import UserContext


class _MemoryFrameworkStore:
  def __init__(self):
    self.profiles: list[dict] = []
    self.episodes: list[dict] = []
    self.snapshots: list[dict] = []
    self.session_states: dict[str, dict] = {}
    self.platform_patterns: dict[str, dict] = {}
    self.platform_events: list[dict] = []
    self.learning_events: list[dict] = []
    self.items: list[dict] = []
    self.preferences: list[dict] = []
    self.messages: list[dict] = []

  def upsert_memory_user_profile(self, user, *, project_id, profile):
    row = {"id": "profile-1", "user_id": user.id, "project_id": project_id or "", "profile_json": profile}
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
    update_count = int((existing or {}).get("update_count") or 0) + 1
    row = {
      "chat_session_id": chat_session_id,
      "rolling_summary": rolling_summary,
      "update_count": update_count,
      **kwargs,
    }
    self.session_states[chat_session_id] = row
    return row

  def insert_memory_episode(self, user, **kwargs):
    row = {"id": f"ep-{len(self.episodes) + 1}", **kwargs}
    self.episodes.append(row)
    return row

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
    scoped = [
      row
      for row in self.episodes
      if row.get("project_id") == project_id and row.get("chat_session_id") == chat_session_id
    ]
    if len(scoped) <= keep:
      return 0
    keep_ids = {row["id"] for row in scoped[-keep:]}
    before = len(self.episodes)
    self.episodes = [
      row
      for row in self.episodes
      if not (
        row.get("project_id") == project_id
        and row.get("chat_session_id") == chat_session_id
        and row["id"] not in keep_ids
      )
    ]
    return before - len(self.episodes)

  def list_memory_episodes(self, user, *, project_id=None, chat_session_id=None, scope=None, limit=12):
    rows = list(self.episodes)
    if project_id:
      rows = [row for row in rows if row.get("project_id") == project_id]
    if chat_session_id:
      rows = [row for row in rows if row.get("chat_session_id") == chat_session_id]
    if scope:
      rows = [row for row in rows if row.get("scope") == scope]
    return rows[:limit]

  def upsert_memory_platform_pattern(self, **kwargs):
    from backend.storage.memory_framework import build_platform_pattern_key

    key = build_platform_pattern_key(
      domain=kwargs.get("domain", "general"),
      module=kwargs.get("module", "general"),
      pattern_type=kwargs.get("pattern_type", "fix_pattern"),
      title=kwargs.get("title", "pattern"),
    )
    existing = self.platform_patterns.get(key)
    metadata = kwargs.get("metadata") or {}
    if existing:
      existing["source_count"] = int(existing.get("source_count") or 0) + 1
      existing["confidence_score"] = min(0.99, float(existing.get("confidence_score") or 0.6) + 0.05)
      existing.update(kwargs)
      existing["metadata_json"] = metadata
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
    rows.sort(key=lambda row: (float(row.get("confidence_score") or 0), int(row.get("source_count") or 0)), reverse=True)
    return rows[:limit]

  def record_platform_pattern_event(self, **kwargs):
    row = {"id": f"evt-{len(self.platform_events) + 1}", **kwargs}
    self.platform_events.append(row)
    return row

  def record_memory_learning_event(self, user, **kwargs):
    run_id = kwargs.get("run_id")
    if run_id:
      existing = next(
        (
          row
          for row in self.learning_events
          if row.get("user_id") == user.id
          and row.get("project_id") == kwargs.get("project_id")
          and row.get("run_id") == run_id
        ),
        None,
      )
      if existing:
        return {**existing, "_created": False}
    row = {
      "id": f"learn-{len(self.learning_events) + 1}",
      "user_id": user.id,
      "metadata_json": kwargs.pop("metadata", {}),
      "changed_paths_json": kwargs.pop("changed_paths", []),
      "_created": True,
      **kwargs,
    }
    self.learning_events.append(row)
    return row

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
    rows = list(self.learning_events)
    if not include_all_users:
      rows = [row for row in rows if row.get("user_id") == user.id]
    if project_id:
      rows = [row for row in rows if row.get("project_id") == project_id]
    if chat_session_id:
      rows = [row for row in rows if row.get("chat_session_id") == chat_session_id]
    if run_id:
      rows = [row for row in rows if row.get("run_id") == run_id]
    if scope:
      rows = [row for row in rows if row.get("scope") == scope]
    return rows[:limit]

  def upsert_memory_item(self, user, *, project_id, namespace, key, kind, content, metadata=None):
    row = {
      "id": f"mem-{len(self.items) + 1}",
      "project_id": project_id,
      "namespace": namespace,
      "key": key,
      "kind": kind,
      "content": content,
      "metadata_json": metadata or {},
    }
    self.items.append(row)
    return row

  def list_memory_preferences(self, user, *, limit=50):
    return getattr(self, "preferences", [])[:limit]

  def upsert_memory_preference(self, user, *, category, preference, polarity="positive", confidence=0.8, durability="long_term", reason="", metadata=None):
    if not hasattr(self, "preferences"):
      self.preferences = []
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

  def list_project_chat_messages(self, project_id, user, *, limit=200, chat_session_id=None):
    rows = [row for row in self.messages if row.get("chat_session_id") == chat_session_id]
    return rows[:limit]

  def delete_memory_preference(self, user, *, preference_id):
    before = len(self.preferences)
    self.preferences = [item for item in self.preferences if item.get("id") != preference_id]
    return len(self.preferences) < before

  def list_memory_items(self, user, *, project_id=None, namespace=None, kind=None, limit=12):
    rows = [
      item
      for item in self.items
      if item.get("namespace") == namespace and item.get("project_id") == project_id
    ]
    if kind:
      rows = [item for item in rows if item.get("kind") == kind]
    return rows[:limit]

  def prune_memory_items(self, user, *, project_id, namespace, kind, keep):
    return 0


def test_infer_domain_and_modules_from_crm_prompt():
  domain = infer_domain(prompt="Build a CRM with leads and contacts pipeline", project_name="Sales CRM")
  modules = infer_modules(prompt="Update leads page navbar", changed_paths=["src/pages/Leads.jsx"])
  assert domain == "crm"
  assert "leads" in modules


def test_build_episode_from_run_classifies_fix_pattern():
  episode = build_episode_from_run(
    prompt="Fix build error in Leads.jsx",
    intent="website_update",
    outcome="completed",
    changed_paths=["src/pages/Leads.jsx"],
    preview_status="failed",
    error_category="syntax_error",
    domain="crm",
    modules=["leads"],
  )
  assert episode["memory_type"] == "fix_pattern"
  assert episode["improved_behavior"]
  assert "Intent: website_update" in episode["searchable_summary"]
  assert "syntax_error" in episode["searchable_summary"]


def test_persist_generation_memory_checkpoint_updates_session_state():
  store = _MemoryFrameworkStore()
  user = UserContext(id="user-1", email="u@example.com", role="user")
  result = persist_generation_memory_checkpoint(
    store,
    user,
    project_id="project-1",
    chat_session_id="session-1",
    generation_run_id="run-1",
    prompt="Update leads dashboard spacing",
    intent="website_update",
    outcome="completed",
    project_name="CRM Demo",
    changed_paths=["src/pages/Leads.jsx"],
    preview_status="ready",
  )
  assert result["status"] == "stored"
  assert store.session_states["session-1"]["update_count"] == 1
  assert len(store.snapshots) == 1
  assert len(store.episodes) == 1
  assert result["domain"] == "crm"
  assert result["learning_event"]["status"] == "stored"
  assert len(store.learning_events) == 1

  second = persist_generation_memory_checkpoint(
    store,
    user,
    project_id="project-1",
    chat_session_id="session-1",
    generation_run_id="run-2",
    prompt="Fix navbar on leads page",
    intent="website_update",
    outcome="completed",
    changed_paths=["src/pages/Leads.jsx"],
    error_category="syntax_error",
    preview_status="failed",
  )
  assert second["status"] == "stored"
  assert store.session_states["session-1"]["update_count"] == 2
  assert "Previous session context" in store.session_states["session-1"]["rolling_summary"]


def test_persist_generation_memory_checkpoint_runs_turn_learning_for_error_turn():
  store = _MemoryFrameworkStore()
  user = UserContext(id="user-1", email="u@example.com", role="user")
  store.messages = [
    {
      "role": "user",
      "content": "write a python code for prime number",
      "chat_session_id": "session-1",
    },
    {
      "role": "user",
      "content": "fix the syntax error and keep the validation clear",
      "chat_session_id": "session-1",
    },
  ]

  result = persist_generation_memory_checkpoint(
    store,
    user,
    project_id="project-1",
    chat_session_id="session-1",
    generation_run_id="run-1",
    prompt="fix the syntax error and keep the validation clear",
    intent="website_update",
    outcome="failed",
    project_name="Code Demo",
    changed_paths=["prime_number.py"],
    preview_status="failed",
    error_category="syntax_error",
  )

  assert result["turn_learning"]["status"] == "stored"
  assert result["correction_learning"] == result["turn_learning"]
  assert len(store.preferences) == 1
  assert store.preferences[0]["metadata_json"]["error_category"] == "syntax_error"
  assert result["learning_event"]["scope"] == "blocked_pattern"


def test_first_validated_crm_generation_creates_soft_platform_blueprint():
  store = _MemoryFrameworkStore()
  user = UserContext(id="user-1", email="u@example.com", role="user")

  result = persist_generation_memory_checkpoint(
    store,
    user,
    project_id="project-1",
    chat_session_id="session-1",
    generation_run_id="run-crm-1",
    prompt=(
      "Generate a CRM website with auth, onboarding, dashboard, leads, contacts, "
      "deals, sales, projects, products, AI chat, settings, and profile."
    ),
    intent="website_generation",
    outcome="completed",
    project_name="CRM",
    changed_paths=["src/App.jsx", "src/pages/Auth.jsx", "src/pages/Dashboard.jsx"],
    preview_status="ready",
  )

  assert result["learning_event"]["status"] == "stored"
  assert result["learning_event"]["scope"] == "soft_platform"
  event = store.learning_events[-1]
  assert event["domain"] == "crm"
  assert event["task_type"] == "full_generation"
  assert "Avoid single static dashboard pages" in event["extracted_lesson"]
  learned_patterns = [
    row
    for row in store.platform_patterns.values()
    if row.get("pattern_type") == "generation_blueprint"
  ]
  assert len(learned_patterns) == 1
  assert learned_patterns[0]["metadata_json"]["promotion_status"] == "soft_platform_lesson"


def test_second_crm_user_receives_first_validated_soft_blueprint():
  store = _MemoryFrameworkStore()
  first_user = UserContext(id="user-1", email="one@example.com", role="user")
  second_user = UserContext(id="user-2", email="two@example.com", role="user")
  persist_generation_memory_checkpoint(
    store,
    first_user,
    project_id="project-1",
    chat_session_id="session-1",
    generation_run_id="run-crm-1",
    prompt=(
      "Generate a CRM website with auth, onboarding, dashboard, leads, contacts, "
      "deals, sales, projects, products, AI chat, settings, and profile."
    ),
    intent="website_generation",
    outcome="completed",
    project_name="CRM",
    changed_paths=["src/App.jsx", "src/pages/Auth.jsx", "src/pages/Dashboard.jsx"],
    preview_status="ready",
  )

  block = build_unified_memory_context_block(
    store,
    second_user,
    project_id="project-2",
    prompt="Generate a CRM website with auth, onboarding, dashboard, and sales modules.",
    chat_session_id="session-2",
    project_name="CRM",
    files=[],
    ideology_only=True,
  )

  assert "soft platform lesson" in block
  assert "route-backed Auth, Onboarding, Dashboard" in block
  assert "Avoid single static dashboard pages" in block


def test_greeting_checkpoint_skips_episode_but_keeps_session_state():
  store = _MemoryFrameworkStore()
  user = UserContext(id="user-1", email="u@example.com", role="user")
  result = persist_generation_memory_checkpoint(
    store,
    user,
    project_id="project-1",
    chat_session_id="session-1",
    generation_run_id="run-greet",
    prompt="hello",
    intent="greeting",
    outcome="completed",
    project_name="Demo",
  )
  assert result["status"] == "stored"
  assert result["episode_status"] == "skipped"
  assert result["episode_id"] is None
  assert len(store.episodes) == 0
  assert store.session_states["session-1"]["update_count"] == 1


def test_duplicate_generation_run_does_not_insert_second_episode():
  store = _MemoryFrameworkStore()
  user = UserContext(id="user-1", email="u@example.com", role="user")
  first = persist_generation_memory_checkpoint(
    store,
    user,
    project_id="project-1",
    chat_session_id="session-1",
    generation_run_id="run-1",
    prompt="Update navbar spacing",
    intent="website_update",
    outcome="completed",
    changed_paths=["src/App.jsx"],
    preview_status="ready",
  )
  second = persist_generation_memory_checkpoint(
    store,
    user,
    project_id="project-1",
    chat_session_id="session-1",
    generation_run_id="run-1",
    prompt="Update navbar spacing",
    intent="website_update",
    outcome="completed",
    changed_paths=["src/App.jsx"],
    preview_status="ready",
  )
  assert first["episode_status"] == "stored"
  assert second["episode_status"] == "existing"
  assert first["learning_event"]["status"] == "stored"
  assert second["learning_event"]["status"] == "existing"
  assert len(store.episodes) == 1
  assert len(store.learning_events) == 1


def test_prune_episodic_memories_trims_structured_episodes():
  from backend.agents.memory.episodic import prune_episodic_memories

  store = _MemoryFrameworkStore()
  user = UserContext(id="user-1", email="u@example.com", role="user")
  for index in range(25):
    store.insert_memory_episode(
      user,
      project_id="project-1",
      chat_session_id="session-1",
      generation_run_id=f"run-{index}",
      scope="personal",
      memory_type="update_checkpoint",
      title=f"run {index}",
      searchable_summary=f"Intent: website_update\nUser request: update {index}",
      outcome="completed",
    )
  pruned = prune_episodic_memories(
    store,
    user,
    project_id="project-1",
    chat_session_id="session-1",
  )
  assert pruned == 5
  assert len(store.episodes) == 20


def test_platform_pattern_promotion_increments_source_count():
  store = _MemoryFrameworkStore()
  episode = {
    "memory_type": "fix_pattern",
    "title": "fix_pattern · leads · website_update",
    "searchable_summary": "User said fix navbar",
    "situation": "Domain=crm",
    "improved_behavior": "Minimal syntax fix",
    "avoid": "Do not regenerate whole project",
    "outcome": "completed",
  }
  first = maybe_promote_episode_to_platform_pattern(
    store,
    episode=episode,
    domain="crm",
    modules=["leads"],
    intent="website_update",
    error_category="syntax_error",
    changed_paths=["src/pages/Leads.jsx"],
    preview_status="failed",
  )
  second = maybe_promote_episode_to_platform_pattern(
    store,
    episode=episode,
    domain="crm",
    modules=["leads"],
    intent="website_update",
    error_category="syntax_error",
    changed_paths=["src/pages/Leads.jsx"],
    preview_status="failed",
  )
  assert first is not None
  assert second is not None
  assert int(second.get("source_count") or 0) >= 2
  assert "User said" not in str(first.get("summary") or "")
  assert "syntax_error" in str(first.get("summary") or "")
  assert "Leads.jsx" not in str(first.get("summary") or "")


def test_platform_learning_skips_conversation_and_chat_only_runs():
  assert not is_platform_learnable_run(
    memory_type="update_checkpoint",
    intent="greeting",
    outcome="completed",
    error_category=None,
    changed_paths=None,
    preview_status=None,
  )
  assert not is_platform_learnable_run(
    memory_type="workflow",
    intent="website_generation",
    outcome="completed",
    error_category=None,
    changed_paths=["src/App.jsx"],
    preview_status="failed",
  )
  assert is_platform_learnable_run(
    memory_type="fix_pattern",
    intent="website_update",
    outcome="completed",
    error_category="syntax_error",
    changed_paths=["src/pages/Leads.jsx"],
    preview_status="failed",
  )
  summary = build_anonymized_platform_summary(
    memory_type="fix_pattern",
    domain="crm",
    modules=["leads"],
    outcome="completed",
    error_category="syntax_error",
    changed_paths=["src/pages/Leads.jsx"],
  )
  assert "syntax_error" in summary
  assert "Affected paths" not in summary
  assert "User request" not in summary


def test_session_memory_does_not_leak_across_chat_sessions():
  store = _MemoryFrameworkStore()
  user = UserContext(id="user-1", email="u@example.com", role="user")
  persist_generation_memory_checkpoint(
    store,
    user,
    project_id="project-1",
    chat_session_id="session-a",
    generation_run_id="run-1",
    prompt="Update leads page in session A",
    intent="website_update",
    outcome="completed",
    changed_paths=["src/pages/Leads.jsx"],
  )
  persist_generation_memory_checkpoint(
    store,
    user,
    project_id="project-1",
    chat_session_id="session-b",
    generation_run_id="run-2",
    prompt="Update contacts page in session B",
    intent="website_update",
    outcome="completed",
    changed_paths=["src/pages/Contacts.jsx"],
  )
  block_a = build_unified_memory_context_block(
    store,
    user,
    project_id="project-1",
    prompt="continue leads work",
    chat_session_id="session-a",
  )
  block_b = build_unified_memory_context_block(
    store,
    user,
    project_id="project-1",
    prompt="continue contacts work",
    chat_session_id="session-b",
  )
  assert "session A" in block_a or "Leads.jsx" in block_a
  assert "session B" not in block_a
  assert "Contacts.jsx" not in block_a or "session A" in block_a
  assert "session B" in block_b or "Contacts.jsx" in block_b
  assert "session A" not in block_b


def test_unified_memory_context_includes_session_and_platform_blocks():
  store = _MemoryFrameworkStore()
  user = UserContext(id="user-1", email="u@example.com", role="user")
  persist_generation_memory_checkpoint(
    store,
    user,
    project_id="project-1",
    chat_session_id="session-1",
    generation_run_id="run-1",
    prompt="Build CRM leads page",
    intent="website_generation",
    outcome="completed",
    changed_paths=["src/pages/Leads.jsx"],
  )
  maybe_promote_episode_to_platform_pattern(
    store,
    episode=store.episodes[-1],
    domain="crm",
    modules=["leads"],
    intent="website_generation",
    changed_paths=["src/pages/Leads.jsx"],
    preview_status="ready",
  )
  maybe_promote_episode_to_platform_pattern(
    store,
    episode=store.episodes[-1],
    domain="crm",
    modules=["leads"],
    intent="website_generation",
    changed_paths=["src/pages/Leads.jsx"],
    preview_status="ready",
  )
  block = build_unified_memory_context_block(
    store,
    user,
    project_id="project-1",
    prompt="update leads page",
    chat_session_id="session-1",
  )
  assert "Chat session continuity memory" in block
  assert len(store.episodes) == 1
  # After a single run, session rolling summary and episodic content overlap — dedup keeps tokens down.
  assert "Platform" in block or "Cross-project platform learning" in block


def test_unified_memory_context_includes_user_preferences():
  store = _MemoryFrameworkStore()
  store.preferences = [
    {
      "category": "style",
      "preference": "Prefer functional React components",
      "confidence": 0.9,
      "durability": "long_term",
      "polarity": "positive",
    }
  ]
  user = UserContext(id="user-1", email="u@example.com", role="user")
  store.session_states["session-1"] = {
    "chat_session_id": "session-1",
    "update_count": 1,
    "rolling_summary": "Built landing page",
  }
  block = build_unified_memory_context_block(
    store,
    user,
    project_id="project-1",
    prompt="update hero",
    chat_session_id="session-1",
  )
  assert "Learned user requirements" in block
  assert "functional React" in block


def test_compact_chat_continuity_block_includes_recent_turns_and_error_context():
  messages = [
    {"role": "user", "content": "Build a SaaS landing page"},
    {"role": "model", "content": "Generated the landing page with hero and pricing."},
    {"role": "user", "content": "Fix the header alignment only"},
  ]
  block = build_compact_chat_continuity_block(
    messages,
    error_context="TypeError: Cannot read properties of undefined",
  )
  assert "CONVERSATION CONTINUITY" in block
  assert "header alignment" in block
  assert "TypeError" in block


def test_agent_flow_memory_block_merges_unified_and_chat_continuity():
  store = _MemoryFrameworkStore()
  user = UserContext(id="user-1", email="u@example.com", role="user")
  store.session_states["session-1"] = {
    "chat_session_id": "session-1",
    "update_count": 2,
    "rolling_summary": "User asked to tighten navbar spacing",
  }
  messages = [
    {"role": "user", "content": "Make navbar compact"},
    {"role": "model", "content": "Updated navbar padding."},
    {"role": "user", "content": "Also fix the hero title color"},
  ]
  block = build_agent_flow_memory_block(
    store,
    user,
    project_id="project-1",
    prompt="fix hero title color",
    chat_session_id="session-1",
    chat_messages=messages,
  )
  assert "Chat session continuity memory" in block
  assert "CONVERSATION CONTINUITY" in block
  assert "hero title color" in block
