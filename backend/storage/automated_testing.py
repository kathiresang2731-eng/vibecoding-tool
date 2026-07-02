from __future__ import annotations

from typing import Any

from .errors import StorageError
from .ids import new_id
from .permissions import ensure_project_read, ensure_project_write, require_project
from .serialization import json_dumps_safe, serialize_row
from .user import UserContext


class AutomatedTestingStoreMixin:
  def link_automation_test_runs_to_generation(
    self,
    *,
    agent_run_id: str,
    generation_run_id: str,
  ) -> int:
    if not agent_run_id or not generation_run_id:
      return 0
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          update automation_test_runs
          set generation_run_id = %s
          where agent_run_id = %s and generation_run_id is null
          """,
          (generation_run_id, agent_run_id),
        )
        return max(0, int(cursor.rowcount or 0))

  def create_automation_test_run(
    self,
    project_id: str,
    user: UserContext,
    *,
    operation: str,
    scope: str,
    chat_session_id: str | None = None,
    generation_run_id: str | None = None,
    agent_run_id: str | None = None,
    project_version_id: str | None = None,
    changed_paths: list[str] | None = None,
    affected_routes: list[str] | None = None,
    test_scope: dict[str, Any] | None = None,
  ) -> dict[str, Any]:
    project = require_project(self, project_id, user)
    ensure_project_write(user, project)
    if operation not in {"generation", "update"}:
      raise StorageError("Automation test operation must be generation or update.")
    if scope not in {"full", "targeted"}:
      raise StorageError("Automation test scope must be full or targeted.")
    run_id = new_id()
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          insert into automation_test_runs (
            id, project_id, user_id, chat_session_id, generation_run_id, agent_run_id,
            project_version_id, operation, scope, status, changed_paths_json,
            affected_routes_json, test_scope_json
          )
          values (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'running', %s::jsonb, %s::jsonb, %s::jsonb)
          returning *
          """,
          (
            run_id,
            project_id,
            user.id,
            chat_session_id,
            generation_run_id,
            agent_run_id,
            project_version_id,
            operation,
            scope,
            json_dumps_safe(changed_paths or [], context="automation_test_run.changed_paths"),
            json_dumps_safe(affected_routes or [], context="automation_test_run.affected_routes"),
            json_dumps_safe(test_scope or {}, context="automation_test_run.test_scope"),
          ),
        )
        row = cursor.fetchone()
    self.add_event(project_id, user.id, "automation.test.started", {"test_run_id": run_id, "operation": operation, "scope": scope})
    return serialize_row(row)

  def complete_automation_test_run(
    self,
    test_run_id: str,
    user: UserContext,
    *,
    status: str,
    summary: str = "",
    results: dict[str, Any] | None = None,
    generation_run_id: str | None = None,
  ) -> dict[str, Any]:
    run = self.get_automation_test_run(test_run_id, user)
    if not run:
      raise StorageError("Automation test run not found.")
    project = require_project(self, str(run["project_id"]), user)
    ensure_project_write(user, project)
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          update automation_test_runs
          set status = %s,
              summary = %s,
              results_json = %s::jsonb,
              generation_run_id = coalesce(%s, generation_run_id),
              completed_at = now()
          where id = %s
          returning *
          """,
          (
            status,
            summary,
            json_dumps_safe(results or {}, context="automation_test_run.results"),
            generation_run_id,
            test_run_id,
          ),
        )
        row = cursor.fetchone()
    self.add_event(str(run["project_id"]), user.id, f"automation.test.{status}", {"test_run_id": test_run_id})
    return serialize_row(row)

  def create_screenshot_artifact(
    self,
    project_id: str,
    user: UserContext,
    *,
    test_run_id: str,
    phase: str,
    route: str,
    viewport_name: str,
    width: int,
    height: int,
    storage_path: str,
    sha256: str,
    size_bytes: int,
    chat_session_id: str | None = None,
    project_version_id: str | None = None,
    source_artifact_id: str | None = None,
    is_baseline: bool = False,
    metadata: dict[str, Any] | None = None,
  ) -> dict[str, Any]:
    project = require_project(self, project_id, user)
    ensure_project_write(user, project)
    if phase not in {"before", "after", "diff", "baseline"}:
      raise StorageError("Unsupported screenshot phase.")
    artifact_id = new_id()
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          insert into screenshot_artifacts (
            id, test_run_id, project_id, user_id, chat_session_id, project_version_id,
            source_artifact_id, phase, route, viewport_name, width, height, storage_path,
            sha256, size_bytes, is_baseline, metadata_json
          )
          values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
          returning *
          """,
          (
            artifact_id,
            test_run_id,
            project_id,
            user.id,
            chat_session_id,
            project_version_id,
            source_artifact_id,
            phase,
            route or "/",
            viewport_name,
            max(1, int(width)),
            max(1, int(height)),
            storage_path,
            sha256,
            max(0, int(size_bytes)),
            bool(is_baseline),
            json_dumps_safe(metadata or {}, context="screenshot_artifact.metadata"),
          ),
        )
        row = cursor.fetchone()
    return serialize_row(row)

  def create_visual_comparison(
    self,
    project_id: str,
    user: UserContext,
    *,
    test_run_id: str,
    after_artifact_id: str,
    route: str,
    viewport_name: str,
    status: str,
    changed: bool,
    before_artifact_id: str | None = None,
    diff_artifact_id: str | None = None,
    difference_ratio: float | None = None,
    threshold: float | None = None,
    changed_regions: list[dict[str, Any]] | None = None,
    layout_issues: list[dict[str, Any]] | None = None,
    metadata: dict[str, Any] | None = None,
  ) -> dict[str, Any]:
    project = require_project(self, project_id, user)
    ensure_project_write(user, project)
    comparison_id = new_id()
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          insert into visual_comparisons (
            id, test_run_id, project_id, before_artifact_id, after_artifact_id,
            diff_artifact_id, route, viewport_name, status, changed, difference_ratio,
            threshold, changed_regions_json, layout_issues_json, metadata_json
          )
          values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb)
          returning *
          """,
          (
            comparison_id,
            test_run_id,
            project_id,
            before_artifact_id,
            after_artifact_id,
            diff_artifact_id,
            route or "/",
            viewport_name,
            status,
            bool(changed),
            difference_ratio,
            threshold,
            json_dumps_safe(changed_regions or [], context="visual_comparison.changed_regions"),
            json_dumps_safe(layout_issues or [], context="visual_comparison.layout_issues"),
            json_dumps_safe(metadata or {}, context="visual_comparison.metadata"),
          ),
        )
        row = cursor.fetchone()
    return serialize_row(row)

  def get_automation_test_run(self, test_run_id: str, user: UserContext) -> dict[str, Any] | None:
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute("select * from automation_test_runs where id = %s", (test_run_id,))
        row = cursor.fetchone()
    if not row:
      return None
    project = require_project(self, str(row["project_id"]), user)
    ensure_project_read(user, project)
    return serialize_row(row)

  def list_automation_test_runs(
    self,
    project_id: str,
    user: UserContext,
    *,
    chat_session_id: str | None = None,
    limit: int = 50,
  ) -> list[dict[str, Any]]:
    project = require_project(self, project_id, user)
    ensure_project_read(user, project)
    safe_limit = max(1, min(int(limit), 200))
    with self.connect() as conn:
      with conn.cursor() as cursor:
        if chat_session_id:
          cursor.execute(
            """
            select * from automation_test_runs
            where project_id = %s and chat_session_id = %s
            order by started_at desc limit %s
            """,
            (project_id, chat_session_id, safe_limit),
          )
        else:
          cursor.execute(
            "select * from automation_test_runs where project_id = %s order by started_at desc limit %s",
            (project_id, safe_limit),
          )
        rows = cursor.fetchall()
    return [serialize_row(row) for row in rows]

  def list_test_run_screenshots(
    self,
    test_run_id: str,
    user: UserContext,
  ) -> list[dict[str, Any]]:
    run = self.get_automation_test_run(test_run_id, user)
    if not run:
      return []
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          "select * from screenshot_artifacts where test_run_id = %s order by route, viewport_name, created_at",
          (test_run_id,),
        )
        rows = cursor.fetchall()
    return [serialize_row(row) for row in rows]

  def get_screenshot_artifact(self, artifact_id: str, user: UserContext) -> dict[str, Any] | None:
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute("select * from screenshot_artifacts where id = %s", (artifact_id,))
        row = cursor.fetchone()
    if not row:
      return None
    project = require_project(self, str(row["project_id"]), user)
    ensure_project_read(user, project)
    return serialize_row(row)

  def latest_baseline_screenshot(
    self,
    project_id: str,
    user: UserContext,
    *,
    route: str,
    viewport_name: str,
  ) -> dict[str, Any] | None:
    project = require_project(self, project_id, user)
    ensure_project_read(user, project)
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          select * from screenshot_artifacts
          where project_id = %s and route = %s and viewport_name = %s and is_baseline = true
          order by created_at desc limit 1
          """,
          (project_id, route or "/", viewport_name),
        )
        row = cursor.fetchone()
    return serialize_row(row) if row else None
