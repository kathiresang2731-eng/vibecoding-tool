"""Deterministic checks and repairs for local JavaScript module contracts."""

from __future__ import annotations

import posixpath
import re
from typing import Any


SOURCE_EXTENSIONS = (".jsx", ".tsx", ".js", ".ts", ".mjs", ".cjs")
IMPORT_FROM_RE = re.compile(
  r"(?P<prefix>\bimport\s+)"
  r"(?P<clause>[^;]+?)"
  r"(?P<from>\s+from\s+)"
  r"(?P<quote>[\"'])"
  r"(?P<specifier>\.[^\"']*)"
  r"(?P=quote)"
  r"(?P<semi>\s*;?)",
  re.MULTILINE,
)
IDENTIFIER_RE = re.compile(r"^[A-Za-z_$][\w$]*$")


def module_exports(content: str) -> tuple[bool, set[str]]:
  code = str(content or "")
  has_default = bool(re.search(r"\bexport\s+default\b", code))
  named: set[str] = set()
  for match in re.finditer(
    r"\bexport\s+(?!default\b)(?:declare\s+)?(?:async\s+)?"
    r"(?:function|class|const|let|var)\s+([A-Za-z_$][\w$]*)",
    code,
  ):
    named.add(match.group(1))
  for match in re.finditer(r"\bexport\s*\{([^}]+)\}", code, re.DOTALL):
    for item in match.group(1).split(","):
      public_name = re.split(r"\s+as\s+", item.strip())[-1].strip()
      if IDENTIFIER_RE.fullmatch(public_name):
        named.add(public_name)
  return has_default, named


def resolve_relative_module_path(
  importer_path: str,
  specifier: str,
  available_paths: set[str],
) -> str | None:
  importer_dir = posixpath.dirname(str(importer_path or "").replace("\\", "/"))
  base = posixpath.normpath(posixpath.join(importer_dir, specifier))
  candidates = [base]
  if not base.endswith(SOURCE_EXTENSIONS):
    candidates.extend(f"{base}{extension}" for extension in SOURCE_EXTENSIONS)
    candidates.extend(posixpath.join(base, f"index{extension}") for extension in SOURCE_EXTENSIONS)
  for candidate in candidates:
    if candidate in available_paths:
      return candidate
  return None


def _single_named_import(clause: str) -> tuple[str, str] | None:
  stripped = clause.strip()
  if not (stripped.startswith("{") and stripped.endswith("}")):
    return None
  items = [item.strip() for item in stripped[1:-1].split(",") if item.strip()]
  if len(items) != 1:
    return None
  parts = re.split(r"\s+as\s+", items[0])
  imported_name = parts[0].strip()
  local_name = parts[-1].strip()
  if not IDENTIFIER_RE.fullmatch(imported_name) or not IDENTIFIER_RE.fullmatch(local_name):
    return None
  return imported_name, local_name


def _single_default_import(clause: str) -> str | None:
  stripped = clause.strip()
  if any(marker in stripped for marker in ("{", "}", ",", "*")):
    return None
  return stripped if IDENTIFIER_RE.fullmatch(stripped) else None


def normalize_relative_import_export_contracts(
  files: list[dict[str, Any]],
) -> tuple[list[dict[str, str]], list[str], list[dict[str, str]]]:
  normalized = [
    {"path": str(item.get("path") or ""), "content": str(item.get("content") or "")}
    for item in files
    if isinstance(item, dict) and item.get("path")
  ]
  content_by_path = {item["path"]: item["content"] for item in normalized}
  available_paths = set(content_by_path)
  changed_paths: list[str] = []
  repairs: list[dict[str, str]] = []

  for item in normalized:
    importer_path = item["path"]
    if not importer_path.endswith(SOURCE_EXTENSIONS):
      continue

    def replace_import(match: re.Match[str]) -> str:
      specifier = match.group("specifier")
      target_path = resolve_relative_module_path(importer_path, specifier, available_paths)
      if not target_path:
        return match.group(0)
      has_default, named_exports = module_exports(content_by_path[target_path])
      clause = match.group("clause")

      named_import = _single_named_import(clause)
      if named_import:
        imported_name, local_name = named_import
        if imported_name not in named_exports and has_default:
          repairs.append(
            {
              "importer": importer_path,
              "target": target_path,
              "symbol": imported_name,
              "repair": "named_to_default",
            }
          )
          return (
            f"{match.group('prefix')}{local_name}{match.group('from')}"
            f"{match.group('quote')}{specifier}{match.group('quote')}{match.group('semi')}"
          )

      default_import = _single_default_import(clause)
      if default_import and not has_default and default_import in named_exports:
        repairs.append(
          {
            "importer": importer_path,
            "target": target_path,
            "symbol": default_import,
            "repair": "default_to_named",
          }
        )
        return (
          f"{match.group('prefix')}{{ {default_import} }}{match.group('from')}"
          f"{match.group('quote')}{specifier}{match.group('quote')}{match.group('semi')}"
        )
      return match.group(0)

    updated = IMPORT_FROM_RE.sub(replace_import, item["content"])
    if updated != item["content"]:
      item["content"] = updated
      content_by_path[importer_path] = updated
      changed_paths.append(importer_path)

  return normalized, list(dict.fromkeys(changed_paths)), repairs
