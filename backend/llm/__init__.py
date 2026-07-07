"""Backward-compatible import namespace for :mod:`backend.agents`.

The alias loader makes legacy and canonical imports return the same module
objects. This matters for provider registries, monkeypatches, and runtime state.
"""

from __future__ import annotations

import importlib
import importlib.abc
import importlib.util
from pathlib import Path
import sys

__path__ = [str(Path(__file__).resolve().parent.parent / "agents")]

_LEGACY_PREFIX = f"{__name__}."
_CANONICAL_ROOT = "backend.agents" if __name__.startswith("backend.") else "agents"


class _LegacyLlmAliasLoader(importlib.abc.Loader):
  def __init__(self, canonical_name: str) -> None:
    self.canonical_name = canonical_name

  def create_module(self, spec):
    module = importlib.import_module(self.canonical_name)
    sys.modules[spec.name] = module
    return module

  def exec_module(self, module) -> None:
    return None


class _LegacyLlmAliasFinder(importlib.abc.MetaPathFinder):
  def find_spec(self, fullname: str, path=None, target=None):
    if not fullname.startswith(_LEGACY_PREFIX):
      return None

    suffix = fullname.removeprefix(_LEGACY_PREFIX)
    canonical_name = f"{_CANONICAL_ROOT}.{suffix}"
    canonical_spec = importlib.util.find_spec(canonical_name)
    if canonical_spec is None:
      return None

    is_package = canonical_spec.submodule_search_locations is not None
    return importlib.util.spec_from_loader(
      fullname,
      _LegacyLlmAliasLoader(canonical_name),
      is_package=is_package,
    )


if not any(isinstance(finder, _LegacyLlmAliasFinder) for finder in sys.meta_path):
  sys.meta_path.insert(0, _LegacyLlmAliasFinder())
