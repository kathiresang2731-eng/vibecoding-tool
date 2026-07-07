from __future__ import annotations


def test_project_workspace_snapshot_prints_resolved_input_and_output_paths(tmp_path, capsys, monkeypatch):
  from backend.api.generation_parts.project import print_project_workspace_snapshot

  monkeypatch.setenv("WORKTUAL_ORCHESTRATION_TERMINAL_VERBOSE", "1")

  project = {"id": "project-1", "name": "Demo", "local_path": str(tmp_path)}
  files = [
    {"path": "index.html", "content": "<div />"},
    {"path": "src/App.jsx", "content": "export default function App() {}"},
  ]
  generated_files = [{"path": "src/App.jsx", "content": "updated"}]

  detail = print_project_workspace_snapshot(
    stage="after_orchestration",
    project_id="project-1",
    project=project,
    files=files,
    generated_files=generated_files,
    intent="website_update",
  )

  output = capsys.readouterr().out
  assert "[WorktualWorkspace] stage=after_orchestration" in output
  assert f"folder={tmp_path.resolve()}" in output
  assert f"input: {(tmp_path / 'index.html').resolve()}" in output
  assert f"output: {(tmp_path / 'src/App.jsx').resolve()}" in output
  assert detail["input_file_count"] == 2
  assert detail["generated_file_count"] == 1
  assert detail["resolved_generated_paths"] == [str((tmp_path / "src/App.jsx").resolve())]


def test_orchestration_terminal_prints_workspace_loaded_paths(monkeypatch, capsys, tmp_path):
  from backend.orchestration_terminal import print_orchestration_event

  monkeypatch.setenv("WORKTUAL_ORCHESTRATION_TERMINAL", "1")
  monkeypatch.setenv("WORKTUAL_ORCHESTRATION_TERMINAL_VERBOSE", "1")
  print_orchestration_event(
    {
      "step": "workspace.files.loaded",
      "status": "completed",
      "message": "Loaded project files",
      "detail": {
        "workspace_mode": "server_local_folder",
        "folder": str(tmp_path.resolve()),
        "input_file_count": 2,
        "resolved_input_paths": [
          str((tmp_path / "index.html").resolve()),
          str((tmp_path / "src/App.jsx").resolve()),
        ],
      },
    }
  )

  output = capsys.readouterr().out
  assert "📂 Workspace loaded: 2 file(s)" in output
  assert f"folder={tmp_path.resolve()}" in output
  assert f"• {(tmp_path / 'index.html').resolve()}" in output
  assert f"• {(tmp_path / 'src/App.jsx').resolve()}" in output


def test_orchestration_terminal_prints_zero_file_failure_with_context(monkeypatch, capsys, tmp_path):
  from backend.orchestration_terminal import print_orchestration_event

  monkeypatch.setenv("WORKTUAL_ORCHESTRATION_TERMINAL", "1")
  monkeypatch.setenv("WORKTUAL_ORCHESTRATION_TERMINAL_VERBOSE", "1")
  print_orchestration_event(
    {
      "step": "files.missing",
      "status": "failed",
      "message": "Artifact execution returned zero generated files; nothing was saved",
      "detail": {
        "workspace_mode": "server_local_folder",
        "folder": str(tmp_path.resolve()),
        "input_file_count": 1,
        "generated_file_count": 0,
        "resolved_input_paths": [str((tmp_path / "src/App.jsx").resolve())],
        "resolved_generated_paths": [],
        "intent": "website_update",
      },
    }
  )

  output = capsys.readouterr().out
  assert "✗ FAILED files.missing" in output
  assert "generated files: 0" in output
  assert f"folder={tmp_path.resolve()}" in output
  assert f"• {(tmp_path / 'src/App.jsx').resolve()}" in output


def test_orchestration_terminal_prints_scope_targets_with_function_and_line(monkeypatch, capsys):
  from backend.orchestration_terminal import print_orchestration_event

  monkeypatch.setenv("WORKTUAL_ORCHESTRATION_TERMINAL", "1")
  monkeypatch.setenv("WORKTUAL_ORCHESTRATION_TERMINAL_VERBOSE", "1")
  print_orchestration_event(
    {
      "step": "scope.resolved",
      "status": "completed",
      "message": "Update scope: src/pages/Analytics.jsx",
      "detail": {
        "update_mode": "targeted_patch",
        "request_kind": "interaction_wiring_update",
        "preflight_source": "scope_engine_llm",
        "scope_rationale": "Fix the onboarding walkthrough button.",
        "interaction_summary": "Start Onboarding Walkthrough button: navigate to onboarding",
        "project_ui_match_count": 1,
        "project_ui_matched_files": ["src/pages/Analytics.jsx"],
        "candidate_files": ["src/pages/Analytics.jsx"],
        "modification_targets": [
          {
            "path": "src/pages/Analytics.jsx",
            "line": 42,
            "function_name": "Analytics",
            "function_line": 4,
            "reason": "matched rendered button: Start Onboarding Walkthrough",
          }
        ],
      },
    }
  )

  output = capsys.readouterr().out
  assert "🎯 Update target selection: interaction_wiring_update" in output
  assert "rendered UI matches: 1" in output
  assert "src/pages/Analytics.jsx L42 fn=Analytics@L4" in output
  assert "Start Onboarding Walkthrough" in output


def test_orchestration_terminal_prints_tool_function_location(monkeypatch, capsys):
  from backend.orchestration_terminal import print_orchestration_event

  monkeypatch.setenv("WORKTUAL_ORCHESTRATION_TERMINAL", "1")
  monkeypatch.setenv("WORKTUAL_ORCHESTRATION_TERMINAL_VERBOSE", "1")
  print_orchestration_event(
    {
      "step": "tool.str_replace",
      "status": "completed",
      "message": "Edited src/pages/Analytics.jsx L42-44 (+3/-2)",
      "detail": {
        "tool": "str_replace",
        "path": "src/pages/Analytics.jsx",
        "start_line": 42,
        "end_line": 44,
        "function_name": "Analytics",
        "function_line": 4,
        "added": 3,
        "removed": 2,
      },
    }
  )

  output = capsys.readouterr().out
  assert "[Tool:str_replace] src/pages/Analytics.jsx L42-44 fn=Analytics@L4 (+3/-2)" in output
