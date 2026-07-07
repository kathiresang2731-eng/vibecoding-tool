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
  r"(?P<specifier>(?:\.{1,2}/|/src/|src/|@/)[^\"']*)"
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


def module_local_bindings(content: str) -> set[str]:
  code = str(content or "")
  bindings: set[str] = set()
  for match in re.finditer(
    r"\b(?:const|let|var|function|class)\s+([A-Za-z_$][\w$]*)",
    code,
  ):
    bindings.add(match.group(1))
  return bindings


def default_export_identifier(content: str) -> str:
  match = re.search(r"\bexport\s+default\s+([A-Za-z_$][\w$]*)\s*;?", str(content or ""))
  return match.group(1) if match else ""


def resolve_module_path(
  importer_path: str,
  specifier: str,
  available_paths: set[str],
) -> str | None:
  normalized_specifier = str(specifier or "").replace("\\", "/")
  if normalized_specifier.startswith(("./", "../")):
    importer_dir = posixpath.dirname(str(importer_path or "").replace("\\", "/"))
    base = posixpath.normpath(posixpath.join(importer_dir, normalized_specifier))
  elif normalized_specifier.startswith("/src/"):
    base = normalized_specifier.lstrip("/")
  elif normalized_specifier.startswith("src/"):
    base = normalized_specifier
  elif normalized_specifier.startswith("@/"):
    base = posixpath.normpath(posixpath.join("src", normalized_specifier[2:]))
  else:
    base = normalized_specifier.lstrip("/")
  candidates = [base]
  if not base.endswith(SOURCE_EXTENSIONS):
    candidates.extend(f"{base}{extension}" for extension in SOURCE_EXTENSIONS)
    candidates.extend(posixpath.join(base, f"index{extension}") for extension in SOURCE_EXTENSIONS)
  for candidate in candidates:
    if candidate in available_paths:
      return candidate
  return None


def resolve_relative_module_path(
  importer_path: str,
  specifier: str,
  available_paths: set[str],
) -> str | None:
  return resolve_module_path(importer_path, specifier, available_paths)


def _named_imports(clause: str) -> list[tuple[str, str]]:
  match = re.search(r"\{(?P<body>[^}]+)\}", str(clause or ""), flags=re.DOTALL)
  if not match:
    return []
  imports: list[tuple[str, str]] = []
  for raw_item in match.group("body").split(","):
    item = raw_item.strip()
    if not item:
      continue
    item = re.sub(r"^(?:type\s+)", "", item).strip()
    parts = re.split(r"\s+as\s+", item)
    imported_name = parts[0].strip()
    local_name = parts[-1].strip()
    if IDENTIFIER_RE.fullmatch(imported_name) and IDENTIFIER_RE.fullmatch(local_name):
      imports.append((imported_name, local_name))
  return imports


def _single_named_import(clause: str) -> tuple[str, str] | None:
  stripped = clause.strip()
  if not (stripped.startswith("{") and stripped.endswith("}")):
    return None
  imports = _named_imports(stripped)
  if len(imports) != 1:
    return None
  return imports[0]


def _single_default_import(clause: str) -> str | None:
  stripped = clause.strip()
  if any(marker in stripped for marker in ("{", "}", ",", "*")):
    return None
  return stripped if IDENTIFIER_RE.fullmatch(stripped) else None


def _identifier_key(name: str) -> str:
  key = re.sub(r"[^a-z0-9]", "", str(name or "").lower())
  for suffix in ("data", "items", "list", "records", "entries", "content", "collection"):
    if key.endswith(suffix) and len(key) > len(suffix) + 2:
      key = key[: -len(suffix)]
      break
  if key.endswith("ies") and len(key) > 4:
    key = f"{key[:-3]}y"
  elif key.endswith("s") and len(key) > 4:
    key = key[:-1]
  return key


def _best_alias_source(
  imported_name: str,
  *,
  named_exports: set[str],
  local_bindings: set[str],
  default_identifier: str,
) -> str:
  if imported_name in local_bindings:
    return imported_name
  candidates = sorted(named_exports | local_bindings)
  imported_key = _identifier_key(imported_name)
  for candidate in candidates:
    if _identifier_key(candidate) == imported_key:
      return candidate
  for candidate in candidates:
    candidate_key = _identifier_key(candidate)
    if imported_key and candidate_key and (imported_key in candidate_key or candidate_key in imported_key):
      return candidate
  return default_identifier if default_identifier in local_bindings else ""


def _append_named_export_aliases(content: str, aliases: list[tuple[str, str]]) -> str:
  unique_aliases = list(dict.fromkeys(aliases))
  statements = []
  for source_name, public_name in unique_aliases:
    if not IDENTIFIER_RE.fullmatch(source_name) or not IDENTIFIER_RE.fullmatch(public_name):
      continue
    statement = f"export {{ {source_name}{f' as {public_name}' if source_name != public_name else ''} }};"
    if statement not in content:
      statements.append(statement)
  if not statements:
    return content
  return f"{content.rstrip()}\n\n" + "\n".join(statements) + "\n"


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
  pending_target_aliases: dict[str, list[tuple[str, str]]] = {}

  for item in normalized:
    importer_path = item["path"]
    if not importer_path.endswith(SOURCE_EXTENSIONS):
      continue

    def replace_import(match: re.Match[str]) -> str:
      specifier = match.group("specifier")
      target_path = resolve_module_path(importer_path, specifier, available_paths)
      if not target_path:
        return match.group(0)
      target_content = content_by_path[target_path]
      has_default, named_exports = module_exports(target_content)
      local_bindings = module_local_bindings(target_content)
      default_identifier = default_export_identifier(target_content)
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

      for imported_name, _local_name in _named_imports(clause):
        if imported_name in named_exports:
          continue
        alias_source = _best_alias_source(
          imported_name,
          named_exports=named_exports,
          local_bindings=local_bindings,
          default_identifier=default_identifier,
        )
        if alias_source:
          pending_target_aliases.setdefault(target_path, []).append((alias_source, imported_name))
          named_exports.add(imported_name)
          repairs.append(
            {
              "importer": importer_path,
              "target": target_path,
              "symbol": imported_name,
              "repair": "add_named_export_alias",
            }
          )
          continue

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

  for target_path, aliases in pending_target_aliases.items():
    current = content_by_path.get(target_path, "")
    updated = _append_named_export_aliases(current, aliases)
    if updated != current:
      content_by_path[target_path] = updated
      changed_paths.append(target_path)
      repairs.append(
        {
          "importer": "",
          "target": target_path,
          "symbol": ", ".join(public for _source, public in aliases),
          "repair": "persist_named_export_aliases",
        }
      )

  for item in normalized:
    if item["path"] in content_by_path:
      item["content"] = content_by_path[item["path"]]

  return normalized, list(dict.fromkeys(changed_paths)), repairs
