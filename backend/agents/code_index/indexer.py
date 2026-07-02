from __future__ import annotations

import hashlib
import re
from typing import Any

_CODE_EXTENSIONS = (".js", ".jsx", ".ts", ".tsx", ".css", ".html", ".json")


def _content_hash(content: str) -> str:
  return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def chunk_file(path: str, content: str, *, project_id: str = "") -> list[dict[str, Any]]:
  """Split a source file into coarse semantic chunks (exports, functions, components)."""
  if not content.strip():
    return []
  if not path.endswith(_CODE_EXTENSIONS):
    return []

  chunks: list[dict[str, Any]] = []
  lines = content.splitlines()
  pattern = re.compile(
    r"^(export\s+)?(default\s+)?(function|const|class)\s+([A-Za-z_$][\w$]*)",
    re.MULTILINE,
  )
  matches = list(pattern.finditer(content))
  if not matches:
    chunks.append(
      {
        "project_id": project_id,
        "path": path,
        "symbol": path.rsplit("/", 1)[-1],
        "line_start": 1,
        "line_end": len(lines),
        "content": content[:8000],
        "content_hash": _content_hash(content),
      }
    )
    return chunks

  for index, match in enumerate(matches):
    start = content[: match.start()].count("\n") + 1
    end = (
      content[: matches[index + 1].start()].count("\n") + 1
      if index + 1 < len(matches)
      else len(lines)
    )
    symbol = match.group(4) or path.rsplit("/", 1)[-1]
    slice_lines = lines[max(0, start - 1) : end]
    chunk_content = "\n".join(slice_lines)
    chunks.append(
      {
        "project_id": project_id,
        "path": path,
        "symbol": symbol,
        "line_start": start,
        "line_end": end,
        "content": chunk_content[:8000],
        "content_hash": _content_hash(chunk_content),
      }
    )
  return chunks


def chunk_project_files(
  files: list[dict[str, str]],
  *,
  project_id: str = "",
) -> list[dict[str, Any]]:
  all_chunks: list[dict[str, Any]] = []
  for item in files:
    path = str(item.get("path") or "")
    content = str(item.get("content") or "")
    if not path:
      continue
    all_chunks.extend(chunk_file(path, content, project_id=project_id))
  return all_chunks
