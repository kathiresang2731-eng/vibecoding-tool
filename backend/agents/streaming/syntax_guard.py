"""Lightweight syntax guards before staging or persisting generated source files."""

from __future__ import annotations

import re
from typing import Any


def syntax_issues_for_content(path: str, content: str) -> list[str]:
  normalized_path = str(path or "").strip()
  if not normalized_path.endswith((".jsx", ".tsx", ".js", ".ts", ".mjs", ".cjs")):
    return []
  code = str(content or "")
  if not code.strip():
    return [f"{normalized_path}: file is empty"]
  issues: list[str] = []
  if code.count("{") != code.count("}"):
    issues.append(f"{normalized_path}: unbalanced '{{' / '}}' braces")
  if code.count("(") != code.count(")"):
    issues.append(f"{normalized_path}: unbalanced '(' / ')' parentheses")
  if code.count("[") != code.count("]"):
    issues.append(f"{normalized_path}: unbalanced '[' / ']' brackets")
  if normalized_path.endswith((".jsx", ".tsx")):
    if "export default" not in code and "module.exports" not in code:
      issues.append(f"{normalized_path}: missing export default")
    if re.search(r"element=\{<[^/>]{1,60}$", code, flags=re.MULTILINE):
      issues.append(f"{normalized_path}: incomplete JSX element (truncated route/component)")
    if re.search(r"<\s*[A-Z][A-Za-z0-9_]*\s*$", code, flags=re.MULTILINE):
      issues.append(f"{normalized_path}: incomplete JSX tag")
  return issues


def guard_syntax_write(path: str, content: str) -> dict[str, Any] | None:
  issues = syntax_issues_for_content(path, content)
  if not issues:
    return None
  return {
    "error": (
      f"Syntax check failed for {path}: {issues[0]}. "
      "Fix the code and retry write_file or str_replace. Do not persist broken files."
    ),
    "path": path,
    "recoverable": True,
    "syntax_blocked": True,
    "issues": issues,
  }


def find_syntax_issues_in_payload(files: list[dict[str, Any]]) -> list[str]:
  issues: list[str] = []
  for item in files:
    if not isinstance(item, dict):
      continue
    path = str(item.get("path") or "")
    content = str(item.get("content") or "")
    blocked = guard_syntax_write(path, content)
    if blocked:
      issues.extend(str(issue) for issue in (blocked.get("issues") or []) if issue)
  return issues
