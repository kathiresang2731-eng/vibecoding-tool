from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import HTTPException

try:
  from ..storage import StorageError, UserContext
except ImportError:
  from storage import StorageError, UserContext


def list_automation_tests_payload(
  store: Any,
  user: UserContext,
  *,
  project_id: str,
  chat_session_id: str | None = None,
  limit: int = 50,
) -> dict[str, Any]:
  try:
    runs = store.list_automation_test_runs(
      project_id,
      user,
      chat_session_id=chat_session_id,
      limit=limit,
    )
  except StorageError as exc:
    raise HTTPException(status_code=404, detail=str(exc)) from exc
  return {"project_id": project_id, "chat_session_id": chat_session_id, "test_runs": runs}


def automation_test_detail_payload(
  store: Any,
  user: UserContext,
  *,
  project_id: str,
  test_run_id: str,
) -> dict[str, Any]:
  try:
    run = store.get_automation_test_run(test_run_id, user)
    if not run or str(run.get("project_id") or "") != project_id:
      raise HTTPException(status_code=404, detail="Automation test run not found.")
    screenshots = store.list_test_run_screenshots(test_run_id, user)
  except StorageError as exc:
    raise HTTPException(status_code=404, detail=str(exc)) from exc
  public_screenshots = [
    {
      **{key: value for key, value in screenshot.items() if key != "storage_path"},
      "content_url": f"/api/screenshots/{screenshot['id']}",
    }
    for screenshot in screenshots
  ]
  return {"test_run": run, "screenshots": public_screenshots}


def resolve_screenshot_file(
  store: Any,
  settings: Any,
  user: UserContext,
  *,
  artifact_id: str,
) -> Path:
  try:
    artifact = store.get_screenshot_artifact(artifact_id, user)
  except StorageError as exc:
    raise HTTPException(status_code=404, detail=str(exc)) from exc
  if not artifact:
    raise HTTPException(status_code=404, detail="Screenshot not found.")
  configured_root = getattr(settings, "screenshot_storage_root", None)
  if configured_root:
    root = Path(configured_root).expanduser().resolve()
  else:
    root = Path(getattr(settings, "app_root", Path.cwd())).resolve() / ".data" / "screenshots"
  path = Path(str(artifact.get("storage_path") or "")).expanduser().resolve()
  if root != path and root not in path.parents:
    raise HTTPException(status_code=403, detail="Screenshot path is outside the configured storage root.")
  if not path.is_file():
    raise HTTPException(status_code=404, detail="Screenshot file is unavailable.")
  return path
