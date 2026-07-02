from __future__ import annotations

from typing import Any

try:
  from ..streaming.module_contracts import normalize_relative_import_export_contracts
  from .app_shell import apply_deterministic_app_shell
except ImportError:
  from backend.agents.streaming.module_contracts import normalize_relative_import_export_contracts
  from backend.agents.generation_engine.app_shell import apply_deterministic_app_shell


def _contract_eligible_paths(files_map: dict[str, str]) -> list[str]:
  paths: list[str] = []
  for path in files_map:
    if path == "src/App.jsx" or path.startswith("src/pages/") or path.startswith("src/components/"):
      paths.append(path)
  return sorted(paths)


def apply_generation_deterministic_repairs(
  files_map: dict[str, str],
  *,
  work_plan: dict[str, Any] | None = None,
  force_app_shell: bool = True,
) -> tuple[dict[str, str], list[str], list[dict[str, str]]]:
  """Apply deterministic App.jsx synthesis and import/export contract repairs."""
  updated = dict(files_map)
  changed_paths: list[str] = []

  repaired_map, app_changed = apply_deterministic_app_shell(
    updated,
    work_plan=work_plan,
    force=force_app_shell,
  )
  if app_changed:
    updated = repaired_map
    changed_paths.append("src/App.jsx")

  contract_payload = [
    {"path": path, "content": updated[path]}
    for path in _contract_eligible_paths(updated)
    if path in updated
  ]
  if contract_payload:
    normalized, contract_changed, repairs = normalize_relative_import_export_contracts(contract_payload)
    for item in normalized:
      path = str(item.get("path") or "")
      if path in contract_changed:
        updated[path] = str(item.get("content") or "")
    changed_paths.extend(contract_changed)

  return updated, list(dict.fromkeys(changed_paths)), repairs if contract_payload else []
