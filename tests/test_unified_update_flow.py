from __future__ import annotations

import os

os.environ.setdefault("ENABLE_UNIFIED_UPDATE_ENGINE", "true")
os.environ.setdefault("ENABLE_LEGACY_PARALLEL_UPDATES", "false")

from backend.agents.runtime_config import (
  code_index_enabled,
  legacy_parallel_updates_enabled,
  parallel_stream_orchestrator_enabled,
  unified_update_engine_enabled,
)
from backend.agents.streaming.file_agent import _unified_update_scope_enabled, select_system_instruction
from backend.agents.streaming.task_planner import resolve_scoped_target_paths
from backend.agents.update_engine.commit_pipeline import build_commit_user_message


def test_unified_flags_default_on():
  assert unified_update_engine_enabled()
  assert code_index_enabled()
  assert not legacy_parallel_updates_enabled()
  assert not parallel_stream_orchestrator_enabled()


def test_unified_scope_skips_cart_heuristic_routing():
  paths = ["src/pages/Auth.jsx", "src/components/Navbar.jsx", "src/pages/Marketplace.jsx"]
  files_map = {
    "src/pages/Auth.jsx": "export default function Auth() { return <div>Login</div>; }",
    "src/components/Navbar.jsx": "export function Navbar() { return <button>Cart</button>; }",
    "src/pages/Marketplace.jsx": "export default function Marketplace() { return <button>Add to cart</button>; }",
  }
  scoped = resolve_scoped_target_paths("fix header cart button", paths=paths, files_map=files_map)
  assert scoped
  assert "Auth.jsx" not in scoped
  assert any("Navbar" in path or "Marketplace" in path for path in scoped)


def test_select_system_instruction_uses_single_update_prompt():
  instruction = select_system_instruction(intent="website_update", prompt="fix cart button in header")
  assert "auth/login" not in instruction.lower()
  assert "marketplace/product/cart page first" not in instruction.lower()
  assert "DIRECT PROJECT UPDATE" in instruction
  assert "str_replace" in instruction


def test_commit_user_message_includes_scope_rationale():
  message = build_commit_user_message(
    saved_paths=["src/components/Navbar.jsx"],
    rejected_writes=[],
    agent_summary="Wired cart button handler.",
    scope_rationale="Navbar and Marketplace handle cart UI.",
  )
  assert "Navbar" in message
  assert "Scope:" in message


def test_file_agent_unified_scope_enabled_for_updates_only():
  assert _unified_update_scope_enabled(intent="website_update", worker_id=None)
  assert not _unified_update_scope_enabled(intent="website_generation", worker_id=None)
  assert not _unified_update_scope_enabled(intent="website_update", worker_id="worker-1")
