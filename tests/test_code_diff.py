from __future__ import annotations

from backend.code_diff import build_project_diff, redact_project_diff_for_audit


def test_build_project_diff_reports_added_and_removed_lines():
  before = [{"path": "src/App.jsx", "content": "export default function App() {\n  return <h1>Old</h1>;\n}\n"}]
  after = [{"path": "src/App.jsx", "code": "export default function App() {\n  return <h1>New</h1>;\n}\n"}]

  diff = build_project_diff(before, after)

  assert diff["file_count"] == 1
  assert diff["added"] == 1
  assert diff["removed"] == 1
  assert diff["diffs"][0]["path"] == "src/App.jsx"
  assert "+  return <h1>New</h1>;" in diff["diffs"][0]["diff"]
  assert "-  return <h1>Old</h1>;" in diff["diffs"][0]["diff"]


def test_redacted_project_diff_keeps_metadata_without_diff_body():
  before = [{"path": "src/App.jsx", "content": "secret code body"}]
  after = [{"path": "src/App.jsx", "content": "changed secret code body"}]

  redacted = redact_project_diff_for_audit(build_project_diff(before, after))

  assert redacted["file_count"] == 1
  assert redacted["files"][0]["path"] == "src/App.jsx"
  assert redacted["files"][0]["new_hash"]
  assert "diff" not in redacted["files"][0]
  assert "changed secret code body" not in str(redacted)


def test_build_project_diff_ignores_hidden_worktual_files():
  before = [
    {"path": "src/App.jsx", "content": "old\n"},
    {"path": ".worktual/skills/agent/SKILL.md", "content": "old skill\n"},
  ]
  after = [
    {"path": "src/App.jsx", "content": "new\n"},
    {"path": ".worktual/skills/agent/SKILL.md", "content": "new skill\nmany lines\n"},
  ]

  diff = build_project_diff(before, after)

  assert diff["file_count"] == 1
  assert diff["added"] == 1
  assert diff["removed"] == 1
  assert [item["path"] for item in diff["diffs"]] == ["src/App.jsx"]


def test_build_project_diff_changed_only_ignores_missing_after_files():
  before = [
    {"path": "src/App.jsx", "content": "old app\n"},
    {"path": "package-lock.json", "content": "lock\n" * 3000},
    {"path": "api.py", "content": "print('old')\n"},
  ]
  after = [{"path": "src/App.jsx", "content": "new app\n"}]

  diff = build_project_diff(before, after, compare_mode="changed_only")

  assert diff["file_count"] == 1
  assert diff["added"] == 1
  assert diff["removed"] == 1
  assert diff["diffs"][0]["path"] == "src/App.jsx"


def test_build_project_diff_skips_lockfiles_and_pdfs():
  before = [
    {"path": "package-lock.json", "content": "old lock\n" * 100},
    {"path": "docs/spec.pdf", "content": "binary"},
    {"path": "src/App.jsx", "content": "old\n"},
  ]
  after = [
    {"path": "package-lock.json", "content": "new lock\n" * 100},
    {"path": "docs/spec.pdf", "content": "changed"},
    {"path": "src/App.jsx", "content": "new\n"},
  ]

  diff = build_project_diff(before, after)

  assert diff["file_count"] == 1
  assert diff["diffs"][0]["path"] == "src/App.jsx"
