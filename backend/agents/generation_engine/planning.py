from __future__ import annotations

import re
from typing import Any


THREE_WORKER_PROTOCOL = "worktual-three-worker-v1"


def _component_name(path: str) -> str:
  base = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
  parts = [part for part in re.split(r"[^a-zA-Z0-9]+", base) if part]
  name = "".join(part[:1].upper() + part[1:] for part in parts) or "GeneratedModule"
  return f"Generated{name}" if name[0].isdigit() else name


def _import_path_from_app(path: str) -> str:
  if path.startswith("src/"):
    return f"./{path.removeprefix('src/')}".rsplit(".", 1)[0]
  return ""


def _dedupe(paths: list[str]) -> list[str]:
  return list(dict.fromkeys(str(path).strip() for path in paths if str(path or "").strip()))


def _split_pages(page_paths: list[str]) -> tuple[list[str], list[str]]:
  midpoint = max(1, (len(page_paths) + 1) // 2)
  return page_paths[:midpoint], page_paths[midpoint:]


def _route_for_page(path: str, *, auth_is_entry: bool) -> str:
  stem = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
  lowered = stem.lower()
  if lowered == "auth" and auth_is_entry:
    return "/"
  if lowered == "home" and not auth_is_entry:
    return "/"
  if lowered == "home":
    return "/home"
  slug = re.sub(r"(?<!^)(?=[A-Z])", "-", stem).replace("_", "-").lower()
  return f"/{slug}"


def _task_contract(task_id: str, kind: str, paths: list[str]) -> dict[str, Any]:
  exports = {
    path: {
      "export_type": "default" if path.endswith((".jsx", ".tsx")) else "module",
      "export_name": _component_name(path),
      "import_path_from_app": _import_path_from_app(path),
    }
    for path in paths
  }
  return {
    "task_id": task_id,
    "kind": kind,
    "allowed_paths": paths,
    "depends_on": [],
    "exports": exports,
    "acceptance": "Create every assigned path, preserve the shared route contract, and keep all imports build-safe.",
  }


def build_three_worker_greenfield_plan(
  *,
  prompt: str,
  website_type: str,
  page_paths: list[str],
  component_paths: list[str],
  data_paths: list[str],
  backend_paths: list[str],
) -> dict[str, Any]:
  """Create one bounded plan with exactly three concurrent coding workers.

  Connectivity is agreed before generation: the integration worker receives the
  complete page/export map, so it can wire App.jsx while the other two workers
  create those modules concurrently.
  """
  pages = _dedupe(page_paths) or ["src/pages/Home.jsx"]
  components = _dedupe(component_paths)
  data = _dedupe(data_paths)
  backend = _dedupe(backend_paths)
  primary_pages, secondary_pages = _split_pages(pages)

  integration_paths = _dedupe(["src/App.jsx", *components])
  primary_paths = _dedupe(primary_pages)
  secondary_paths = _dedupe([*secondary_pages, *data, *backend])

  # Normal greenfield planning always has data files. Keep the invariant explicit
  # for callers that provide a minimal custom blueprint.
  if not secondary_paths:
    secondary_paths = ["src/data/mockData.js"]

  auth_is_entry = any(path.rsplit("/", 1)[-1].lower().startswith("auth.") for path in pages)
  route_contract = [
    {
      "file_path": path,
      "route": _route_for_page(path, auth_is_entry=auth_is_entry),
      "component": _component_name(path),
      "import_path": _import_path_from_app(path),
    }
    for path in pages
  ]
  tasks = [
    {
      "id": "greenfield-integration",
      "kind": "greenfield_integration_group",
      "paths": integration_paths,
      "scope": (
        "Own application integration. Create src/App.jsx as the thin router shell and create the assigned shared "
        "layout/navigation components. Wire every route in the shared route contract. The route modules are owned "
        "by co-workers but their paths and default export names are guaranteed by this plan."
      ),
      "depends_on": [],
      "route_contract": route_contract,
    },
    {
      "id": "greenfield-pages-primary",
      "kind": "greenfield_page_group",
      "paths": primary_paths,
      "scope": (
        "Create every assigned primary journey page as a standalone default-exported React component. "
        "Implement the entry journey and working navigation defined by the shared route contract."
      ),
      "depends_on": [],
      "route_contract": route_contract,
    },
    {
      "id": "greenfield-features-secondary",
      "kind": "greenfield_feature_group",
      "paths": secondary_paths,
      "scope": (
        "Create every assigned secondary page, data module, and optional backend module. Keep frontend page "
        "exports consistent with the shared route contract and keep backend modules independent of frontend imports."
      ),
      "depends_on": [],
      "route_contract": route_contract,
    },
  ]
  task_contracts = [
    _task_contract(str(task["id"]), str(task["kind"]), list(task["paths"]))
    for task in tasks
  ]
  coordination_contract = {
    "website_type": website_type or "custom",
    "chief_orchestrator": "Owns the plan, shared memory, merge, build, page QA, and single repair pass.",
    "main_coding_agent": "The integration worker owns App.jsx, routes, and shared layout connectivity.",
    "worker_protocol": THREE_WORKER_PROTOCOL,
    "route_contract": route_contract,
    "communication_rules": [
      "Exactly three coding workers start in the same wave.",
      "Every worker writes only its allowed paths and creates every assigned file.",
      "All workers use the same route/export contract before writing code.",
      "Each staged write is published to thread-safe orchestration memory and streamed to the UI.",
      "The orchestrator merges once, builds once, tests every planned route, and allows at most one repair pass.",
    ],
    "task_contracts": task_contracts,
  }
  all_paths = _dedupe([*integration_paths, *primary_paths, *secondary_paths])
  return {
    "tasks": tasks,
    "waves": [[task["id"] for task in tasks]],
    "task_count": 3,
    "worker_count": 3,
    "wave_count": 1,
    "parallel_waves": 1,
    "planning_source": "three_worker_greenfield_planner",
    "website_type": website_type or "custom",
    "coordination_contract": coordination_contract,
    "route_contract": route_contract,
    "scoped_targets": all_paths,
    "use_parallel_workers": True,
    "greenfield": True,
    "prompt_summary": str(prompt or "").strip()[:2_000],
  }
