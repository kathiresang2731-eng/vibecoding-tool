from __future__ import annotations

from backend.agents.generation_engine.validation import validate_generation_deliverable
from backend.agents.requirement_confirmation.prompts import format_confirmation_brief_for_generation
from backend.agents.streaming.task_planner import (
  _infer_greenfield_flow_page_paths,
  _infer_greenfield_page_paths,
  build_greenfield_streaming_prompt,
  plan_greenfield_parallel_tasks,
)


def test_confirmation_brief_injected_into_generation_prompt() -> None:
  block = format_confirmation_brief_for_generation(
    {
      "summary": "AI-native CRM",
      "planned_changes": ["Generate auth flow", "Wire dashboard modules"],
      "assumptions": ["React + Vite frontend"],
      "scope_boundaries": ["Do not remove scaffold config"],
    }
  )
  assert "Confirmed execution brief" in block
  assert "AI-native CRM" in block
  assert "Generate auth flow" in block


def test_greenfield_flow_pages_from_auth_onboarding_dashboard() -> None:
  prompt = "auth -> onboarding with 5 steps -> dashboard with reports -> operation hub -> settings"
  paths = _infer_greenfield_flow_page_paths(prompt)
  assert "src/pages/Auth.jsx" in paths
  assert "src/pages/Onboarding.jsx" in paths
  assert "src/pages/Dashboard.jsx" in paths
  assert "src/pages/Settings.jsx" in paths


def test_numbered_modules_become_page_blueprint() -> None:
  prompt = (
    "CRM modules:\n"
    "1) lead & contact\n"
    "2) deals\n"
    "3) project\n"
    "4) product\n"
    "5) sales\n"
    "6) finance"
  )
  paths = _infer_greenfield_page_paths(prompt, max_pages=12)
  assert len(paths) >= 4
  blueprint = build_greenfield_streaming_prompt(prompt)
  assert "Greenfield build blueprint" in blueprint
  assert "src/pages/" in blueprint


def test_scaffold_only_rich_crm_fails_minimum_deliverable() -> None:
  prompt = (
    "Build an enterprise CRM with auth onboarding dashboard modules for leads deals projects "
    "products sales finance and analytics copilot workspace"
  )
  scaffold_files = [
    {"path": "package.json", "content": "{}"},
    {"path": "src/App.jsx", "content": "export default function App(){return null}"},
    {"path": "index.html", "content": "<html></html>"},
  ]
  result = validate_generation_deliverable(prompt=prompt, project_files=scaffold_files)
  assert result["complete"] is False
  assert "rich_greenfield_needs_multiple_pages" in result["issues"] or "scaffold_only_no_pages" in result["issues"]
  assert result["can_resume"] is True


def test_complete_generation_passes_minimum_deliverable() -> None:
  prompt = "Build a CRM with dashboard and deals modules"
  files = [
    {"path": "src/pages/Auth.jsx", "content": "export default function Auth(){return <div/>}"},
    {"path": "src/pages/Dashboard.jsx", "content": "export default function Dashboard(){return <div/>}"},
    {"path": "src/App.jsx", "content": "import { Routes, Route } from 'react-router-dom'; export default function App(){return <Routes><Route path='/' /></Routes>}"},
  ]
  result = validate_generation_deliverable(prompt=prompt, project_files=files)
  assert result["page_count"] >= 2


def test_greenfield_plan_includes_backend_when_requested() -> None:
  prompt = "Build a full stack CRM with FastAPI backend and PostgreSQL database for contacts and deals"
  plan = plan_greenfield_parallel_tasks(prompt)
  paths = [path for task in plan["tasks"] for path in task.get("paths", [])]
  assert any(path.startswith("backend/") for path in paths)
