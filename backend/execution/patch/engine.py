"""Patch-first file edit engine (Codex apply_patch / Cursor Composer parity)."""

from __future__ import annotations

import re
from typing import Any

try:
  from ...agents.artifacts.paths import normalize_artifact_path
except ImportError:
  from agents.artifacts.paths import normalize_artifact_path

from .errors import PatchEngineError


_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", re.MULTILINE)


def apply_unified_patch(*, path: str, original_content: str, unified_diff: str) -> str:
  """Apply a unified diff to file content. Raises PatchEngineError on mismatch."""
  cleaned_path = normalize_artifact_path(path)
  if not unified_diff.strip():
    raise PatchEngineError(f"Empty patch for {cleaned_path}.")
  lines = original_content.splitlines()
  patch_lines = unified_diff.replace("\r\n", "\n").splitlines()
  cursor = 0
  output: list[str] = []
  hunk_started = False

  for raw_line in patch_lines:
    if raw_line.startswith("---") or raw_line.startswith("+++"):
      continue
    if raw_line.startswith("@@"):
      match = _HUNK_RE.match(raw_line)
      if not match:
        raise PatchEngineError(f"Invalid hunk header for {cleaned_path}: {raw_line}")
      old_start = max(int(match.group(1)) - 1, 0)
      if old_start > len(lines):
        raise PatchEngineError(f"Patch hunk starts beyond file end for {cleaned_path}.")
      output.extend(lines[cursor:old_start])
      cursor = old_start
      hunk_started = True
      continue
    if not hunk_started:
      continue
    if raw_line.startswith(" "):
      expected = raw_line[1:]
      if cursor >= len(lines) or lines[cursor] != expected:
        raise PatchEngineError(f"Patch context mismatch in {cleaned_path} at line {cursor + 1}.")
      output.append(lines[cursor])
      cursor += 1
    elif raw_line.startswith("-"):
      expected = raw_line[1:]
      if cursor >= len(lines) or lines[cursor] != expected:
        raise PatchEngineError(f"Patch removal mismatch in {cleaned_path} at line {cursor + 1}.")
      cursor += 1
    elif raw_line.startswith("+"):
      output.append(raw_line[1:])
    elif raw_line == r"\ No newline at end of file":
      continue
    else:
      raise PatchEngineError(f"Unsupported patch line in {cleaned_path}: {raw_line[:120]}")

  output.extend(lines[cursor:])
  return "\n".join(output)


def apply_patches_to_files(
  files: list[dict[str, Any]],
  patches: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
  file_map = {str(item.get("path") or "").strip(): str(item.get("content") or "") for item in files if isinstance(item, dict)}
  applied: list[dict[str, Any]] = []
  stats = {"additions": 0, "deletions": 0, "paths": []}

  for patch in patches:
    if not isinstance(patch, dict):
      raise PatchEngineError("Each patch must be an object.")
    path = str(patch.get("path") or "").strip()
    if not path:
      raise PatchEngineError("Patch path is required.")
    normalize_artifact_path(path)
    unified_diff = str(patch.get("unified_diff") or patch.get("diff") or "").strip()
    if not unified_diff:
      raise PatchEngineError(f"Patch for {path} is missing unified_diff.")
    original = file_map.get(path, "")
    updated = apply_unified_patch(path=path, original_content=original, unified_diff=unified_diff)
    before_lines = original.splitlines()
    after_lines = updated.splitlines()
    stats["additions"] += max(len(after_lines) - len(before_lines), 0)
    stats["deletions"] += max(len(before_lines) - len(after_lines), 0)
    file_map[path] = updated
    applied.append({"path": path, "status": "applied"})
    stats["paths"].append(path)

  merged = [{"path": path, "content": content} for path, content in sorted(file_map.items())]
  return merged, {"applied": applied, "diff_stats": stats}
