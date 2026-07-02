from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

try:
  from ..config import Settings
except ImportError:
  from config import Settings

from .browser import resolve_browser_command
from .artifacts import screenshot_file_metadata
from .dom_probe import run_browser_layout_qa
from .layout import DEFAULT_LAYOUT_VIEWPORTS, skipped_layout_viewport_results
from .png import read_png_dimensions
from .rendering import render_preview_with_browser
from .results import failed_visual_qa, skipped_visual_qa


def run_browser_preview_qa(
  *,
  settings: Settings | None,
  project_id: str,
  preview_url: str | None,
  screenshot_output_dir: Path | None = None,
  route: str = "/",
) -> dict[str, Any]:
  if settings is None:
    return with_skipped_layout(skipped_visual_qa(project_id, "Runtime settings are unavailable for browser rendering."))
  if not preview_url:
    return with_skipped_layout(skipped_visual_qa(project_id, "Preview URL is missing."))

  browser_command = resolve_browser_command(settings)
  if not browser_command:
    return with_skipped_layout(skipped_visual_qa(project_id, "No Chrome, Chromium, Edge, Brave, or configured browser command was found."))

  target_url = resolve_preview_url(settings, preview_url)
  with tempfile.TemporaryDirectory(prefix="worktual-preview-qa-", ignore_cleanup_errors=True) as temp_dir:
    capture_root = screenshot_output_dir or (Path(temp_dir) / "screenshots")
    capture_root.mkdir(parents=True, exist_ok=True)
    screenshots: list[dict[str, Any]] = []
    checks = [
      {"name": "browser_command_resolved", "status": "passed", "detail": f"{browser_command.source}: {browser_command.display}"},
    ]
    warnings: list[str] = []
    for viewport in DEFAULT_LAYOUT_VIEWPORTS:
      viewport_name = str(viewport["name"])
      screenshot_path = capture_root / f"{viewport_name}.png"
      render_result = render_preview_with_browser(
        browser_command=browser_command,
        target_url=target_url,
        screenshot_path=screenshot_path,
        profile_path=Path(temp_dir) / f"profile-{viewport_name}",
        viewport=f"{viewport['width']},{viewport['height']}",
      )
      if render_result["status"] != "passed" or not screenshot_path.exists():
        return with_skipped_layout(
          failed_visual_qa(
            project_id,
            str(render_result.get("reason") or f"Browser render failed for {viewport_name}."),
            browser_command=browser_command,
            target_url=target_url,
            failure_kind=str(render_result.get("failure_kind") or "browser_render_failed"),
          )
        )
      dimensions = read_png_dimensions(screenshot_path)
      width, height = dimensions or (int(viewport["width"]), int(viewport["height"]))
      metadata = screenshot_file_metadata(screenshot_path)
      screenshot = {
        "route": route or "/",
        "viewport_name": viewport_name,
        "width": width,
        "height": height,
        **metadata,
      }
      if screenshot_output_dir is None:
        screenshot.pop("storage_path", None)
      screenshots.append(screenshot)
      checks.extend(
        [
          {"name": "browser_render", "status": "passed", "detail": f"{viewport_name} viewport rendered."},
          {"name": "screenshot_created", "status": "passed", "detail": f"{viewport_name}: {metadata['size_bytes']} bytes"},
          {"name": "screenshot_dimensions", "status": "passed", "detail": f"{width}x{height}"},
        ]
      )
      if metadata["size_bytes"] < 4_000:
        warnings.append(f"{viewport_name} screenshot is very small; the page may be blank or mostly empty.")

    layout_result = run_browser_layout_qa(
      browser_command=browser_command,
      target_url=target_url,
      profile_root=Path(temp_dir),
    )
    layout_checked = bool(layout_result.get("layout_checked"))
    viewport_results = [item for item in layout_result.get("viewport_results", []) if isinstance(item, dict)]
    layout_issues = [item for item in layout_result.get("layout_issues", []) if isinstance(item, dict)]
    severity = str(layout_result.get("severity") or "none")
    layout_warnings = [item for item in layout_result.get("warnings", []) if isinstance(item, str)]
    warnings.extend(layout_warnings)
    if layout_checked:
      failed_count = sum(1 for item in viewport_results if item.get("status") == "failed")
      checks.append(
        {
          "name": "layout_probe",
          "status": "failed" if severity == "high" else "passed",
          "detail": f"{len(viewport_results)} viewport(s) checked, {failed_count} failed.",
        }
      )
    else:
      checks.append(
        {
          "name": "layout_probe",
          "status": "skipped",
          "detail": "; ".join(layout_warnings[:3]) or "Browser layout probe was skipped.",
        }
      )
    return {
      "project_id": project_id,
      "status": "failed" if severity == "high" else "passed",
      "mode": "browser_rendered_preview",
      "browser_rendered": True,
      "layout_checked": layout_checked,
      "viewport_results": viewport_results,
      "layout_issues": layout_issues,
      "severity": severity,
      "browser_command": browser_command.display,
      "browser_command_source": browser_command.source,
      "target_url": target_url,
      "screenshots": screenshots,
      "checks": checks,
      "warnings": warnings,
    }


def with_skipped_layout(result: dict[str, Any]) -> dict[str, Any]:
  reason = str(result.get("reason") or "Browser layout QA was skipped.")
  return {
    **result,
    "layout_checked": False,
    "viewport_results": skipped_layout_viewport_results(reason),
    "layout_issues": [],
    "severity": "unknown",
  }

def resolve_preview_url(settings: Settings | None, preview_url: str) -> str:
  if preview_url.startswith(("http://", "https://")):
    return preview_url
  base_url = "http://127.0.0.1:8787"
  if settings is not None and getattr(settings, "backend_public_base_url", ""):
    base_url = str(settings.backend_public_base_url).rstrip("/")
  return urljoin(f"{base_url}/", preview_url.lstrip("/"))
