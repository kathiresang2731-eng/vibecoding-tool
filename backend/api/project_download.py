from __future__ import annotations

import io
import re
import zipfile
from typing import Any


def _safe_zip_path(path: str) -> str:
  normalized = str(path or "").strip().replace("\\", "/")
  while normalized.startswith("/"):
    normalized = normalized[1:]
  if not normalized or ".." in normalized.split("/"):
    raise ValueError(f"Unsafe archive path: {path}")
  return normalized


def build_project_zip(files: list[dict[str, Any]], *, project_name: str = "project") -> bytes:
  buffer = io.BytesIO()
  with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
    for item in files:
      if not isinstance(item, dict):
        continue
      path = _safe_zip_path(str(item.get("path") or ""))
      content = item.get("content")
      if content is None:
        content = item.get("code")
      if not isinstance(content, str):
        content = str(content or "")
      archive.writestr(path, content)
  buffer.seek(0)
  return buffer.getvalue()


def safe_download_filename(project_name: str) -> str:
  slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(project_name or "project").strip()).strip("-._")
  return (slug or "project")[:80]
