from __future__ import annotations

import os

os.environ.setdefault("ENABLE_UNIFIED_UPDATE_ENGINE", "true")

from backend.agents.streaming.file_agent import streaming_file_agent_step_limit
from backend.agents.update_engine.scope_engine import _apply_style_reference_scope


def test_style_reference_step_budget_increased() -> None:
  base = streaming_file_agent_step_limit(
    intent="website_update",
    prompt="change auth colors like dashboard",
    request_kind="",
  )
  style = streaming_file_agent_step_limit(
    intent="website_update",
    prompt="change auth colors like dashboard",
    request_kind="style_reference_update",
  )
  assert style >= base + 2


def test_auth_dashboard_scope_targets_and_reference() -> None:
  project_files = [
    {"path": "src/pages/Auth.jsx", "content": 'export default function Auth(){ return <div className="bg-black">x</div>; }'},
    {"path": "src/pages/Dashboard.jsx", "content": 'export default function Dashboard(){ return <div className="bg-green-600">x</div>; }'},
  ]
  scope = _apply_style_reference_scope(
    {"update_mode": "targeted_patch", "candidate_files": ["src/pages/Auth.jsx"]},
    prompt="change the website auth page colors to same like dashboard",
    project_files=project_files,
  )
  assert scope["request_kind"] == "style_reference_update"
  assert any("Auth" in path for path in scope.get("target_files", []))
  assert any("Dashboard" in path for path in scope.get("reference_files", []))
