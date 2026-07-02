from __future__ import annotations

from pathlib import Path
from typing import Any

from .constants import MAX_LOCAL_FILE_BYTES
from .content import (
  encode_file_as_data_url,
  is_binary_project_asset,
  normalize_file_content,
  write_project_file_content,
)
from .errors import LocalWorkspaceError
from .paths import normalize_project_file_path, safe_project_file, should_ignore


def read_local_project_files(root: Path) -> list[dict[str, str]]:
  if not root.exists():
    raise LocalWorkspaceError(f"Local path does not exist: {root}")
  if not root.is_dir():
    raise LocalWorkspaceError(f"Local path is not a folder: {root}")

  files: list[dict[str, str]] = []
  for path in sorted(root.rglob("*")):
    if not path.is_file() or should_ignore(path, root):
      continue
    relative_path = path.relative_to(root).as_posix()
    try:
      normalized_path = normalize_project_file_path(relative_path)
    except LocalWorkspaceError:
      continue
    if path.stat().st_size > MAX_LOCAL_FILE_BYTES:
      raise LocalWorkspaceError(f"Local file is too large to import: {normalized_path}")
    if is_binary_project_asset(normalized_path):
      content = encode_file_as_data_url(path, normalized_path)
    else:
      try:
        content = path.read_text(encoding="utf-8")
      except UnicodeDecodeError as exc:
        raise LocalWorkspaceError(f"Local file is not UTF-8 text: {normalized_path}") from exc
    files.append({"path": normalized_path, "content": content})
  return files


def write_local_project_files(
  root: Path,
  files: list[dict[str, Any]],
  *,
  prune_missing: bool = False,
  allow_prune_missing: bool = False,
) -> int:
  if prune_missing and not allow_prune_missing:
    raise LocalWorkspaceError("Destructive local sync requires allow_prune_missing=true.")
  root.mkdir(parents=True, exist_ok=True)
  snapshot = snapshot_local_project_files(root, include_all=prune_missing, files=files)
  count = 0
  written_paths: set[str] = set()
  try:
    for file_item in files:
      path = normalize_project_file_path(str(file_item.get("path", "")))
      content = normalize_file_content(file_item)
      destination = safe_project_file(root, path)
      destination.parent.mkdir(parents=True, exist_ok=True)
      write_project_file_content(destination, path, content)
      written_paths.add(path)
      count += 1

    if prune_missing:
      prune_missing_project_files(root, written_paths)
    return count
  except Exception:
    restore_local_project_files(root, snapshot)
    raise


def snapshot_local_project_files(
  root: Path,
  *,
  include_all: bool,
  files: list[dict[str, Any]],
) -> dict[str, bytes | None]:
  paths: set[str] = set()
  if include_all and root.exists():
    for path in sorted(root.rglob("*")):
      if not path.is_file() or should_ignore(path, root):
        continue
      try:
        paths.add(normalize_project_file_path(path.relative_to(root).as_posix()))
      except LocalWorkspaceError:
        continue
  for file_item in files:
    try:
      paths.add(normalize_project_file_path(str(file_item.get("path", ""))))
    except LocalWorkspaceError:
      continue

  snapshot: dict[str, bytes | None] = {}
  for path in paths:
    destination = safe_project_file(root, path)
    snapshot[path] = destination.read_bytes() if destination.exists() and destination.is_file() else None
  return snapshot


def restore_local_project_files(root: Path, snapshot: dict[str, bytes | None]) -> None:
  for path, content in snapshot.items():
    destination = safe_project_file(root, path)
    if content is None:
      if destination.exists() and destination.is_file():
        destination.unlink()
      continue
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
  remove_empty_project_directories(root)


def prune_missing_project_files(root: Path, desired_paths: set[str]) -> int:
  if not root.exists():
    return 0

  pruned = 0
  for path in sorted(root.rglob("*"), reverse=True):
    if not path.is_file() or should_ignore(path, root):
      continue
    relative_path = path.relative_to(root).as_posix()
    try:
      normalized_path = normalize_project_file_path(relative_path)
    except LocalWorkspaceError:
      continue
    if normalized_path in desired_paths:
      continue
    path.unlink()
    pruned += 1

  remove_empty_project_directories(root)
  return pruned


def remove_empty_project_directories(root: Path) -> None:
  if not root.exists():
    return
  for path in sorted((item for item in root.rglob("*") if item.is_dir()), reverse=True):
    if should_ignore(path, root):
      continue
    try:
      path.rmdir()
    except OSError:
      continue
