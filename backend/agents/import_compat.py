from __future__ import annotations

import importlib
import importlib.abc
import importlib.util
import sys
from typing import Any

_ALIAS_INSTALLED = False


class _AgentsAliasLoader(importlib.abc.Loader):
  def __init__(self, backend_name: str, alias_name: str) -> None:
    self._backend_name = backend_name
    self._alias_name = alias_name

  def create_module(self, spec: importlib.machinery.ModuleSpec) -> None:
    return None

  def exec_module(self, module: Any) -> None:
    backend_module = importlib.import_module(self._backend_name)
    sys.modules[self._alias_name] = backend_module


class _AgentsAliasFinder(importlib.abc.MetaPathFinder):
  def find_spec(
    self,
    fullname: str,
    path: object | None = None,
    target: object | None = None,
  ) -> importlib.machinery.ModuleSpec | None:
    if fullname != "agents" and not fullname.startswith("agents."):
      return None
    backend_name = f"backend.{fullname}"
    target_spec = importlib.util.find_spec(backend_name)
    if target_spec is None:
      return None
    loader = _AgentsAliasLoader(backend_name, fullname)
    return importlib.util.spec_from_loader(
      fullname,
      loader,
      origin=target_spec.origin,
      is_package=target_spec.submodule_search_locations is not None,
    )


def install_agents_import_alias() -> None:
  """Map legacy `agents.*` imports to `backend.agents.*` for uvicorn runs."""
  global _ALIAS_INSTALLED
  if _ALIAS_INSTALLED:
    return
  sys.meta_path.insert(0, _AgentsAliasFinder())
  _ALIAS_INSTALLED = True


def import_agents_module(module_suffix: str) -> Any:
  """Import agents.* with backend.agents fallback for uvicorn backend.main:app."""
  install_agents_import_alias()
  cleaned = str(module_suffix or "").strip().lstrip(".")
  candidates = (
    f"backend.agents.{cleaned}",
    f"agents.{cleaned}",
  )
  last_error: ImportError | None = None
  for name in candidates:
    try:
      return importlib.import_module(name)
    except ImportError as exc:
      last_error = exc
  if last_error is not None:
    raise last_error
  raise ImportError(f"Could not import agents module: {cleaned}")
