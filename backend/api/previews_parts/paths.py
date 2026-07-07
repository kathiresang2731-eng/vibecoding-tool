from __future__ import annotations


def preview_base_path(project_id: str, version_id: str) -> str:
  return f"/api/previews/{project_id.strip()}/{version_id.strip()}/"

