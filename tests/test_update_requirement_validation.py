from __future__ import annotations

from backend.agents.update_engine.requirement_validation import validate_update_requirement


def test_requirement_validation_fails_zero_patch() -> None:
  result = validate_update_requirement(
    prompt="fix launch operation hub button",
    files_before_map={"src/App.jsx": "old"},
    files_after_map={"src/App.jsx": "old"},
    changed_paths=[],
    update_scope={"candidate_files": ["src/App.jsx"], "target_files": ["src/App.jsx"]},
    preview_status="skipped",
  )

  assert result["status"] == "failed"
  assert result["issues"][0]["code"] == "no_code_changes"


def test_requirement_validation_checks_candidate_new_files() -> None:
  result = validate_update_requirement(
    prompt="add new AI chat widget",
    files_before_map={"src/App.jsx": "old"},
    files_after_map={"src/App.jsx": "new", "src/components/AIChatWidget.jsx": "export default function AIChatWidget() { return null; }"},
    changed_paths=["src/App.jsx", "src/components/AIChatWidget.jsx"],
    update_scope={
      "candidate_files": ["src/App.jsx", "src/components/AIChatWidget.jsx"],
      "target_files": ["src/App.jsx"],
      "candidate_new_files": ["src/components/AIChatWidget.jsx"],
    },
    preview_status="ready",
  )

  assert result["status"] == "satisfied"


def test_requirement_validation_does_not_require_optional_candidate_new_files() -> None:
  result = validate_update_requirement(
    prompt="before dashboard user must sign in then onboarding then dashboard",
    files_before_map={"src/pages/Auth.jsx": "old"},
    files_after_map={"src/pages/Auth.jsx": "new"},
    changed_paths=["src/pages/Auth.jsx"],
    update_scope={
      "candidate_files": ["src/pages/Auth.jsx"],
      "target_files": ["src/pages/Auth.jsx"],
      "candidate_new_files": ["src/components/AuthAndOnboardingFlow.jsx"],
      "new_file_requirements": {
        "needed": False,
        "reason": "Existing flow files are enough.",
        "planned_files": [],
      },
    },
    preview_status="ready",
  )

  assert result["status"] == "satisfied"


def test_requirement_validation_requires_planned_new_files_when_marked_needed() -> None:
  result = validate_update_requirement(
    prompt="add new AI chat widget",
    files_before_map={"src/App.jsx": "old"},
    files_after_map={"src/App.jsx": "new"},
    changed_paths=["src/App.jsx"],
    update_scope={
      "candidate_files": ["src/App.jsx"],
      "target_files": ["src/App.jsx"],
      "candidate_new_files": ["src/components/AIChatWidget.jsx"],
      "new_file_requirements": {
        "needed": True,
        "planned_files": [{"path": "src/components/AIChatWidget.jsx"}],
      },
    },
    preview_status="ready",
  )

  assert result["status"] == "failed"
  assert any(issue["code"] == "missing_new_file" for issue in result["issues"])


def test_requirement_validation_fails_when_preview_not_ready() -> None:
  result = validate_update_requirement(
    prompt="fix src/App.jsx",
    files_before_map={"src/App.jsx": "old"},
    files_after_map={"src/App.jsx": "new"},
    changed_paths=["src/App.jsx"],
    update_scope={"candidate_files": ["src/App.jsx"], "target_files": ["src/App.jsx"]},
    preview_status="failed",
  )

  assert result["status"] == "failed"
  assert any(issue["code"] == "preview_not_ready" for issue in result["issues"])
