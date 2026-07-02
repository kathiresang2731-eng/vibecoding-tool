from __future__ import annotations

import os

os.environ.setdefault("ENABLE_UNIFIED_UPDATE_ENGINE", "true")
os.environ.setdefault("ENABLE_LEGACY_PARALLEL_UPDATES", "false")

from backend.agents.import_compat import import_agents_module
from backend.agents.streaming.file_agent import _emit_cumulative_staged_patch_diff


def test_import_compat_loads_backend_agents_module() -> None:
  module = import_agents_module("runtime_config")
  assert hasattr(module, "unified_update_engine_enabled")


def test_emit_cumulative_staged_patch_diff_emits_patch_proposed() -> None:
  events: list[dict] = []

  def emit(step: str, message: str, **kwargs) -> None:
    events.append({"step": step, "message": message, **kwargs})

  _emit_cumulative_staged_patch_diff(
    emit=emit,
    intent="website_update",
    changed_paths={"src/pages/Marketplace.jsx"},
    staged_files={
      "src/pages/Marketplace.jsx": (
        "export default function Marketplace() {\n"
        "  const handleAddToCart = () => {};\n"
        "  return <button onClick={handleAddToCart}>Add</button>;\n"
        "}\n"
      )
    },
    files_before_map={
      "src/pages/Marketplace.jsx": (
        "export default function Marketplace() {\n"
        "  return <button>Add</button>;\n"
        "}\n"
      )
    },
    persisted=False,
  )
  patch_events = [event for event in events if event["step"] == "patch.proposed"]
  assert patch_events
  assert patch_events[0]["detail"].get("staged") is True
  assert patch_events[0]["detail"].get("diffs")
