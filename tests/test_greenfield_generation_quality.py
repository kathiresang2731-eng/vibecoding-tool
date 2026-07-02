from __future__ import annotations

from backend.agents.generation_engine.app_shell import (
  apply_deterministic_app_shell,
  synthesize_greenfield_app_shell,
)
from backend.agents.generation_engine.validation import validate_generation_deliverable
from backend.agents.streaming.syntax_guard import syntax_issues_for_content
from backend.agents.streaming.task_planner import _extract_prompt_page_labels, plan_greenfield_parallel_tasks


DESIGN_BRIEF_PROMPT = """
Build an enterprise CRM website.

Modules:
1. Initialize React framework with Vite
2. Tailwind CSS
3. Clear typography rules
4. Warm cream background accents
5. Earthy clay buttons
6. Lucide React icons
7. Dashboard with contacts and deals
8. Establish sustainable design system
"""


def test_design_brief_items_do_not_become_pages() -> None:
  labels = _extract_prompt_page_labels(DESIGN_BRIEF_PROMPT, max_labels=12)
  assert "dashboard with contacts and deals" in labels or any("dashboard" in label for label in labels)
  assert not any("tailwind" in label for label in labels)
  assert not any("earthy clay" in label for label in labels)
  assert not any("lucide" in label for label in labels)

  plan = plan_greenfield_parallel_tasks(DESIGN_BRIEF_PROMPT)
  page_paths = [
    str(path)
    for task in plan.get("tasks") or []
    if str(task.get("kind") or "").startswith("greenfield_page")
    for path in (task.get("paths") or [])
  ]
  assert any("Dashboard" in path for path in page_paths)
  assert not any("TailwindCss" in path for path in page_paths)
  assert not any("EarthyClayButtons" in path for path in page_paths)


def test_synthesize_app_shell_wires_valid_pages_only() -> None:
  files_map = {
    "src/pages/Dashboard.jsx": "import React from 'react';\nexport default function Dashboard(){return <div>CRM</div>;}\n",
    "src/pages/Home.jsx": "import React from 'react';\nexport default function Home(){return <div>Home</div>;}\n",
    "src/components/Layout.jsx": "import React from 'react';\nexport default function Layout({children}){return <div>{children}</div>;}\n",
    "src/App.jsx": '<Route path="tailwind" element={<Tail',
  }
  app = synthesize_greenfield_app_shell(["src/pages/Home.jsx", "src/pages/Dashboard.jsx"], files_map)
  assert "import Dashboard from" in app
  assert "import Home from" in app
  assert '<Route path="/dashboard" element={<Dashboard />} />' in app
  assert "element={<Tail" not in app

  repaired, changed = apply_deterministic_app_shell(files_map)
  assert changed is True
  assert syntax_issues_for_content("src/App.jsx", repaired["src/App.jsx"]) == []


def test_validation_flags_truncated_app_routes() -> None:
  files = [
    {"path": "src/pages/Dashboard.jsx", "content": "export default function Dashboard(){return <div/>;}"},
    {"path": "src/pages/Contacts.jsx", "content": "export default function Contacts(){return <div/>;}"},
    {"path": "src/App.jsx", "content": '<Route path="tailwind" element={<Tail'},
  ]
  result = validate_generation_deliverable(
    prompt="Build a CRM with dashboard and contacts",
    project_files=files,
  )
  assert result["complete"] is False
  assert "syntax_errors" in result["issues"]
