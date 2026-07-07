from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any

try:
  from ..local_workspace import LocalWorkspaceError, normalize_project_file_path
except ImportError:
  from local_workspace import LocalWorkspaceError, normalize_project_file_path

from .roles import READ_ROLES, WRITE_ROLES

from .errors import StorageError
from .ids import new_id
from .permissions import ensure_project_read, ensure_project_write, require_project, require_write
from .serialization import serialize_row
from .user import UserContext

logger = logging.getLogger(__name__)


def _content_hash(content: str) -> str:
  return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _project_ui_refresh_inline_enabled() -> bool:
  raw = os.getenv("WORKTUAL_INLINE_PROJECT_UI_KNOWLEDGE_REFRESH", "").strip().lower()
  return raw in {"1", "true", "yes", "on"}


def _normalize_project_file_record(file_item: dict[str, Any]) -> dict[str, str]:
  raw_path = str(file_item.get("path") or "").strip()
  try:
    path = normalize_project_file_path(raw_path)
  except LocalWorkspaceError as exc:
    raise StorageError(str(exc)) from exc
  if "content" in file_item:
    content = file_item.get("content")
  else:
    content = file_item.get("code")
  if content is None:
    raise StorageError(f"Project file is missing content: {path}")
  if not isinstance(content, str):
    raise StorageError(f"Project file content must be a string: {path}")
  text = content
  return {"path": path, "content": text, "content_hash": _content_hash(text)}


def _normalize_project_file_records(files: list[dict[str, Any]]) -> list[dict[str, str]]:
  by_path: dict[str, dict[str, str]] = {}
  for file_item in files:
    if not isinstance(file_item, dict):
      raise StorageError("Project files must be objects with path and content.")
    normalized = _normalize_project_file_record(file_item)
    if normalized["path"] in by_path:
      raise StorageError(f"Duplicate project file path after normalization: {normalized['path']}")
    by_path[normalized["path"]] = normalized
  return [by_path[path] for path in sorted(by_path)]


def _reindex_project_files_after_persist(
  project_id: str,
  files: list[dict[str, Any]],
  *,
  changed_paths: list[str] | None = None,
) -> bool:
  try:
    from ..agents.code_index.incremental import maybe_reindex_after_persist
  except ImportError:
    try:
      from agents.code_index.incremental import maybe_reindex_after_persist
    except ImportError:
      return False
  try:
    result = maybe_reindex_after_persist(project_id, files, changed_paths=changed_paths)
    return isinstance(result, dict) and not bool(result.get("error"))
  except Exception:
    logger.exception("Project code reindex failed after file persistence", extra={"project_id": project_id})
    return False


def _persist_project_code_index_after_reindex(
  store: Any,
  project_id: str,
  files: list[dict[str, Any]],
  *,
  replace_all: bool = False,
) -> bool:
  try:
    from ..agents.code_index.store import get_project_chunks
    from ..agents.code_index.incremental import maybe_reindex_after_persist
  except ImportError:
    try:
      from agents.code_index.store import get_project_chunks
      from agents.code_index.incremental import maybe_reindex_after_persist
    except ImportError:
      return False
  if not replace_all:
    try:
      with store.connect() as conn:
        with conn.cursor() as cursor:
          cursor.execute(
            """
            select
              project_files.path,
              project_files.content,
              project_files.content_hash,
              exists (
                select 1
                from project_code_index_chunks
                where project_code_index_chunks.project_id = project_files.project_id
                  and project_code_index_chunks.path = project_files.path
                  and project_code_index_chunks.file_content_hash = project_files.content_hash
              ) as indexed
            from project_files
            where project_files.project_id = %s
            order by project_files.path
            """,
            (project_id,),
          )
          rows = [dict(row) for row in cursor.fetchall()]
      indexable = [
        row
        for row in rows
        if str(row.get("content") or "").strip()
        and str(row.get("path") or "").endswith((".js", ".jsx", ".ts", ".tsx", ".css", ".html", ".json"))
      ]
      if any(not bool(row.get("indexed")) for row in indexable):
        files = [
          {
            "path": str(row.get("path") or ""),
            "content": str(row.get("content") or ""),
            "content_hash": str(row.get("content_hash") or ""),
          }
          for row in rows
          if row.get("path")
        ]
        maybe_reindex_after_persist(project_id, files)
        replace_all = True
    except Exception:
      logger.exception("Could not inspect persistent code-index freshness", extra={"project_id": project_id})
  paths = {
    str(item.get("path") or "")
    for item in files
    if isinstance(item, dict) and item.get("path")
  }
  file_hashes = {
    str(item.get("path") or ""): str(item.get("content_hash") or _content_hash(str(item.get("content") or "")))
    for item in files
    if isinstance(item, dict) and item.get("path")
  }
  chunks = [
    item
    for item in get_project_chunks(project_id)
    if (
      isinstance(item, dict)
      and str(item.get("path") or "") in paths
      and str(item.get("file_content_hash") or "") == file_hashes.get(str(item.get("path") or ""), "")
    )
  ]

  def operation(cursor: Any) -> None:
    if replace_all:
      cursor.execute("delete from project_code_index_chunks where project_id = %s", (project_id,))
    else:
      for path in sorted(paths):
        cursor.execute(
          "delete from project_code_index_chunks where project_id = %s and path = %s",
          (project_id, path),
        )
    for chunk in chunks:
      path = str(chunk.get("path") or "")
      chunk_id = str(chunk.get("chunk_id") or "")
      if not path or not chunk_id:
        continue
      cursor.execute(
        """
        insert into project_code_index_chunks (
          project_id, path, chunk_id, symbol, line_start, line_end, content,
          content_hash, file_content_hash, embedding_json, embedding_model,
          embedding_dimensions, updated_at
        )
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, now())
        on conflict (project_id, path, chunk_id)
        do update set
          symbol = excluded.symbol,
          line_start = excluded.line_start,
          line_end = excluded.line_end,
          content = excluded.content,
          content_hash = excluded.content_hash,
          file_content_hash = excluded.file_content_hash,
          embedding_json = excluded.embedding_json,
          embedding_model = excluded.embedding_model,
          embedding_dimensions = excluded.embedding_dimensions,
          updated_at = now()
        """,
        (
          project_id,
          path,
          chunk_id,
          str(chunk.get("symbol") or ""),
          int(chunk.get("line_start") or 0),
          int(chunk.get("line_end") or 0),
          str(chunk.get("content") or ""),
          str(chunk.get("content_hash") or ""),
          str(chunk.get("file_content_hash") or ""),
          json.dumps(list(chunk.get("embedding") or [])),
          str(chunk.get("embedding_model") or ""),
          int(chunk.get("embedding_dimensions") or len(list(chunk.get("embedding") or []))),
        ),
      )

  try:
    store._run_project_file_transaction(operation)
    return True
  except Exception:
    logger.exception("Could not persist refreshed project code index", extra={"project_id": project_id})
    return False


def _refresh_project_ui_knowledge_after_persist(
  store: Any,
  project_id: str,
  user: UserContext,
  *,
  chat_session_id: str | None = None,
  chat_topic_id: str | None = None,
  generation_run_id: str | None = None,
) -> bool:
  if not hasattr(store, "upsert_memory_item"):
    return False
  try:
    from ..agents.memory.project_knowledge import persist_project_ui_knowledge
  except ImportError:
    try:
      from agents.memory.project_knowledge import persist_project_ui_knowledge
    except ImportError:
      return False
  try:
    files = store.list_files(project_id, user)
    persist_project_ui_knowledge(
      store,
      user,
      project_id=project_id,
      files=files,
      chat_session_id=chat_session_id,
      chat_topic_id=chat_topic_id,
      generation_run_id=generation_run_id,
    )
    return True
  except Exception:
    logger.exception("Could not refresh project UI knowledge", extra={"project_id": project_id})
    return False


def _add_project_event_safely(
  store: Any,
  project_id: str,
  user_id: str,
  event_type: str,
  payload: dict[str, Any],
) -> None:
  try:
    store.add_event(project_id, user_id, event_type, payload)
  except Exception:
    logger.exception(
      "Project event persistence failed after primary data committed",
      extra={"project_id": project_id, "event_type": event_type},
    )


def _project_files_source_hash(files: list[dict[str, Any]]) -> str:
  digest = hashlib.sha256()
  for item in sorted(files, key=lambda row: str(row.get("path") or "")):
    digest.update(str(item.get("path") or "").encode("utf-8"))
    digest.update(b"\0")
    digest.update(str(item.get("content_hash") or _content_hash(str(item.get("content") or ""))).encode("utf-8"))
    digest.update(b"\0")
  return digest.hexdigest()


def _run_project_post_write_consistency(
  store: Any,
  project_id: str,
  user: UserContext,
  files: list[dict[str, Any]],
  *,
  changed_paths: list[str] | None = None,
  replace_all: bool = False,
  chat_session_id: str | None = None,
  chat_topic_id: str | None = None,
  generation_run_id: str | None = None,
) -> None:
  source_files = files
  if hasattr(store, "list_files"):
    try:
      source_files = list(store.list_files(project_id, user) or [])
    except Exception:
      logger.exception(
        "Could not load the complete project manifest for consistency hashing",
        extra={"project_id": project_id},
      )
  source_hash = _project_files_source_hash(source_files)
  reindexed = _reindex_project_files_after_persist(
    project_id,
    files,
    changed_paths=None if replace_all else changed_paths,
  )
  index_persisted = (
    _persist_project_code_index_after_reindex(
      store,
      project_id,
      files,
      replace_all=replace_all,
    )
    if reindexed
    else False
  )
  has_consistency_queue = hasattr(store, "enqueue_consistency_job")
  ui_persisted = False
  if _project_ui_refresh_inline_enabled() or not has_consistency_queue:
    ui_persisted = _refresh_project_ui_knowledge_after_persist(
      store,
      project_id,
      user,
      chat_session_id=chat_session_id,
      chat_topic_id=chat_topic_id,
      generation_run_id=generation_run_id,
    )
  if not has_consistency_queue:
    return
  common_payload = {
    "changed_paths": list(changed_paths or []),
    "replace_all": replace_all,
    "chat_session_id": chat_session_id,
    "chat_topic_id": chat_topic_id,
    "generation_run_id": generation_run_id,
  }
  if not index_persisted:
    try:
      store.enqueue_consistency_job(
        user,
        project_id=project_id,
        job_type="project_code_index_refresh",
        target_key="project",
        source_hash=source_hash,
        payload=common_payload,
      )
    except Exception:
      logger.exception("Could not enqueue project code-index repair", extra={"project_id": project_id})
  if not ui_persisted:
    try:
      store.enqueue_consistency_job(
        user,
        project_id=project_id,
        job_type="project_ui_knowledge_refresh",
        target_key="project",
        source_hash=source_hash,
        payload=common_payload,
      )
    except Exception:
      logger.exception("Could not enqueue project UI-knowledge repair", extra={"project_id": project_id})


class ProjectFileStoreMixin:
  def _run_project_file_transaction(self, operation: Any) -> Any:
    with self.connect() as conn:
      original_autocommit = getattr(conn, "autocommit", None)
      if original_autocommit is not None:
        conn.autocommit = False
      try:
        with conn.cursor() as cursor:
          result = operation(cursor)
        if hasattr(conn, "commit"):
          conn.commit()
        return result
      except Exception:
        if hasattr(conn, "rollback"):
          conn.rollback()
        raise
      finally:
        if original_autocommit is not None:
          conn.autocommit = original_autocommit

  def ensure_user(self, email: str, *, role: str = "admin") -> UserContext:
    normalized_email = email.strip().lower()
    if role not in READ_ROLES:
      role = "viewer"
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute("select id, email, role, display_name from users where email = %s", (normalized_email,))
        row = cursor.fetchone()
        if row:
          return UserContext(
            id=row["id"],
            email=row["email"],
            role=row["role"],
            display_name=row.get("display_name") or "",
          )
        user_id = new_id()
        cursor.execute(
          "insert into users (id, email, role, display_name) values (%s, %s, %s, %s)",
          (user_id, normalized_email, role, ""),
        )
        return UserContext(id=user_id, email=normalized_email, role=role, display_name="")

  def list_projects(self, user: UserContext) -> list[dict[str, Any]]:
    with self.connect() as conn:
      with conn.cursor() as cursor:
        if user.role == "admin":
          cursor.execute(
            "select id, name, description, owner_user_id, local_path, created_at, updated_at from projects order by updated_at desc"
          )
        else:
          cursor.execute(
            """
            select id, name, description, owner_user_id, local_path, created_at, updated_at
            from projects
            where owner_user_id = %s
            order by updated_at desc
            """,
            (user.id,),
          )
        return [serialize_row(row) for row in cursor.fetchall()]

  def create_project(self, user: UserContext, *, name: str, description: str = "") -> dict[str, Any]:
    require_write(user)
    project_id = new_id()
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          insert into projects (id, owner_user_id, name, description)
          values (%s, %s, %s, %s)
          """,
          (project_id, user.id, name.strip() or "Untitled project", description.strip()),
        )
    self.add_event(project_id, user.id, "project.created", {"name": name})
    project = self.get_project(project_id, user)
    if not project:
      raise StorageError("Project was created but could not be loaded.")
    return project

  def update_project(self, project_id: str, user: UserContext, *, name: str | None = None) -> dict[str, Any]:
    project = require_project(self, project_id, user)
    ensure_project_write(user, project)
    next_name = (name or "").strip()
    if not next_name:
      raise StorageError("Project name cannot be empty.")
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          update projects
          set name = %s, updated_at = now()
          where id = %s
          returning id, name, description, owner_user_id, local_path, created_at, updated_at
          """,
          (next_name, project_id),
        )
        row = cursor.fetchone()
    self.add_event(project_id, user.id, "project.renamed", {"name": next_name})
    return serialize_row(row)

  def delete_project(self, project_id: str, user: UserContext) -> dict[str, Any]:
    project = require_project(self, project_id, user)
    ensure_project_write(user, project)
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute("delete from projects where id = %s", (project_id,))
    return project

  def get_project(self, project_id: str, user: UserContext) -> dict[str, Any] | None:
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          "select id, name, description, owner_user_id, local_path, created_at, updated_at from projects where id = %s",
          (project_id,),
        )
        row = cursor.fetchone()
    if not row:
      return None
    project = serialize_row(row)
    ensure_project_read(user, project)
    return project

  def list_files(
    self,
    project_id: str,
    user: UserContext,
    *,
    include_code_index: bool = False,
  ) -> list[dict[str, Any]]:
    project = require_project(self, project_id, user)
    ensure_project_read(user, project)
    with self.connect() as conn:
      with conn.cursor() as cursor:
        code_index_select = """
            , coalesce(
                (
                  select jsonb_agg(
                    jsonb_build_object(
                      'project_id', project_code_index_chunks.project_id,
                      'path', project_code_index_chunks.path,
                      'chunk_id', project_code_index_chunks.chunk_id,
                      'symbol', project_code_index_chunks.symbol,
                      'line_start', project_code_index_chunks.line_start,
                      'line_end', project_code_index_chunks.line_end,
                      'content', project_code_index_chunks.content,
                      'content_hash', project_code_index_chunks.content_hash,
                      'file_content_hash', project_code_index_chunks.file_content_hash,
                      'embedding', project_code_index_chunks.embedding_json,
                      'embedding_model', project_code_index_chunks.embedding_model,
                      'embedding_dimensions', project_code_index_chunks.embedding_dimensions
                    )
                    order by project_code_index_chunks.line_start, project_code_index_chunks.chunk_id
                  )
                  from project_code_index_chunks
                  where project_code_index_chunks.project_id = project_files.project_id
                    and project_code_index_chunks.path = project_files.path
                ),
                '[]'::jsonb
              ) as code_index_chunks
        """ if include_code_index else ""
        cursor.execute(
          f"""
          select
            project_files.path,
            project_files.content,
            project_files.content_hash,
            project_files.updated_at
            {code_index_select}
          from project_files
          where project_files.project_id = %s
          order by project_files.path
          """,
          (project_id,),
        )
        return [serialize_row(row) for row in cursor.fetchall()]

  def upsert_file(
    self,
    project_id: str,
    user: UserContext,
    *,
    path: str,
    content: str,
    emit_event: bool = True,
  ) -> dict[str, Any]:
    project = require_project(self, project_id, user)
    ensure_project_write(user, project)
    file_item = _normalize_project_file_record({"path": path, "content": content})
    def operation(cursor: Any) -> Any:
        cursor.execute(
          """
          insert into project_files (project_id, path, content, content_hash, updated_at)
          values (%s, %s, %s, %s, now())
          on conflict (project_id, path)
          do update set content = excluded.content, content_hash = excluded.content_hash, updated_at = now()
          returning path, content, content_hash, updated_at
          """,
          (project_id, file_item["path"], file_item["content"], file_item["content_hash"]),
        )
        row = cursor.fetchone()
        cursor.execute("update projects set updated_at = now() where id = %s", (project_id,))
        return row
    row = self._run_project_file_transaction(operation)
    if emit_event:
      _add_project_event_safely(self, project_id, user.id, "file.saved", {"path": file_item["path"]})
    _run_project_post_write_consistency(
      self,
      project_id,
      user,
      [file_item],
      changed_paths=[file_item["path"]],
    )
    return serialize_row(row)

  def set_project_local_path(self, project_id: str, user: UserContext, local_path: str) -> dict[str, Any]:
    project = require_project(self, project_id, user)
    ensure_project_write(user, project)
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          update projects
          set local_path = %s, updated_at = now()
          where id = %s
          returning id, name, description, owner_user_id, local_path, created_at, updated_at
          """,
          (local_path, project_id),
        )
        row = cursor.fetchone()
    self.add_event(project_id, user.id, "local.path.linked", {"path": local_path})
    return serialize_row(row)

  def replace_project_files(
    self,
    project_id: str,
    user: UserContext,
    files: list[dict[str, str]],
    *,
    event_type: str = "files.synced",
    event_payload: dict[str, Any] | None = None,
    allow_prune_missing: bool = False,
  ) -> None:
    project = require_project(self, project_id, user)
    ensure_project_write(user, project)
    normalized_files = _normalize_project_file_records(files)
    def operation(cursor: Any) -> int:
        cursor.execute("select count(*) as count from project_files where project_id = %s", (project_id,))
        row = cursor.fetchone() or {}
        existing_count = int(row.get("count") or 0)
        if (
          existing_count
          and len(normalized_files) < existing_count
          and not allow_prune_missing
          and not bool((event_payload or {}).get("allow_prune_missing"))
        ):
          raise StorageError(
            "Refusing to replace project files with an incomplete manifest. "
            "Use upsert_project_files for partial updates or pass allow_prune_missing for explicit full replacement."
          )
        cursor.execute("delete from project_files where project_id = %s", (project_id,))
        for file_item in normalized_files:
          cursor.execute(
            """
            insert into project_files (project_id, path, content, content_hash, updated_at)
            values (%s, %s, %s, %s, now())
            """,
            (project_id, file_item["path"], file_item["content"], file_item["content_hash"]),
          )
        cursor.execute("update projects set updated_at = now() where id = %s", (project_id,))
        return existing_count
    self._run_project_file_transaction(operation)
    payload = {"count": len(normalized_files)}
    if event_payload:
      payload.update(event_payload)
    _add_project_event_safely(self, project_id, user.id, event_type, payload)
    _run_project_post_write_consistency(
      self,
      project_id,
      user,
      normalized_files,
      changed_paths=[file_item["path"] for file_item in normalized_files],
      replace_all=True,
      chat_session_id=str(payload.get("chat_session_id") or "") or None,
      chat_topic_id=str(payload.get("chat_topic_id") or "") or None,
      generation_run_id=str(payload.get("generation_run_id") or "") or None,
    )

  def upsert_project_files(
    self,
    project_id: str,
    user: UserContext,
    files: list[dict[str, str]],
    *,
    event_type: str = "files.upserted",
    event_payload: dict[str, Any] | None = None,
  ) -> int:
    project = require_project(self, project_id, user)
    ensure_project_write(user, project)
    normalized_files = _normalize_project_file_records(files)
    def operation(cursor: Any) -> None:
        for file_item in normalized_files:
          cursor.execute(
            """
            insert into project_files (project_id, path, content, content_hash, updated_at)
            values (%s, %s, %s, %s, now())
            on conflict (project_id, path)
            do update set content = excluded.content, content_hash = excluded.content_hash, updated_at = now()
            """,
            (project_id, file_item["path"], file_item["content"], file_item["content_hash"]),
          )
        cursor.execute("update projects set updated_at = now() where id = %s", (project_id,))
    self._run_project_file_transaction(operation)
    payload = {"count": len(normalized_files)}
    if event_payload:
      payload.update(event_payload)
    _add_project_event_safely(self, project_id, user.id, event_type, payload)
    _run_project_post_write_consistency(
      self,
      project_id,
      user,
      normalized_files,
      changed_paths=[file_item["path"] for file_item in normalized_files],
      chat_session_id=str(payload.get("chat_session_id") or "") or None,
      chat_topic_id=str(payload.get("chat_topic_id") or "") or None,
      generation_run_id=str(payload.get("generation_run_id") or "") or None,
    )
    return len(normalized_files)

  def apply_generated_files(self, project_id: str, user: UserContext, files: list[dict[str, str]]) -> None:
    project = require_project(self, project_id, user)
    ensure_project_write(user, project)
    normalized_files = _normalize_project_file_records(files)
    def operation(cursor: Any) -> None:
        for file_item in normalized_files:
          cursor.execute(
            """
            insert into project_files (project_id, path, content, content_hash, updated_at)
            values (%s, %s, %s, %s, now())
            on conflict (project_id, path)
            do update set content = excluded.content, content_hash = excluded.content_hash, updated_at = now()
            """,
            (project_id, file_item["path"], file_item["content"], file_item["content_hash"]),
          )
        cursor.execute("update projects set updated_at = now() where id = %s", (project_id,))
    self._run_project_file_transaction(operation)
    _add_project_event_safely(
      self,
      project_id,
      user.id,
      "files.generated",
      {"count": len(normalized_files)},
    )
    _run_project_post_write_consistency(
      self,
      project_id,
      user,
      normalized_files,
      changed_paths=[file_item["path"] for file_item in normalized_files],
    )
