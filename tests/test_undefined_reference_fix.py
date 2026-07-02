from __future__ import annotations

from backend.agents.agent_runtime.scoped_update import (
  deterministic_undefined_reference_fix_changes,
  extract_undefined_reference_names,
  infer_undeclared_jsx_conditional_identifiers,
)
from backend.agents.agent_runtime.scoped_update.runtime import run_scoped_update_agent


def test_extract_undefined_reference_names_from_summary() -> None:
  names = extract_undefined_reference_names(
    "fix this issue",
    {
      "summary": "Fix the showOnboarding is not defined runtime crash in Dashboard.jsx.",
      "target_symbols": [],
    },
  )
  assert names == ["showOnboarding"]


def test_infer_undeclared_jsx_conditional_identifiers() -> None:
  content = (
    "export default function Dashboard() {\n"
    "  return (\n"
    "    <main>\n"
    "      {showOnboarding && (\n"
    "        <section>Tour overlay</section>\n"
    "      )}\n"
    "    </main>\n"
    "  );\n"
    "}\n"
  )
  assert infer_undeclared_jsx_conditional_identifiers(content) == ["showOnboarding"]


def test_deterministic_undefined_reference_fix_removes_show_onboarding_block() -> None:
  dashboard = (
    "import React from 'react';\n"
    "export default function Dashboard() {\n"
    "  return (\n"
    "    <main>\n"
    "      {showOnboarding && (\n"
    "        <section>Tour overlay</section>\n"
    "      )}\n"
    "      <h1>Dashboard</h1>\n"
    "    </main>\n"
    "  );\n"
    "}\n"
  )
  changes = deterministic_undefined_reference_fix_changes(
    prompt="fix this issue",
    update_analysis={
      "update_mode": "bug_fix",
      "summary": "Fix showOnboarding is not defined in Dashboard.jsx.",
      "candidate_files": ["src/pages/Dashboard.jsx"],
    },
    existing_files=[{"path": "src/pages/Dashboard.jsx", "content": dashboard}],
  )
  assert len(changes) == 1
  assert "showOnboarding" not in changes[0]["content"]
  assert "Tour overlay" not in changes[0]["content"]
  assert "Dashboard" in changes[0]["content"]


def test_run_scoped_update_agent_skips_gemini_for_show_onboarding() -> None:
  class ShouldNotCallProvider:
    calls: list[str] = []

    def generate_json(self, prompt, **kwargs):
      self.calls.append(kwargs.get("trace_label"))
      raise AssertionError("Gemini should not be called for deterministic undefined-reference fix")

  dashboard = (
    "import React from 'react';\n"
    "export default function Dashboard() {\n"
    "  return <main>{showOnboarding && <section>Tour</section>}</main>;\n"
    "}\n"
  )
  result = run_scoped_update_agent(
    ShouldNotCallProvider(),
    prompt="Fix showOnboarding is not defined in src/pages/Dashboard.jsx",
    update_analysis={
      "update_mode": "bug_fix",
      "summary": "Fix showOnboarding is not defined runtime crash.",
      "candidate_files": ["src/pages/Dashboard.jsx"],
    },
    existing_files=[{"path": "src/pages/Dashboard.jsx", "content": dashboard}],
    code_search_matches=[],
  )
  assert result["deterministic_fallback"] == "undefined_reference_fix"
  assert "showOnboarding" not in result["changed_files"][0]["code"]
  assert ShouldNotCallProvider.calls == []
