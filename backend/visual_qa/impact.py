from __future__ import annotations

import posixpath
import re
from collections import deque
from typing import Any

from .layout import DEFAULT_LAYOUT_VIEWPORTS


IMPORT_RE = re.compile(
  r"""(?:import\s+(?:[^'"]+\s+from\s+)?|export\s+[^'"]+\s+from\s+|import\s*\()\s*['"]([^'"]+)['"]"""
)
ROUTE_COMPONENT_RE = re.compile(
  r"""<Route\b[^>]*\bpath\s*=\s*['"]([^'"]+)['"][^>]*\belement\s*=\s*\{\s*<([A-Za-z_$][\w$]*)""",
  re.IGNORECASE,
)
OBJECT_ROUTE_RE = re.compile(
  r"""\bpath\s*:\s*['"]([^'"]+)['"][\s\S]{0,240}?\belement\s*:\s*<([A-Za-z_$][\w$]*)""",
  re.IGNORECASE,
)
IMPORT_ALIAS_RE = re.compile(
  r"""import\s+(?:\{\s*)?([A-Za-z_$][\w$]*)[^'"]*?from\s*['"]([^'"]+)['"]"""
)
SOURCE_EXTENSIONS = (".js", ".jsx", ".ts", ".tsx", ".css", ".scss")
GLOBAL_IMPACT_NAMES = {
  "package.json",
  "vite.config.js",
  "vite.config.ts",
  "src/app.jsx",
  "src/app.tsx",
  "src/main.jsx",
  "src/main.tsx",
  "src/index.css",
  "src/globals.css",
}
GLOBAL_IMPACT_MARKERS = ("/layout.", "/router.", "/routes.", "/theme.", "/global")


def build_automated_test_scope(
  files: list[dict[str, Any]],
  *,
  changed_paths: list[str],
  operation: str,
  prompt: str = "",
) -> dict[str, Any]:
  files_map = {
    normalize_path(str(item.get("path") or "")): str(item.get("content") or "")
    for item in files
    if isinstance(item, dict) and item.get("path")
  }
  changed = [normalize_path(path) for path in changed_paths if normalize_path(path)]
  route_map, router_mode = discover_routes(files_map)
  full_visual = operation == "generation" or any(is_global_impact_path(path) for path in changed)
  affected_files = reverse_dependents(files_map, changed)
  affected_routes = sorted(
    {
      route
      for component_path in affected_files
      for route in routes_for_path(component_path, route_map)
      if route
    }
  )
  if full_visual:
    affected_routes = sorted(set(route_map.values())) or ["/"]
  elif not affected_routes:
    affected_routes = inferred_routes_for_changed_pages(changed) or ["/"]

  visual_expected = any(path.endswith(SOURCE_EXTENSIONS) for path in changed) and not all(
    path.endswith((".test.js", ".test.jsx", ".test.ts", ".test.tsx", ".spec.js", ".spec.ts"))
    for path in changed
  )
  lowered_prompt = str(prompt or "").lower()
  if any(term in lowered_prompt for term in ("backend", "api only", "database", "server-side")) and not any(
    term in lowered_prompt for term in ("ui", "screen", "layout", "style", "page", "component")
  ):
    visual_expected = False

  return {
    "scope": "full" if full_visual else "targeted",
    "full_build": True,
    "full_visual": full_visual,
    "changed_paths": changed,
    "affected_files": sorted(affected_files),
    "affected_routes": affected_routes[:20] if full_visual else affected_routes[:8],
    "viewports": [dict(viewport) for viewport in DEFAULT_LAYOUT_VIEWPORTS],
    "router_mode": router_mode,
    "visual_expected": visual_expected,
    "reason": (
      "Generation or shared application infrastructure changed; run the full visual route set."
      if full_visual
      else "Run screenshots only for routes that depend on the changed files."
    ),
  }


def discover_routes(files_map: dict[str, str]) -> tuple[dict[str, str], str]:
  route_map: dict[str, str] = {}
  router_mode = "hash"
  for path, content in files_map.items():
    if "BrowserRouter" in content or "createBrowserRouter" in content:
      router_mode = "browser"
    aliases = {
      alias: resolve_import_path(path, target, files_map)
      for alias, target in IMPORT_ALIAS_RE.findall(content)
      if target.startswith(".")
    }
    for pattern in (ROUTE_COMPONENT_RE, OBJECT_ROUTE_RE):
      for route, component in pattern.findall(content):
        component_path = aliases.get(component)
        if component_path:
          route_map[component_path] = normalize_route(route)
  return route_map, router_mode


def reverse_dependents(files_map: dict[str, str], changed_paths: list[str]) -> set[str]:
  reverse: dict[str, set[str]] = {}
  for importer, content in files_map.items():
    for target in IMPORT_RE.findall(content):
      if not target.startswith("."):
        continue
      resolved = resolve_import_path(importer, target, files_map)
      if resolved:
        reverse.setdefault(resolved, set()).add(importer)

  visited = set(changed_paths)
  queue = deque(changed_paths)
  while queue:
    current = queue.popleft()
    for dependent in reverse.get(current, set()):
      if dependent in visited:
        continue
      visited.add(dependent)
      queue.append(dependent)
  return visited


def resolve_import_path(importer: str, target: str, files_map: dict[str, str]) -> str:
  base = normalize_path(posixpath.join(posixpath.dirname(importer), target))
  candidates = [base]
  candidates.extend(f"{base}{extension}" for extension in SOURCE_EXTENSIONS)
  candidates.extend(f"{base}/index{extension}" for extension in SOURCE_EXTENSIONS)
  return next((candidate for candidate in candidates if candidate in files_map), "")


def routes_for_path(path: str, route_map: dict[str, str]) -> list[str]:
  if path in route_map:
    return [route_map[path]]
  return []


def inferred_routes_for_changed_pages(paths: list[str]) -> list[str]:
  routes: list[str] = []
  for path in paths:
    lowered = path.lower()
    if "/pages/" not in lowered and "/routes/" not in lowered:
      continue
    stem = posixpath.basename(path).rsplit(".", 1)[0]
    if stem.lower() in {"index", "home"}:
      routes.append("/")
    else:
      slug = re.sub(r"(?<!^)(?=[A-Z])", "-", stem).replace("_", "-").lower()
      routes.append(f"/{slug}")
  return sorted(set(routes))


def is_global_impact_path(path: str) -> bool:
  lowered = normalize_path(path).lower()
  return lowered in GLOBAL_IMPACT_NAMES or any(marker in lowered for marker in GLOBAL_IMPACT_MARKERS)


def normalize_path(path: str) -> str:
  return posixpath.normpath(str(path or "").strip().replace("\\", "/")).lstrip("./")


def normalize_route(route: str) -> str:
  value = str(route or "/").strip()
  if value in {"", "*"}:
    return "/"
  return value if value.startswith("/") else f"/{value}"
