"""Durable, project-wide UI knowledge for existing-project updates.

The records in this module are structural evidence, not an intent router.  They
tell the LLM where rendered text lives and what code is attached to that
element.  The update-analysis agent remains responsible for deciding what the
user means and which change should be made.
"""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
from typing import Any

PROJECT_KNOWLEDGE_NAMESPACE = "project_knowledge"
PROJECT_UI_KNOWLEDGE_KEY = "ui_semantics_v1"
PROJECT_UI_KNOWLEDGE_KIND = "ui_semantics"
PROJECT_UI_KNOWLEDGE_SCHEMA_VERSION = 1
MAX_UI_KNOWLEDGE_RECORDS = 600
MAX_UI_TEXT_CHARS = 240
MAX_UI_SNIPPET_CHARS = 900

SOURCE_EXTENSIONS = (".html", ".jsx", ".tsx", ".js", ".ts")
IGNORED_PARTS = frozenset({"node_modules", "dist", "build", ".git", "coverage"})
UI_ELEMENT_RE = re.compile(
  r"<(?P<tag>button|a|label|h[1-6]|th|td|p|span|li|option|legend)\b"
  r"(?P<attrs>[^>]*)>(?P<body>[\s\S]{0,3000}?)</(?P=tag)>",
  flags=re.IGNORECASE,
)
ROUTE_TAG_RE = re.compile(r"<Route\b(?P<attrs>[^>]*)>", flags=re.IGNORECASE | re.DOTALL)
ROUTE_PATH_ATTR_RE = re.compile(r"\bpath\s*=\s*['\"](?P<route>[^'\"]+)['\"]", flags=re.IGNORECASE)
ROUTE_ELEMENT_ATTR_RE = re.compile(
  r"\belement\s*=\s*\{\s*<(?P<component>[A-Za-z_$][\w$]*)",
  flags=re.IGNORECASE,
)
IMPORT_RE = re.compile(
  r"import\s+(?P<name>[A-Za-z_$][\w$]*)\s+from\s+['\"](?P<path>[^'\"]+)['\"]"
)
EVENT_ATTR_RE = re.compile(
  r"\b(?P<event>on[A-Z][A-Za-z0-9_]*)\s*=\s*\{(?P<value>[\s\S]*?)\}",
)
TARGET_ATTR_RE = re.compile(r"\b(?:to|href)\s*=\s*['\"](?P<target>[^'\"]+)['\"]")
NAVIGATE_RE = re.compile(r"\bnavigate\s*\(\s*['\"](?P<target>[^'\"]+)['\"]")
IDENTIFIER_RE = re.compile(r"^[A-Za-z_$][\w$]*$")


def _text(value: Any) -> str:
  return str(value or "").strip()


def _tool_files(files: list[dict[str, Any]] | None) -> list[dict[str, str]]:
  result: list[dict[str, str]] = []
  for item in files or []:
    if not isinstance(item, dict):
      continue
    path = _text(item.get("path")).replace("\\", "/")
    content = item.get("content")
    if not isinstance(content, str):
      content = item.get("code")
    if not path or not isinstance(content, str):
      continue
    if not path.endswith(SOURCE_EXTENSIONS):
      continue
    if any(part.lower() in IGNORED_PARTS for part in path.split("/")):
      continue
    result.append({"path": path, "content": content})
  return result


def project_knowledge_source_hash(files: list[dict[str, Any]] | None) -> str:
  digest = hashlib.sha256()
  for item in sorted(_tool_files(files), key=lambda row: row["path"]):
    digest.update(item["path"].encode("utf-8"))
    digest.update(b"\0")
    digest.update(item["content"].encode("utf-8"))
    digest.update(b"\0")
  return digest.hexdigest()[:24]


def _visible_text(value: str) -> str:
  text = re.sub(r"<[^>]+>", " ", value)
  text = re.sub(r"\{(?:[^{}]|\{[^{}]*\})*\}", " ", text)
  text = re.sub(r"&(?:amp|nbsp|lt|gt|quot|#39);", " ", text, flags=re.IGNORECASE)
  return re.sub(r"\s+", " ", text).strip(" \t\r\n:|-")


def _line_number(content: str, index: int) -> int:
  return content.count("\n", 0, max(0, index)) + 1


def _component_name(path: str, content: str) -> str:
  match = re.search(
    r"(?:export\s+default\s+)?(?:function|class|const)\s+([A-Z][A-Za-z0-9_]*)",
    content,
  )
  if match:
    return match.group(1)
  return path.rsplit("/", 1)[-1].rsplit(".", 1)[0]


def _resolve_import_path(owner_path: str, imported_path: str, known_paths: set[str]) -> str:
  if not imported_path.startswith("."):
    return ""
  owner_dir = posixpath.dirname(owner_path)
  base = posixpath.normpath(posixpath.join(owner_dir, imported_path))
  candidates = [
    base,
    *(f"{base}{suffix}" for suffix in (".jsx", ".tsx", ".js", ".ts")),
    *(f"{base}/index{suffix}" for suffix in (".jsx", ".tsx", ".js", ".ts")),
  ]
  return next((candidate for candidate in candidates if candidate in known_paths), "")


def _route_ownership(files: list[dict[str, str]]) -> tuple[dict[str, str], list[dict[str, str]]]:
  known_paths = {item["path"] for item in files}
  routes_by_path: dict[str, str] = {}
  route_records: list[dict[str, str]] = []
  for item in files:
    path = item["path"]
    content = item["content"]
    imports = {
      match.group("name"): _resolve_import_path(path, match.group("path"), known_paths)
      for match in IMPORT_RE.finditer(content)
    }
    for match in ROUTE_TAG_RE.finditer(content):
      attrs = match.group("attrs")
      path_match = ROUTE_PATH_ATTR_RE.search(attrs)
      component_match = ROUTE_ELEMENT_ATTR_RE.search(attrs)
      if not path_match or not component_match:
        continue
      route = _text(path_match.group("route"))
      component = _text(component_match.group("component"))
      component_path = imports.get(component, "")
      if component_path and component_path not in routes_by_path:
        routes_by_path[component_path] = route
      route_records.append(
        {
          "route": route,
          "component": component,
          "component_path": component_path,
          "route_owner_path": path,
        }
      )
  return routes_by_path, route_records


def _event_details(attrs: str, content: str) -> tuple[str, str, str]:
  event_match = EVENT_ATTR_RE.search(attrs)
  event = _text(event_match.group("event")) if event_match else ""
  handler = _text(event_match.group("value")) if event_match else ""
  target_match = TARGET_ATTR_RE.search(attrs)
  target = _text(target_match.group("target")) if target_match else ""
  if handler:
    navigate_match = NAVIGATE_RE.search(handler)
    if navigate_match:
      target = _text(navigate_match.group("target"))
    elif IDENTIFIER_RE.match(handler):
      handler_pattern = re.compile(
        rf"(?:function\s+{re.escape(handler)}\b|(?:const|let|var)\s+{re.escape(handler)}\s*=)"
      )
      handler_match = handler_pattern.search(content)
      if handler_match:
        excerpt = content[handler_match.start() : handler_match.start() + 1800]
        navigate_match = NAVIGATE_RE.search(excerpt)
        if navigate_match:
          target = _text(navigate_match.group("target"))
  return event, handler[:240], target[:240]


def _element_kind(tag: str) -> str:
  lowered = tag.lower()
  if lowered.startswith("h") and lowered[1:].isdigit():
    return "heading"
  return {
    "a": "link",
    "th": "table_header",
    "td": "table_cell",
    "p": "text",
    "span": "text",
    "li": "list_item",
  }.get(lowered, lowered)


def _purpose(*, kind: str, event: str, handler: str, target: str, route: str) -> str:
  if target:
    return f"Navigates or links to {target}"
  if event and handler:
    return f"Handles {event} with {handler}"
  if event:
    return f"Handles {event}"
  if kind == "heading":
    return f"Names the page or section rendered at {route or 'this component'}"
  if kind == "table_header":
    return "Labels a table column"
  if kind == "label":
    return "Labels a form control"
  return f"Rendered {kind.replace('_', ' ')} content"


def extract_project_ui_knowledge(files: list[dict[str, Any]] | None) -> dict[str, Any]:
  source_files = _tool_files(files)
  routes_by_path, route_records = _route_ownership(source_files)
  records: list[dict[str, Any]] = []
  for item in source_files:
    path = item["path"]
    content = item["content"]
    component = _component_name(path, content)
    route = routes_by_path.get(path, "")
    for match in UI_ELEMENT_RE.finditer(content):
      visible_text = _visible_text(match.group("body"))
      if len(visible_text) < 2 or len(visible_text) > MAX_UI_TEXT_CHARS:
        continue
      tag = match.group("tag").lower()
      attrs = match.group("attrs")
      event, handler, target = _event_details(attrs, content)
      start = max(0, match.start() - 180)
      end = min(len(content), match.end() + 180)
      kind = _element_kind(tag)
      records.append(
        {
          "path": path,
          "component": component,
          "route": route,
          "element_kind": kind,
          "text": visible_text,
          "event": event,
          "handler": handler,
          "target": target,
          "purpose": _purpose(
            kind=kind,
            event=event,
            handler=handler,
            target=target,
            route=route,
          ),
          "line": _line_number(content, match.start()),
          "snippet": content[start:end].strip()[:MAX_UI_SNIPPET_CHARS],
        }
      )
      if len(records) >= MAX_UI_KNOWLEDGE_RECORDS:
        break
    if len(records) >= MAX_UI_KNOWLEDGE_RECORDS:
      break
  return {
    "schema_version": PROJECT_UI_KNOWLEDGE_SCHEMA_VERSION,
    "source_hash": project_knowledge_source_hash(source_files),
    "file_count": len(source_files),
    "record_count": len(records),
    "routes": route_records[:120],
    "elements": records,
  }


def _metadata(row: dict[str, Any]) -> dict[str, Any]:
  value = row.get("metadata_json") if isinstance(row, dict) else None
  return value if isinstance(value, dict) else {}


def load_project_ui_knowledge(
  store: Any,
  user: Any,
  *,
  project_id: str,
) -> dict[str, Any] | None:
  if store is None or user is None or not hasattr(store, "list_memory_items"):
    return None
  try:
    rows = store.list_memory_items(
      user,
      project_id=project_id,
      namespace=PROJECT_KNOWLEDGE_NAMESPACE,
      kind=PROJECT_UI_KNOWLEDGE_KIND,
      limit=1,
    )
  except Exception:
    return None
  if not rows:
    return None
  row = rows[0]
  try:
    payload = json.loads(str(row.get("content") or ""))
  except (TypeError, ValueError, json.JSONDecodeError):
    return None
  if not isinstance(payload, dict):
    return None
  payload["_memory_metadata"] = _metadata(row)
  return payload


def persist_project_ui_knowledge(
  store: Any,
  user: Any,
  *,
  project_id: str,
  files: list[dict[str, Any]],
  chat_session_id: str | None = None,
  chat_topic_id: str | None = None,
  generation_run_id: str | None = None,
) -> dict[str, Any]:
  knowledge = extract_project_ui_knowledge(files)
  if store is None or user is None or not hasattr(store, "upsert_memory_item"):
    return {"status": "skipped", **knowledge}
  row = store.upsert_memory_item(
    user,
    project_id=project_id,
    namespace=PROJECT_KNOWLEDGE_NAMESPACE,
    key=PROJECT_UI_KNOWLEDGE_KEY,
    kind=PROJECT_UI_KNOWLEDGE_KIND,
    content=json.dumps(knowledge, ensure_ascii=False, separators=(",", ":")),
    metadata={
      "schema_version": PROJECT_UI_KNOWLEDGE_SCHEMA_VERSION,
      "source_hash": knowledge["source_hash"],
      "file_count": knowledge["file_count"],
      "record_count": knowledge["record_count"],
      "chat_session_id": chat_session_id,
      "chat_topic_id": chat_topic_id,
      "generation_run_id": generation_run_id,
    },
  )
  return {"status": "stored", "memory_id": row.get("id"), **knowledge}


def _tokens(value: str) -> set[str]:
  return {
    token
    for token in re.findall(r"[a-z0-9]+", _text(value).lower())
    if len(token) >= 2
  }


def _normalized(value: str) -> str:
  return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", _text(value).lower())).strip()


def select_project_ui_knowledge(
  *,
  prompt: str,
  files: list[dict[str, Any]] | None,
  store: Any = None,
  user: Any = None,
  project_id: str = "",
  limit: int = 8,
) -> list[dict[str, Any]]:
  """Retrieve structural UI evidence; the LLM still decides intent and scope."""
  knowledge = load_project_ui_knowledge(store, user, project_id=project_id) if project_id else None
  live_hash = project_knowledge_source_hash(files)
  if not knowledge or _text(knowledge.get("source_hash")) != live_hash:
    knowledge = extract_project_ui_knowledge(files)
  prompt_tokens = _tokens(prompt)
  normalized_prompt = _normalized(prompt)
  scored: list[tuple[float, dict[str, Any]]] = []
  for record in knowledge.get("elements") or []:
    if not isinstance(record, dict):
      continue
    searchable = " ".join(
      _text(record.get(key))
      for key in ("text", "component", "route", "element_kind", "purpose", "handler", "target", "path")
    )
    record_tokens = _tokens(searchable)
    overlap = len(prompt_tokens & record_tokens) / max(len(prompt_tokens), 1)
    normalized_text = _normalized(_text(record.get("text")))
    exact = 1.0 if normalized_text and normalized_text in normalized_prompt else 0.0
    path_overlap = len(prompt_tokens & _tokens(_text(record.get("path")))) / max(len(prompt_tokens), 1)
    element_kind = _text(record.get("element_kind")).replace("_", " ").lower()
    role_match = 0.75 if element_kind and element_kind in normalized_prompt else 0.0
    score = exact * 2.0 + role_match + overlap + path_overlap * 0.35
    if score > 0:
      scored.append((score, record))
  scored.sort(
    key=lambda item: (
      -item[0],
      _text(item[1].get("path")),
      int(item[1].get("line") or 0),
    )
  )
  return [{**record, "relevance_score": round(score, 4)} for score, record in scored[: max(1, limit)]]


def build_project_ui_knowledge_context(
  matches: list[dict[str, Any]],
  *,
  max_chars: int = 4200,
) -> str:
  if not matches:
    return ""
  lines = [
    "Current project UI knowledge (structural evidence; use the LLM to infer user intent):",
    "Each record identifies the live source owner of visible website text.",
  ]
  for item in matches:
    lines.append(
      "- "
      f"path={item.get('path')} line={item.get('line')} component={item.get('component') or '-'} "
      f"route={item.get('route') or '-'} kind={item.get('element_kind') or '-'} "
      f"text={json.dumps(_text(item.get('text')), ensure_ascii=False)} "
      f"purpose={json.dumps(_text(item.get('purpose')), ensure_ascii=False)} "
      f"event={item.get('event') or '-'} handler={item.get('handler') or '-'} "
      f"target={item.get('target') or '-'}"
    )
  return "\n".join(lines)[:max_chars]


def project_ui_matches_as_code_context(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
  result: list[dict[str, Any]] = []
  for item in matches:
    path = _text(item.get("path"))
    if not path:
      continue
    result.append(
      {
        "path": path,
        "symbol": _text(item.get("component")),
        "line_start": int(item.get("line") or 0),
        "line_end": int(item.get("line") or 0),
        "score": float(item.get("relevance_score") or 0.0),
        "matched_terms": [_text(item.get("text"))],
        "snippets": [_text(item.get("snippet"))],
        "content_chars": len(_text(item.get("snippet"))),
        "match_type": "project_ui_knowledge",
        "ui_semantic": {
          key: item.get(key)
          for key in (
            "component",
            "route",
            "element_kind",
            "text",
            "purpose",
            "event",
            "handler",
            "target",
            "line",
          )
        },
      }
    )
  return result


__all__ = [
  "build_project_ui_knowledge_context",
  "extract_project_ui_knowledge",
  "load_project_ui_knowledge",
  "persist_project_ui_knowledge",
  "project_knowledge_source_hash",
  "project_ui_matches_as_code_context",
  "select_project_ui_knowledge",
]
