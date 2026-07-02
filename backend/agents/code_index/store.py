from __future__ import annotations

from typing import Any

try:
  from ..memory.episode_embeddings import embed_episode_text
except ImportError:
  from agents.memory.episode_embeddings import embed_episode_text

_PROJECT_INDEX: dict[str, list[dict[str, Any]]] = {}


def get_project_chunks(project_id: str) -> list[dict[str, Any]]:
  return list(_PROJECT_INDEX.get(str(project_id or ""), []))


def set_project_chunks(project_id: str, chunks: list[dict[str, Any]]) -> None:
  _PROJECT_INDEX[str(project_id or "")] = list(chunks)


def upsert_file_chunks(
  project_id: str,
  path: str,
  chunks: list[dict[str, Any]],
) -> None:
  pid = str(project_id or "")
  existing = [item for item in get_project_chunks(pid) if item.get("path") != path]
  embedded: list[dict[str, Any]] = []
  for chunk in chunks:
    text = f"{chunk.get('path')} {chunk.get('symbol')} {chunk.get('content', '')[:2000]}"
    embedded.append({**chunk, "embedding": embed_episode_text(text)})
  set_project_chunks(pid, [*existing, *embedded])


def remove_file_chunks(project_id: str, path: str) -> None:
  pid = str(project_id or "")
  set_project_chunks(pid, [item for item in get_project_chunks(pid) if item.get("path") != path])
