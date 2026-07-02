from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any


SAFE_SEGMENT_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def safe_storage_segment(value: str, *, fallback: str) -> str:
  cleaned = SAFE_SEGMENT_RE.sub("-", str(value or "").strip()).strip(".-")
  return cleaned[:120] or fallback


def route_storage_segment(route: str) -> str:
  normalized = str(route or "/").strip() or "/"
  readable = safe_storage_segment(normalized.strip("/").replace("/", "-"), fallback="root")
  digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:10]
  return f"{readable}-{digest}"


def screenshot_run_directory(
  settings: Any,
  *,
  project_id: str,
  chat_session_id: str | None,
  test_run_id: str,
  phase: str,
  route: str = "/",
) -> Path:
  configured = getattr(settings, "screenshot_storage_root", None)
  if configured:
    root = Path(configured).expanduser().resolve()
  else:
    app_root = Path(getattr(settings, "app_root", Path.cwd())).resolve()
    root = app_root / ".data" / "screenshots"
  target = (
    root
    / safe_storage_segment(project_id, fallback="project")
    / safe_storage_segment(chat_session_id or "no-session", fallback="no-session")
    / safe_storage_segment(test_run_id, fallback="test-run")
    / safe_storage_segment(phase, fallback="capture")
    / route_storage_segment(route)
  )
  target.mkdir(parents=True, exist_ok=True)
  return target


def screenshot_file_metadata(path: Path) -> dict[str, Any]:
  digest = hashlib.sha256()
  with path.open("rb") as file:
    for chunk in iter(lambda: file.read(1024 * 1024), b""):
      digest.update(chunk)
  return {
    "storage_path": str(path.resolve()),
    "sha256": digest.hexdigest(),
    "size_bytes": path.stat().st_size,
  }


def screenshot_changed(before: dict[str, Any] | None, after: dict[str, Any]) -> bool | None:
  if not before:
    return None
  before_hash = str(before.get("sha256") or "")
  after_hash = str(after.get("sha256") or "")
  if not before_hash or not after_hash:
    return None
  return before_hash != after_hash
