from __future__ import annotations

from typing import Any

from .ids import new_id
from .permissions import require_memory_scope
from .serialization import json_dumps_safe, serialize_row
from .user import UserContext


MEMORY_SCOPE_CONSTRAINT_TABLES = {
  "fk_memory_episodes_session_scope": "memory_episodes",
  "fk_memory_episodes_topic_scope": "memory_episodes",
  "fk_memory_episodes_run_scope": "memory_episodes",
  "fk_memory_snapshots_session_scope": "memory_session_snapshots",
  "fk_memory_snapshots_topic_scope": "memory_session_snapshots",
  "fk_memory_snapshots_run_scope": "memory_session_snapshots",
  "fk_memory_state_session_scope": "memory_chat_session_state",
  "fk_memory_state_topic_scope": "memory_chat_session_state",
  "fk_memory_state_run_scope": "memory_chat_session_state",
  "fk_chat_topics_session_scope": "memory_chat_topics",
  "fk_chat_messages_session_scope": "project_chat_messages",
  "fk_chat_messages_topic_scope": "project_chat_messages",
}


class ConsistencyJobStoreMixin:
  def claim_memory_checkpoint(
    self,
    user: UserContext,
    *,
    project_id: str,
    chat_session_id: str,
    generation_run_id: str,
    chat_topic_id: str | None = None,
    stale_after_seconds: int = 900,
  ) -> bool:
    stale_after = max(60, min(int(stale_after_seconds), 86400))
    require_memory_scope(
      self,
      user,
      project_id=project_id,
      chat_session_id=chat_session_id,
      chat_topic_id=chat_topic_id,
      generation_run_id=generation_run_id,
      write=True,
    )
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          insert into memory_checkpoint_commits (
            generation_run_id, project_id, user_id, chat_session_id, chat_topic_id, status
          )
          values (%s, %s, %s, %s, %s, 'processing')
          on conflict (generation_run_id)
          do update set
            project_id = excluded.project_id,
            user_id = excluded.user_id,
            chat_session_id = excluded.chat_session_id,
            chat_topic_id = excluded.chat_topic_id,
            status = 'processing',
            last_error = '',
            claimed_at = now(),
            updated_at = now()
          where memory_checkpoint_commits.status = 'failed'
             or (
               memory_checkpoint_commits.status = 'processing'
               and memory_checkpoint_commits.updated_at < now() - (%s * interval '1 second')
             )
          returning generation_run_id
          """,
          (
            generation_run_id,
            project_id,
            user.id,
            chat_session_id,
            chat_topic_id,
            stale_after,
          ),
        )
        return cursor.fetchone() is not None

  def complete_memory_checkpoint(
    self,
    *,
    generation_run_id: str,
    snapshot_id: str | None = None,
    episode_id: str | None = None,
  ) -> bool:
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          update memory_checkpoint_commits
          set status = 'completed', snapshot_id = %s, episode_id = %s,
            last_error = '', completed_at = now(), updated_at = now()
          where generation_run_id = %s and status = 'processing'
          returning generation_run_id
          """,
          (snapshot_id, episode_id, generation_run_id),
        )
        return cursor.fetchone() is not None

  def fail_memory_checkpoint(
    self,
    *,
    generation_run_id: str,
    error: str,
  ) -> bool:
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          update memory_checkpoint_commits
          set status = 'failed', last_error = %s, completed_at = null, updated_at = now()
          where generation_run_id = %s and status = 'processing'
          returning generation_run_id
          """,
          (str(error or "")[:1000], generation_run_id),
        )
        return cursor.fetchone() is not None

  def get_memory_checkpoint_commit(self, *, generation_run_id: str) -> dict[str, Any] | None:
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          select generation_run_id, project_id, user_id, chat_session_id, chat_topic_id,
            status, snapshot_id, episode_id, last_error, claimed_at, completed_at, updated_at
          from memory_checkpoint_commits
          where generation_run_id = %s
          limit 1
          """,
          (generation_run_id,),
        )
        row = cursor.fetchone()
        return serialize_row(row) if row else None

  def enqueue_pending_episode_vector_jobs(
    self,
    user: UserContext,
    *,
    limit: int = 20,
  ) -> int:
    safe_limit = max(1, min(int(limit), 100))
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          f"""
          select id, project_id, chat_session_id
          from memory_episodes
          where user_id = %s and vector_status in ('pending', 'failed')
          order by updated_at
          limit %s
          """,
          (user.id, safe_limit),
        )
        rows = [dict(row) for row in cursor.fetchall()]
    for row in rows:
      self.enqueue_consistency_job(
        user,
        project_id=str(row.get("project_id") or ""),
        job_type="episode_vector_upsert",
        target_key=str(row.get("id") or ""),
        source_hash=str(row.get("id") or ""),
        payload={
          "episode_id": row.get("id"),
          "chat_session_id": row.get("chat_session_id"),
        },
      )
    return len(rows)

  def enqueue_consistency_job(
    self,
    user: UserContext | None,
    *,
    project_id: str,
    job_type: str,
    target_key: str = "",
    source_hash: str = "",
    payload: dict[str, Any] | None = None,
    max_attempts: int = 5,
  ) -> dict[str, Any]:
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          insert into project_consistency_jobs (
            id, project_id, user_id, job_type, target_key, source_hash,
            payload_json, status, max_attempts
          )
          values (%s, %s, %s, %s, %s, %s, %s::jsonb, 'pending', %s)
          on conflict (project_id, job_type, target_key, source_hash)
          do update set
            payload_json = excluded.payload_json,
            status = 'pending',
            attempt_count = 0,
            max_attempts = excluded.max_attempts,
            last_error = '',
            available_at = now(),
            locked_at = null,
            completed_at = null,
            updated_at = now()
          returning id, project_id, user_id, job_type, target_key, source_hash,
            payload_json, status, attempt_count, max_attempts, last_error,
            available_at, locked_at, completed_at, created_at, updated_at
          """,
          (
            new_id(),
            project_id,
            getattr(user, "id", None),
            str(job_type or "").strip(),
            str(target_key or "").strip(),
            str(source_hash or "").strip(),
            json_dumps_safe(payload or {}, context="consistency_job.payload"),
            max(1, min(int(max_attempts), 20)),
          ),
        )
        return serialize_row(cursor.fetchone())

  def list_due_consistency_jobs(
    self,
    *,
    limit: int = 20,
    user_id: str | None = None,
  ) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 100))
    user_filter = "and (user_id is null or user_id = %s)" if user_id else ""
    params = (user_id, safe_limit) if user_id else (safe_limit,)
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          f"""
          select id, project_id, user_id, job_type, target_key, source_hash,
            payload_json, status, attempt_count, max_attempts, last_error,
            available_at, locked_at, completed_at, created_at, updated_at
          from project_consistency_jobs
          where status in ('pending', 'failed')
            and attempt_count < max_attempts
            and available_at <= now()
            {user_filter}
          order by available_at, created_at
          limit %s
          """,
          params,
        )
        return [serialize_row(row) for row in cursor.fetchall()]

  def audit_memory_scope_mismatches(self) -> dict[str, int]:
    queries = {
      "topics": """
        select count(*) as count
        from memory_chat_topics topic
        join project_chat_sessions session on session.id = topic.chat_session_id
        where topic.project_id <> session.project_id or topic.user_id <> session.user_id
      """,
      "episodes": """
        select count(*) as count
        from memory_episodes episode
        join project_chat_sessions session on session.id = episode.chat_session_id
        where episode.project_id <> session.project_id or episode.user_id <> session.user_id
      """,
      "snapshots": """
        select count(*) as count
        from memory_session_snapshots snapshot
        join project_chat_sessions session on session.id = snapshot.chat_session_id
        where snapshot.project_id <> session.project_id or snapshot.user_id <> session.user_id
      """,
      "session_state": """
        select count(*) as count
        from memory_chat_session_state state
        join project_chat_sessions session on session.id = state.chat_session_id
        where state.project_id <> session.project_id or state.user_id <> session.user_id
      """,
      "episode_topics": """
        select count(*) as count
        from memory_episodes episode
        join memory_chat_topics topic on topic.id = episode.chat_topic_id
        where episode.project_id <> topic.project_id
          or episode.user_id <> topic.user_id
          or episode.chat_session_id <> topic.chat_session_id
      """,
      "episode_runs": """
        select count(*) as count
        from memory_episodes episode
        join generation_runs run on run.id = episode.generation_run_id
        where episode.project_id <> run.project_id or episode.user_id <> run.user_id
      """,
      "snapshot_topics": """
        select count(*) as count
        from memory_session_snapshots snapshot
        join memory_chat_topics topic on topic.id = snapshot.chat_topic_id
        where snapshot.project_id <> topic.project_id
          or snapshot.user_id <> topic.user_id
          or snapshot.chat_session_id <> topic.chat_session_id
      """,
      "snapshot_runs": """
        select count(*) as count
        from memory_session_snapshots snapshot
        join generation_runs run on run.id = snapshot.generation_run_id
        where snapshot.project_id <> run.project_id or snapshot.user_id <> run.user_id
      """,
    }
    results: dict[str, int] = {}
    with self.connect() as conn:
      with conn.cursor() as cursor:
        for key, query in queries.items():
          cursor.execute(query)
          row = cursor.fetchone() or {}
          results[key] = int(row.get("count") or 0)
    results["total"] = sum(results.values())
    return results

  def list_unvalidated_memory_constraints(self) -> list[dict[str, str]]:
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          select conrelid::regclass::text as table_name, conname as constraint_name
          from pg_constraint
          where conname in (
            'fk_memory_episodes_session_scope',
            'fk_memory_episodes_topic_scope',
            'fk_memory_episodes_run_scope',
            'fk_memory_snapshots_session_scope',
            'fk_memory_snapshots_topic_scope',
            'fk_memory_snapshots_run_scope',
            'fk_memory_state_session_scope',
            'fk_memory_state_topic_scope',
            'fk_memory_state_run_scope',
            'fk_chat_topics_session_scope',
            'fk_chat_messages_session_scope',
            'fk_chat_messages_topic_scope'
          )
            and not convalidated
          order by conrelid::regclass::text, conname
          """
        )
        return [
          {
            "table": str(row.get("table_name") or ""),
            "constraint": str(row.get("constraint_name") or ""),
          }
          for row in cursor.fetchall()
        ]

  def validate_memory_scope_constraints(self, *, dry_run: bool = True) -> dict[str, Any]:
    scope = self.audit_memory_scope_mismatches()
    pending = self.list_unvalidated_memory_constraints()
    if int(scope.get("total") or 0) > 0:
      return {
        "status": "blocked",
        "reason": "memory_scope_mismatches_must_be_fixed_before_constraint_validation",
        "dry_run": dry_run,
        "scope_mismatches": scope,
        "unvalidated_constraints": pending,
        "validated_constraints": [],
      }
    if not pending:
      return {
        "status": "ok",
        "reason": "all_memory_scope_constraints_already_validated",
        "dry_run": dry_run,
        "scope_mismatches": scope,
        "unvalidated_constraints": [],
        "validated_constraints": [],
      }
    validatable = [
      item
      for item in pending
      if str(item.get("constraint") or "") in MEMORY_SCOPE_CONSTRAINT_TABLES
    ]
    if dry_run:
      return {
        "status": "ready",
        "reason": "set_dry_run_false_to_validate_constraints",
        "dry_run": True,
        "scope_mismatches": scope,
        "unvalidated_constraints": pending,
        "would_validate_constraints": validatable,
        "validated_constraints": [],
      }
    validated: list[dict[str, str]] = []
    with self.connect() as conn:
      with conn.cursor() as cursor:
        for item in validatable:
          constraint = str(item.get("constraint") or "")
          table = MEMORY_SCOPE_CONSTRAINT_TABLES[constraint]
          cursor.execute(f"alter table {table} validate constraint {constraint}")
          validated.append({"table": table, "constraint": constraint})
    remaining = self.list_unvalidated_memory_constraints()
    return {
      "status": "validated" if not remaining else "partial",
      "reason": "memory_scope_constraints_validated" if not remaining else "some_constraints_remain_unvalidated",
      "dry_run": False,
      "scope_mismatches": scope,
      "unvalidated_constraints": remaining,
      "validated_constraints": validated,
    }

  def get_memory_health(self) -> dict[str, Any]:
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          select status, count(*) as count
          from project_consistency_jobs
          group by status
          """
        )
        job_counts = {str(row["status"]): int(row["count"]) for row in cursor.fetchall()}
        cursor.execute(
          """
          select vector_status, count(*) as count
          from memory_episodes
          group by vector_status
          """
        )
        vector_counts = {str(row["vector_status"]): int(row["count"]) for row in cursor.fetchall()}
        cursor.execute(
          """
          select
            coalesce(extract(epoch from (now() - min(created_at))), 0) as age_seconds,
            count(*) filter (where status = 'processing' and locked_at < now() - interval '5 minutes') as stuck_processing
          from project_consistency_jobs
          where status in ('pending', 'failed', 'processing')
          """
        )
        row = cursor.fetchone() or {}
        cursor.execute(
          """
          select status, count(*) as count
          from memory_checkpoint_commits
          group by status
          """
        )
        checkpoint_counts = {
          str(item["status"]): int(item["count"])
          for item in cursor.fetchall()
        }
        cursor.execute(
          """
          select count(*) as count
          from memory_checkpoint_commits
          where status = 'processing' and updated_at < now() - interval '15 minutes'
          """
        )
        checkpoint_row = cursor.fetchone() or {}
    scope = self.audit_memory_scope_mismatches()
    unvalidated_constraints = self.list_unvalidated_memory_constraints()
    oldest_retry_age = int(float(row.get("age_seconds") or 0))
    stuck_jobs = int(row.get("stuck_processing") or 0)
    stuck_checkpoints = int(checkpoint_row.get("count") or 0)
    failed_vectors = int(vector_counts.get("failed") or 0)
    return {
      "consistency_jobs": job_counts,
      "episode_vectors": vector_counts,
      "checkpoint_commits": checkpoint_counts,
      "oldest_retry_age_seconds": oldest_retry_age,
      "stuck_processing_jobs": stuck_jobs,
      "stuck_processing_checkpoints": stuck_checkpoints,
      "scope_mismatches": scope,
      "unvalidated_constraints": unvalidated_constraints,
      "healthy": (
        int(scope.get("total") or 0) == 0
        and not unvalidated_constraints
        and int(job_counts.get("failed") or 0) == 0
        and stuck_jobs == 0
        and stuck_checkpoints == 0
        and failed_vectors == 0
        and oldest_retry_age < 300
      ),
    }

  def mark_consistency_job_processing(self, *, job_id: str) -> bool:
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          update project_consistency_jobs
          set status = 'processing', attempt_count = attempt_count + 1,
            locked_at = now(), updated_at = now()
          where id = %s and status in ('pending', 'failed') and attempt_count < max_attempts
          returning id
          """,
          (job_id,),
        )
        return cursor.fetchone() is not None

  def recover_stale_consistency_jobs(self, *, lock_timeout_seconds: int = 300) -> int:
    safe_timeout = max(30, min(int(lock_timeout_seconds), 86400))
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          update project_consistency_jobs
          set status = 'failed',
            last_error = case
              when last_error = '' then 'Worker lock expired before completion.'
              else last_error
            end,
            available_at = now(),
            locked_at = null,
            updated_at = now()
          where status = 'processing'
            and locked_at < now() - (%s * interval '1 second')
          returning id
          """,
          (safe_timeout,),
        )
        return len(cursor.fetchall())

  def complete_consistency_job(self, *, job_id: str) -> bool:
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          update project_consistency_jobs
          set status = 'completed', last_error = '', completed_at = now(), updated_at = now()
          where id = %s
          returning id
          """,
          (job_id,),
        )
        return cursor.fetchone() is not None

  def fail_consistency_job(self, *, job_id: str, error: str, retry_seconds: int = 30) -> bool:
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          update project_consistency_jobs
          set status = 'failed', last_error = %s,
            available_at = now() + (%s * interval '1 second'), updated_at = now()
          where id = %s
          returning id
          """,
          (str(error or "")[:1000], max(1, min(int(retry_seconds), 86400)), job_id),
        )
        return cursor.fetchone() is not None
