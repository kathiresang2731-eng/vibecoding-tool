from __future__ import annotations

import os

os.environ.setdefault("ENABLE_UNIFIED_UPDATE_ENGINE", "true")
os.environ.setdefault("ENABLE_CODE_INDEX", "true")

from backend.agents.update_engine.intent_parser import (
  is_style_reference_prompt,
  merge_style_reference_into_analysis,
  parse_style_reference_intent,
)
from backend.agents.update_engine.scope_engine import _apply_style_reference_scope


SAMPLE_FILES = [
  {
    "path": "src/pages/Auth.jsx",
    "content": (
      'export default function Auth() {\n'
      '  return <div className="bg-slate-900 text-white p-8">Login</div>;\n'
      "}\n"
    ),
  },
  {
    "path": "src/pages/Dashboard.jsx",
    "content": (
      'export default function Dashboard() {\n'
      '  return <div className="bg-emerald-600 text-white p-8">Dashboard</div>;\n'
      "}\n"
    ),
  },
]


def test_style_reference_prompt_detected() -> None:
  prompt = "change the website auth page colors to same like dashboard"
  assert is_style_reference_prompt(prompt)


def test_parse_auth_dashboard_style_reference() -> None:
  paths = [item["path"] for item in SAMPLE_FILES]
  files_map = {item["path"]: item["content"] for item in SAMPLE_FILES}
  intent = parse_style_reference_intent(
    "change the website auth page colors to same like dashboard",
    paths=paths,
    files_map=files_map,
  )
  assert intent is not None
  assert intent.request_kind == "style_reference_update"
  assert any("Auth" in path for path in intent.target_files)
  assert any("Dashboard" in path for path in intent.reference_files)


def test_apply_style_reference_scope_merges_analysis() -> None:
  analysis = _apply_style_reference_scope(
    {"update_mode": "targeted_patch", "candidate_files": ["src/pages/Auth.jsx"], "summary": "update auth"},
    prompt="change auth page colors to same like dashboard",
    project_files=SAMPLE_FILES,
  )
  assert analysis.get("request_kind") == "style_reference_update"
  assert "src/pages/Dashboard.jsx" in analysis.get("reference_files", [])
  assert analysis.get("style_reference_snippets")


def test_merge_style_reference_into_analysis_includes_snippets() -> None:
  paths = [item["path"] for item in SAMPLE_FILES]
  files_map = {item["path"]: item["content"] for item in SAMPLE_FILES}
  intent = parse_style_reference_intent(
    "change auth colors like dashboard",
    paths=paths,
    files_map=files_map,
  )
  assert intent is not None
  merged = merge_style_reference_into_analysis(
    {"candidate_files": [], "update_mode": "targeted_patch"},
    intent,
    files_map=files_map,
  )
  assert merged["candidate_files"]
  assert merged["style_reference_snippets"]
  assert "emerald" in merged["style_reference_snippets"][0]["snippet"].lower() or "bg-" in merged["style_reference_snippets"][0]["snippet"]
