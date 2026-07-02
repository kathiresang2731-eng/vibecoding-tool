from __future__ import annotations

from typing import Any

from .artifacts import screenshot_changed


def persist_visual_qa_result(
  *,
  store: Any,
  user: Any,
  test_run: dict[str, Any],
  browser_result: dict[str, Any],
  project_id: str,
  chat_session_id: str | None,
  project_version_id: str | None,
  phase: str,
) -> dict[str, Any]:
  test_run_id = str(test_run.get("id") or "")
  screenshots = [item for item in browser_result.get("screenshots", []) if isinstance(item, dict)]
  layout_issues = [item for item in browser_result.get("layout_issues", []) if isinstance(item, dict)]
  artifact_ids: list[str] = []
  comparisons: list[dict[str, Any]] = []
  qa_passed = str(browser_result.get("status") or "") == "passed"

  for screenshot in screenshots:
    route = str(screenshot.get("route") or "/")
    viewport_name = str(screenshot.get("viewport_name") or "unknown")
    baseline = store.latest_baseline_screenshot(
      project_id,
      user,
      route=route,
      viewport_name=viewport_name,
    )
    before_artifact = None
    if baseline and phase == "after":
      before_artifact = store.create_screenshot_artifact(
        project_id,
        user,
        test_run_id=test_run_id,
        phase="before",
        route=route,
        viewport_name=viewport_name,
        width=int(baseline.get("width") or screenshot.get("width") or 1),
        height=int(baseline.get("height") or screenshot.get("height") or 1),
        storage_path=str(baseline.get("storage_path") or ""),
        sha256=str(baseline.get("sha256") or ""),
        size_bytes=int(baseline.get("size_bytes") or 0),
        chat_session_id=chat_session_id,
        project_version_id=baseline.get("project_version_id"),
        source_artifact_id=str(baseline.get("id") or "") or None,
        metadata={"linked_from_baseline": True},
      )
      artifact_ids.append(str(before_artifact["id"]))

    after_artifact = store.create_screenshot_artifact(
      project_id,
      user,
      test_run_id=test_run_id,
      phase=phase,
      route=route,
      viewport_name=viewport_name,
      width=int(screenshot.get("width") or 1),
      height=int(screenshot.get("height") or 1),
      storage_path=str(screenshot.get("storage_path") or ""),
      sha256=str(screenshot.get("sha256") or ""),
      size_bytes=int(screenshot.get("size_bytes") or 0),
      chat_session_id=chat_session_id,
      project_version_id=project_version_id,
      is_baseline=qa_passed and phase in {"after", "baseline"},
      metadata={"target_url": browser_result.get("target_url")},
    )
    artifact_ids.append(str(after_artifact["id"]))

    viewport_issues = [
      issue
      for issue in layout_issues
      if str(issue.get("viewport") or "") in {"", viewport_name}
    ]
    changed = screenshot_changed(baseline, screenshot)
    comparison_status = "failed" if any(issue.get("severity") == "high" for issue in viewport_issues) else "passed"
    if baseline is None:
      comparison_status = "baseline_created" if qa_passed else comparison_status
    comparison = store.create_visual_comparison(
      project_id,
      user,
      test_run_id=test_run_id,
      before_artifact_id=str(before_artifact.get("id") or "") if before_artifact else None,
      after_artifact_id=str(after_artifact["id"]),
      route=route,
      viewport_name=viewport_name,
      status=comparison_status,
      changed=bool(changed),
      difference_ratio=0.0 if changed is False else None,
      layout_issues=viewport_issues,
      metadata={
        "comparison_mode": "sha256_exact",
        "change_known": changed is not None,
      },
    )
    comparisons.append(
      {
        "id": comparison.get("id"),
        "route": route,
        "viewport_name": viewport_name,
        "status": comparison_status,
        "changed": changed,
        "before_artifact_id": before_artifact.get("id") if before_artifact else None,
        "after_artifact_id": after_artifact.get("id"),
      }
    )

  status = "passed" if qa_passed else "failed"
  completed = store.complete_automation_test_run(
    test_run_id,
    user,
    status=status,
    summary=(
      f"Captured {len(screenshots)} screenshot(s); visual QA {status}."
      if screenshots
      else f"Visual QA {status} without durable screenshots."
    ),
    results={
      "browser_status": browser_result.get("status"),
      "layout_checked": browser_result.get("layout_checked"),
      "severity": browser_result.get("severity"),
      "screenshot_count": len(screenshots),
      "comparison_count": len(comparisons),
      "warnings": browser_result.get("warnings") or [],
    },
  )
  return {
    "test_run_id": test_run_id,
    "status": completed.get("status") or status,
    "screenshot_artifact_ids": artifact_ids,
    "comparisons": comparisons,
  }
