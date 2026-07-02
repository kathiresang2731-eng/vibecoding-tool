from __future__ import annotations

import hashlib
import re
from typing import Any

from .errors import StorageError
from .ids import new_id
from .permissions import ensure_project_read, ensure_project_write, require_project
from .serialization import json_dumps_safe, serialize_row
from .user import UserContext

EPISODE_SCOPES = frozenset({"personal", "shared"})
EPISODE_MEMORY_TYPES = frozenset(
  {"workflow", "tool_pattern", "fix_pattern", "conversation_improvement", "update_checkpoint"}
)
SNAPSHOT_KINDS = frozenset({"update_checkpoint", "code_manifest", "error_recovery", "session_summary"})


def _slug(value: str) -> str:
  return re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-") or "general"


def build_platform_pattern_key(*, domain: str, module: str, pattern_type: str, title: str) -> str:
  raw = "|".join([_slug(domain), _slug(module), _slug(pattern_type), _slug(title)])
  return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


class MemoryFrameworkStoreMixin:
  def upsert_memory_user_profile(
    self,
    user: UserContext,
    *,
    project_id: str | None,
    profile: dict[str, Any],
  ) -> dict[str, Any]:
    if project_id:
      project = require_project(self, project_id, user)
      ensure_project_write(user, project)
    profile_json = json_dumps_safe(profile, context="memory.profile")
    framework = str(profile.get("framework") or "").strip()
    domain = str(profile.get("domain") or profile.get("project_type") or "").strip()
    normalized_project_id = project_id or ""
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          insert into memory_user_profiles (id, user_id, project_id, profile_json, framework, domain)
          values (%s, %s, %s, %s::jsonb, %s, %s)
          on conflict (user_id, project_id)
          do update set
            profile_json = excluded.profile_json,
            framework = excluded.framework,
            domain = excluded.domain,
            updated_at = now()
          returning id, user_id, project_id, profile_json, framework, domain, created_at, updated_at
          """,
          (
            new_id(),
            user.id,
            normalized_project_id,
            profile_json,
            framework,
            domain,
          ),
        )
        return serialize_row(cursor.fetchone())

  def get_memory_user_profile(
    self,
    user: UserContext,
    *,
    project_id: str | None = None,
  ) -> dict[str, Any] | None:
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          select id, user_id, project_id, profile_json, framework, domain, created_at, updated_at
          from memory_user_profiles
          where user_id = %s and project_id = %s
          limit 1
          """,
          (user.id, project_id or ""),
        )
        row = cursor.fetchone()
        return serialize_row(row) if row else None

  def upsert_memory_preference(
    self,
    user: UserContext,
    *,
    category: str,
    preference: str,
    polarity: str = "positive",
    confidence: float = 0.8,
    durability: str = "long_term",
    reason: str = "",
    metadata: dict[str, Any] | None = None,
  ) -> dict[str, Any]:
    normalized_category = category.strip()
    normalized_preference = preference.strip()
    if not normalized_category or not normalized_preference:
      raise StorageError("Preference category and preference text are required.")
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          insert into memory_user_preferences (
            id, user_id, category, preference, polarity, confidence, durability, reason, metadata_json
          )
          values (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
          on conflict (user_id, category, preference)
          do update set
            polarity = excluded.polarity,
            confidence = excluded.confidence,
            durability = excluded.durability,
            reason = excluded.reason,
            metadata_json = excluded.metadata_json,
            updated_at = now()
          returning id, user_id, category, preference, polarity, confidence, durability, reason,
            metadata_json, created_at, updated_at
          """,
          (
            new_id(),
            user.id,
            normalized_category,
            normalized_preference,
            polarity.strip() or "positive",
            float(confidence),
            durability.strip() or "long_term",
            reason.strip(),
            json_dumps_safe(metadata or {}, context="memory.preference"),
          ),
        )
        return serialize_row(cursor.fetchone())

  def list_memory_preferences(self, user: UserContext, *, limit: int = 50) -> list[dict[str, Any]]:
    safe_limit = max(1, min(limit, 100))
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          select id, user_id, category, preference, polarity, confidence, durability, reason,
            metadata_json, created_at, updated_at
          from memory_user_preferences
          where user_id = %s
          order by updated_at desc
          limit %s
          """,
          (user.id, safe_limit),
        )
        return [serialize_row(row) for row in cursor.fetchall()]

  def delete_memory_preference(self, user: UserContext, *, preference_id: str) -> bool:
    normalized_id = str(preference_id or "").strip()
    if not normalized_id:
      raise StorageError("Preference id is required.")
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          delete from memory_user_preferences
          where user_id = %s and id = %s
          returning id
          """,
          (user.id, normalized_id),
        )
        return cursor.fetchone() is not None

  def insert_memory_episode(
    self,
    user: UserContext,
    *,
    project_id: str,
    chat_session_id: str | None,
    generation_run_id: str | None,
    scope: str,
    memory_type: str,
    title: str,
    searchable_summary: str,
    situation: str = "",
    stack_tags: str = "",
    module_tags: str = "",
    improved_behavior: str = "",
    avoid: str = "",
    outcome: str = "completed",
    changed_paths: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
  ) -> dict[str, Any]:
    project = require_project(self, project_id, user)
    ensure_project_write(user, project)
    normalized_scope = scope if scope in EPISODE_SCOPES else "personal"
    normalized_type = memory_type if memory_type in EPISODE_MEMORY_TYPES else "update_checkpoint"
    episode_id = new_id()
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          insert into memory_episodes (
            id, user_id, project_id, chat_session_id, generation_run_id, scope, memory_type,
            title, searchable_summary, situation, stack_tags, module_tags, improved_behavior, avoid,
            outcome, changed_paths_json, metadata_json
          )
          values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
          returning id, user_id, project_id, chat_session_id, generation_run_id, scope, memory_type,
            title, searchable_summary, situation, stack_tags, module_tags, improved_behavior, avoid,
            outcome, changed_paths_json, metadata_json, created_at, updated_at
          """,
          (
            episode_id,
            user.id,
            project_id,
            chat_session_id,
            generation_run_id,
            normalized_scope,
            normalized_type,
            title.strip()[:240],
            searchable_summary.strip()[:4000],
            situation.strip()[:2000],
            stack_tags.strip()[:500],
            module_tags.strip()[:500],
            improved_behavior.strip()[:2000],
            avoid.strip()[:2000],
            outcome.strip()[:64] or "completed",
            json_dumps_safe(list(changed_paths or [])[:24], context="memory.episode.paths"),
            json_dumps_safe(metadata or {}, context="memory.episode.metadata"),
          ),
        )
        row = serialize_row(cursor.fetchone())
    self.add_event(
      project_id,
      user.id,
      "memory.episode.created",
      {"episode_id": episode_id, "memory_type": normalized_type, "scope": normalized_scope},
    )
    return row

  def list_memory_episodes(
    self,
    user: UserContext,
    *,
    project_id: str | None = None,
    chat_session_id: str | None = None,
    scope: str | None = None,
    module_tag: str | None = None,
    limit: int = 12,
  ) -> list[dict[str, Any]]:
    if project_id:
      project = require_project(self, project_id, user)
      ensure_project_read(user, project)
    filters = ["user_id = %s"]
    params: list[Any] = [user.id]
    if project_id:
      filters.append("project_id = %s")
      params.append(project_id)
    if chat_session_id:
      filters.append("chat_session_id = %s")
      params.append(chat_session_id)
    if scope:
      filters.append("scope = %s")
      params.append(scope)
    if module_tag:
      filters.append("module_tags ilike %s")
      params.append(f"%{module_tag.strip()}%")
    safe_limit = max(1, min(limit, 50))
    params.append(safe_limit)
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          f"""
          select id, user_id, project_id, chat_session_id, generation_run_id, scope, memory_type,
            title, searchable_summary, situation, stack_tags, module_tags, improved_behavior, avoid,
            outcome, changed_paths_json, metadata_json, created_at, updated_at
          from memory_episodes
          where {' and '.join(filters)}
          order by created_at desc
          limit %s
          """,
          tuple(params),
        )
        return [serialize_row(row) for row in cursor.fetchall()]

  def find_memory_episode_by_run_id(
    self,
    user: UserContext,
    *,
    project_id: str,
    chat_session_id: str,
    generation_run_id: str,
  ) -> dict[str, Any] | None:
    if not generation_run_id:
      return None
    project = require_project(self, project_id, user)
    ensure_project_read(user, project)
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          select id, user_id, project_id, chat_session_id, generation_run_id, scope, memory_type,
            title, searchable_summary, situation, stack_tags, module_tags, improved_behavior, avoid,
            outcome, changed_paths_json, metadata_json, created_at, updated_at
          from memory_episodes
          where user_id = %s and project_id = %s and chat_session_id = %s and generation_run_id = %s
          order by created_at desc
          limit 1
          """,
          (user.id, project_id, chat_session_id, generation_run_id),
        )
        row = cursor.fetchone()
        return serialize_row(row) if row else None

  def prune_memory_episodes(
    self,
    user: UserContext,
    *,
    project_id: str,
    chat_session_id: str,
    keep: int = 20,
  ) -> int:
    project = require_project(self, project_id, user)
    ensure_project_write(user, project)
    safe_keep = max(1, min(int(keep), 50))
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          with ranked as (
            select id,
              row_number() over (order by created_at desc) as row_num
            from memory_episodes
            where user_id = %s and project_id = %s and chat_session_id = %s and scope = 'personal'
          )
          delete from memory_episodes
          where id in (select id from ranked where row_num > %s)
          returning id
          """,
          (user.id, project_id, chat_session_id, safe_keep),
        )
        return len(cursor.fetchall())

  def delete_memory_episode(
    self,
    user: UserContext,
    *,
    episode_id: str,
    project_id: str,
  ) -> bool:
    project = require_project(self, project_id, user)
    ensure_project_write(user, project)
    normalized_id = str(episode_id or "").strip()
    if not normalized_id:
      return False
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          delete from memory_episodes
          where id = %s and user_id = %s and project_id = %s
          returning id
          """,
          (normalized_id, user.id, project_id),
        )
        deleted = cursor.fetchone() is not None
    if deleted:
      self.add_event(
        project_id,
        user.id,
        "memory.episode.deleted",
        {"episode_id": normalized_id},
      )
    return deleted

  def insert_memory_session_snapshot(
    self,
    user: UserContext,
    *,
    project_id: str,
    chat_session_id: str,
    generation_run_id: str | None,
    snapshot_kind: str,
    content: str,
    changed_paths: list[str] | None = None,
    file_manifest: dict[str, Any] | None = None,
    preview_status: str | None = None,
    error_category: str | None = None,
    metadata: dict[str, Any] | None = None,
  ) -> dict[str, Any]:
    project = require_project(self, project_id, user)
    ensure_project_write(user, project)
    normalized_kind = snapshot_kind if snapshot_kind in SNAPSHOT_KINDS else "update_checkpoint"
    snapshot_id = new_id()
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          insert into memory_session_snapshots (
            id, project_id, user_id, chat_session_id, generation_run_id, snapshot_kind,
            content, changed_paths_json, file_manifest_json, preview_status, error_category, metadata_json
          )
          values (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s::jsonb)
          returning id, project_id, user_id, chat_session_id, generation_run_id, snapshot_kind,
            content, changed_paths_json, file_manifest_json, preview_status, error_category,
            metadata_json, created_at
          """,
          (
            snapshot_id,
            project_id,
            user.id,
            chat_session_id,
            generation_run_id,
            normalized_kind,
            content.strip()[:8000],
            json_dumps_safe(list(changed_paths or [])[:32], context="memory.snapshot.paths"),
            json_dumps_safe(file_manifest or {}, context="memory.snapshot.manifest"),
            preview_status,
            error_category,
            json_dumps_safe(metadata or {}, context="memory.snapshot.metadata"),
          ),
        )
        return serialize_row(cursor.fetchone())

  def list_memory_session_snapshots(
    self,
    user: UserContext,
    *,
    project_id: str,
    chat_session_id: str,
    limit: int = 20,
  ) -> list[dict[str, Any]]:
    project = require_project(self, project_id, user)
    ensure_project_read(user, project)
    safe_limit = max(1, min(limit, 50))
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          select id, project_id, user_id, chat_session_id, generation_run_id, snapshot_kind,
            content, changed_paths_json, file_manifest_json, preview_status, error_category,
            metadata_json, created_at
          from memory_session_snapshots
          where project_id = %s and user_id = %s and chat_session_id = %s
          order by created_at desc
          limit %s
          """,
          (project_id, user.id, chat_session_id, safe_limit),
        )
        return [serialize_row(row) for row in cursor.fetchall()]

  def upsert_memory_chat_session_state(
    self,
    user: UserContext,
    *,
    project_id: str,
    chat_session_id: str,
    rolling_summary: str,
    changed_paths: list[str] | None = None,
    preview_status: str | None = None,
    error_category: str | None = None,
    file_count: int = 0,
    generation_run_id: str | None = None,
    metadata: dict[str, Any] | None = None,
  ) -> dict[str, Any]:
    project = require_project(self, project_id, user)
    ensure_project_write(user, project)
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          insert into memory_chat_session_state (
            chat_session_id, project_id, user_id, rolling_summary, last_changed_paths_json,
            last_preview_status, last_error_category, file_count, update_count,
            last_generation_run_id, metadata_json
          )
          values (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, 1, %s, %s::jsonb)
          on conflict (chat_session_id)
          do update set
            rolling_summary = excluded.rolling_summary,
            last_changed_paths_json = excluded.last_changed_paths_json,
            last_preview_status = excluded.last_preview_status,
            last_error_category = excluded.last_error_category,
            file_count = excluded.file_count,
            update_count = memory_chat_session_state.update_count + 1,
            last_generation_run_id = excluded.last_generation_run_id,
            metadata_json = excluded.metadata_json,
            updated_at = now()
          returning chat_session_id, project_id, user_id, rolling_summary, last_changed_paths_json,
            last_preview_status, last_error_category, file_count, update_count,
            last_generation_run_id, metadata_json, created_at, updated_at
          """,
          (
            chat_session_id,
            project_id,
            user.id,
            rolling_summary.strip()[:6000],
            json_dumps_safe(list(changed_paths or [])[:32], context="memory.session.paths"),
            preview_status,
            error_category,
            int(file_count),
            generation_run_id,
            json_dumps_safe(metadata or {}, context="memory.session.metadata"),
          ),
        )
        return serialize_row(cursor.fetchone())

  def get_memory_chat_session_state(
    self,
    user: UserContext,
    *,
    chat_session_id: str,
  ) -> dict[str, Any] | None:
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          select chat_session_id, project_id, user_id, rolling_summary, last_changed_paths_json,
            last_preview_status, last_error_category, file_count, update_count,
            last_generation_run_id, metadata_json, created_at, updated_at
          from memory_chat_session_state
          where chat_session_id = %s and user_id = %s
          limit 1
          """,
          (chat_session_id, user.id),
        )
        row = cursor.fetchone()
        return serialize_row(row) if row else None

  def record_memory_learning_event(
    self,
    user: UserContext,
    *,
    project_id: str | None,
    chat_session_id: str | None = None,
    run_id: str | None = None,
    request_text_hash: str = "",
    normalized_intent: str = "",
    domain: str = "general",
    task_type: str = "general",
    changed_paths: list[str] | None = None,
    validation_status: str = "",
    mistake_type: str = "",
    extracted_lesson: str = "",
    scope: str = "personal",
    confidence: float = 0.6,
    metadata: dict[str, Any] | None = None,
  ) -> dict[str, Any]:
    if project_id:
      project = require_project(self, project_id, user)
      ensure_project_write(user, project)
    event_id = new_id()
    safe_confidence = max(0.0, min(0.99, float(confidence or 0.6)))
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          insert into memory_learning_events (
            id, user_id, project_id, chat_session_id, run_id, request_text_hash,
            normalized_intent, domain, task_type, changed_paths_json,
            validation_status, mistake_type, extracted_lesson, scope, confidence,
            metadata_json
          )
          values (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb,
            %s, %s, %s, %s, %s, %s::jsonb
          )
          on conflict do nothing
          returning id, user_id, project_id, chat_session_id, run_id, request_text_hash,
            normalized_intent, domain, task_type, changed_paths_json, validation_status,
            mistake_type, extracted_lesson, scope, confidence, metadata_json, created_at
          """,
          (
            event_id,
            user.id,
            project_id or None,
            chat_session_id or None,
            str(run_id or ""),
            request_text_hash.strip()[:128],
            normalized_intent.strip()[:120] or "unknown",
            domain.strip()[:120] or "general",
            task_type.strip()[:120] or "general",
            json_dumps_safe(changed_paths or [], context="memory.learning.changed_paths"),
            validation_status.strip()[:120],
            mistake_type.strip()[:160],
            extracted_lesson.strip()[:4000],
            scope.strip()[:80] or "personal",
            safe_confidence,
            json_dumps_safe(metadata or {}, context="memory.learning.metadata"),
          ),
        )
        row = cursor.fetchone()
        if row:
          created = serialize_row(row)
          created["_created"] = True
          return created
        cursor.execute(
          """
          select id, user_id, project_id, chat_session_id, run_id, request_text_hash,
            normalized_intent, domain, task_type, changed_paths_json, validation_status,
            mistake_type, extracted_lesson, scope, confidence, metadata_json, created_at
          from memory_learning_events
          where user_id = %s and project_id = %s and run_id = %s
          limit 1
          """,
          (user.id, project_id or None, str(run_id or "")),
        )
        existing = cursor.fetchone()
        if existing:
          reused = serialize_row(existing)
          reused["_created"] = False
          return reused
        raise RuntimeError("Learning event insert did not return a row.")

  def list_memory_learning_events(
    self,
    user: UserContext,
    *,
    project_id: str | None = None,
    chat_session_id: str | None = None,
    run_id: str | None = None,
    scope: str | None = None,
    limit: int = 50,
    include_all_users: bool = False,
  ) -> list[dict[str, Any]]:
    filters: list[str] = []
    params: list[Any] = []
    if not include_all_users or user.role != "admin":
      filters.append("user_id = %s")
      params.append(user.id)
    if project_id:
      if not include_all_users or user.role != "admin":
        project = require_project(self, project_id, user)
        ensure_project_read(user, project)
      filters.append("project_id = %s")
      params.append(project_id)
    if chat_session_id:
      filters.append("chat_session_id = %s")
      params.append(chat_session_id)
    if run_id:
      filters.append("run_id = %s")
      params.append(run_id)
    if scope:
      filters.append("scope = %s")
      params.append(scope.strip())
    where_clause = f"where {' and '.join(filters)}" if filters else ""
    params.append(max(1, min(int(limit or 50), 200)))
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          f"""
          select id, user_id, project_id, chat_session_id, run_id, request_text_hash,
            normalized_intent, domain, task_type, changed_paths_json, validation_status,
            mistake_type, extracted_lesson, scope, confidence, metadata_json, created_at
          from memory_learning_events
          {where_clause}
          order by created_at desc
          limit %s
          """,
          tuple(params),
        )
        return [serialize_row(row) for row in cursor.fetchall()]

  def upsert_memory_platform_pattern(
    self,
    *,
    domain: str,
    module: str,
    pattern_type: str,
    memory_type: str,
    title: str,
    summary: str,
    situation: str = "",
    improved_behavior: str = "",
    avoid: str = "",
    stack_tags: str = "",
    metadata: dict[str, Any] | None = None,
  ) -> dict[str, Any]:
    pattern_key = build_platform_pattern_key(
      domain=domain,
      module=module,
      pattern_type=pattern_type,
      title=title,
    )
    pattern_id = new_id()
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          insert into memory_platform_patterns (
            id, pattern_key, domain, module, pattern_type, memory_type, title, summary,
            situation, improved_behavior, avoid, stack_tags, source_count, confidence_score, metadata_json
          )
          values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1, 0.6, %s::jsonb)
          on conflict (pattern_key)
          do update set
            summary = excluded.summary,
            situation = case when length(excluded.situation) > 0 then excluded.situation else memory_platform_patterns.situation end,
            improved_behavior = case when length(excluded.improved_behavior) > 0 then excluded.improved_behavior else memory_platform_patterns.improved_behavior end,
            avoid = case when length(excluded.avoid) > 0 then excluded.avoid else memory_platform_patterns.avoid end,
            stack_tags = case when length(excluded.stack_tags) > 0 then excluded.stack_tags else memory_platform_patterns.stack_tags end,
            source_count = memory_platform_patterns.source_count + 1,
            confidence_score = least(0.99, memory_platform_patterns.confidence_score + 0.05),
            metadata_json = excluded.metadata_json,
            last_seen_at = now(),
            updated_at = now()
          returning id, pattern_key, domain, module, pattern_type, memory_type, title, summary,
            situation, improved_behavior, avoid, stack_tags, source_count, confidence_score,
            metadata_json, first_seen_at, last_seen_at, updated_at
          """,
          (
            pattern_id,
            pattern_key,
            domain.strip()[:120] or "general",
            module.strip()[:120] or "general",
            pattern_type.strip()[:64] or "general",
            memory_type.strip()[:64] or "fix_pattern",
            title.strip()[:240],
            summary.strip()[:4000],
            situation.strip()[:2000],
            improved_behavior.strip()[:2000],
            avoid.strip()[:2000],
            stack_tags.strip()[:500],
            json_dumps_safe(metadata or {}, context="memory.platform.metadata"),
          ),
        )
        return serialize_row(cursor.fetchone())

  def list_memory_platform_patterns(
    self,
    *,
    domain: str | None = None,
    module: str | None = None,
    pattern_type: str | None = None,
    limit: int = 8,
  ) -> list[dict[str, Any]]:
    filters: list[str] = []
    params: list[Any] = []
    if domain:
      filters.append("domain = %s")
      params.append(domain.strip())
    if module:
      filters.append("module = %s")
      params.append(module.strip())
    if pattern_type:
      filters.append("pattern_type = %s")
      params.append(pattern_type.strip())
    where_clause = f"where {' and '.join(filters)}" if filters else ""
    safe_limit = max(1, min(limit, 25))
    params.append(safe_limit)
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          f"""
          select id, pattern_key, domain, module, pattern_type, memory_type, title, summary,
            situation, improved_behavior, avoid, stack_tags, source_count, confidence_score,
            metadata_json, first_seen_at, last_seen_at, updated_at
          from memory_platform_patterns
          {where_clause}
          order by confidence_score desc, source_count desc, last_seen_at desc
          limit %s
          """,
          tuple(params),
        )
        return [serialize_row(row) for row in cursor.fetchall()]

  def record_platform_pattern_event(
    self,
    *,
    pattern_id: str,
    domain: str,
    module: str,
    pattern_type: str,
    outcome: str = "observed",
  ) -> dict[str, Any]:
    event_id = new_id()
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          insert into memory_platform_pattern_events (
            id, pattern_id, domain, module, pattern_type, outcome
          )
          values (%s, %s, %s, %s, %s, %s)
          returning id, pattern_id, domain, module, pattern_type, outcome, created_at
          """,
          (event_id, pattern_id, domain, module, pattern_type, outcome),
        )
        return serialize_row(cursor.fetchone())
