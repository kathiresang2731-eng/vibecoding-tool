import os
from pathlib import Path
from textwrap import dedent

from backend.config import Settings
from backend.visual_qa import analyze_layout_snapshot, browser_runtime_error_markers, resolve_browser_command, resolve_preview_url, run_browser_preview_qa


def test_resolve_preview_url_uses_backend_public_base_url(tmp_path):
  settings = Settings(
    database_url="postgres://example",
    frontend_origins=[],
    dev_user_email="dev@example.com",
    gemini_api_key="",
    gemini_model="gemini-test",
    app_root=tmp_path,
    local_workspace_roots=[tmp_path],
    backend_public_base_url="http://localhost:8787",
  )

  assert resolve_preview_url(settings, "/api/previews/project-1/v1/") == "http://localhost:8787/api/previews/project-1/v1/"


def test_browser_preview_qa_skips_without_runtime_settings():
  result = run_browser_preview_qa(settings=None, project_id="project-1", preview_url="/api/previews/project-1/v1/")

  assert result["status"] == "skipped"
  assert result["mode"] == "browser_render_skipped"
  assert result["browser_rendered"] is False


def test_resolve_browser_command_supports_quoted_configured_command(tmp_path):
  browser_path = write_fake_browser(tmp_path / "Fake Browser")
  settings = visual_settings(tmp_path, visual_qa_browser_command=f'"{browser_path}" --custom-flag')

  command = resolve_browser_command(settings)

  assert command is not None
  assert command.parts == [str(browser_path), "--custom-flag"]
  assert command.source == "settings.visual_qa_browser_command"


def test_browser_preview_qa_passes_with_configured_browser_command(tmp_path):
  browser_path = write_fake_browser(tmp_path / "Fake Browser")
  settings = visual_settings(tmp_path, visual_qa_browser_command=f'"{browser_path}" --custom-flag')

  result = run_browser_preview_qa(settings=settings, project_id="project-1", preview_url="/api/previews/project-1/v1/")

  assert result["status"] == "passed"
  assert result["mode"] == "browser_rendered_preview"
  assert result["browser_rendered"] is True
  assert result["layout_checked"] is False
  assert result["severity"] == "none"
  assert {item["name"] for item in result["viewport_results"]} == {"mobile", "tablet", "desktop"}
  assert result["browser_command_source"] == "settings.visual_qa_browser_command"
  assert result["target_url"] == "http://localhost:8787/api/previews/project-1/v1/"
  assert any(check["name"] == "screenshot_dimensions" and check["detail"] == "640x480" for check in result["checks"])


def test_browser_preview_qa_persists_all_viewport_screenshots(tmp_path):
  browser_path = write_fake_browser(tmp_path / "Fake Browser")
  settings = visual_settings(tmp_path, visual_qa_browser_command=str(browser_path))
  output_dir = tmp_path / "captures"

  result = run_browser_preview_qa(
    settings=settings,
    project_id="project-1",
    preview_url="/api/previews/project-1/v1/",
    screenshot_output_dir=output_dir,
  )

  assert result["status"] == "passed"
  assert {item["viewport_name"] for item in result["screenshots"]} == {"mobile", "tablet", "desktop"}
  assert all(Path(item["storage_path"]).is_file() for item in result["screenshots"])


def test_browser_preview_qa_reports_failed_when_browser_exits_nonzero(tmp_path):
  browser_path = write_failing_browser(tmp_path / "Failing Browser")
  settings = visual_settings(tmp_path, visual_qa_browser_command=str(browser_path))

  result = run_browser_preview_qa(settings=settings, project_id="project-1", preview_url="/api/previews/project-1/v1/")

  assert result["status"] == "failed"
  assert result["mode"] == "browser_render_failed"
  assert result["browser_rendered"] is False
  assert "Browser render failed with exit code" in result["warnings"][0]


def test_browser_preview_qa_ignores_temp_profile_cleanup_errors(tmp_path, monkeypatch):
  browser_path = write_fake_browser(tmp_path / "Fake Browser")
  settings = visual_settings(tmp_path, visual_qa_browser_command=str(browser_path))

  class CleanupSensitiveTemporaryDirectory:
    def __init__(self, *args, **kwargs):
      self.ignore_cleanup_errors = bool(kwargs.get("ignore_cleanup_errors"))
      self.path = tmp_path / "worktual-preview-qa-sensitive"

    def __enter__(self):
      self.path.mkdir(exist_ok=True)
      return str(self.path)

    def __exit__(self, exc_type, exc, traceback):
      if not self.ignore_cleanup_errors:
        raise OSError("[Errno 66] Directory not empty")
      return False

  monkeypatch.setattr("backend.visual_qa.tempfile.TemporaryDirectory", CleanupSensitiveTemporaryDirectory)

  result = run_browser_preview_qa(settings=settings, project_id="project-1", preview_url="/api/previews/project-1/v1/")

  assert result["status"] == "passed"


def test_browser_runtime_error_markers_detect_react_reference_error():
  output = "Uncaught ReferenceError: React is not defined at App (index.js:1:10)"

  markers = browser_runtime_error_markers(output)

  assert "react is not defined" in markers
  assert "uncaught referenceerror" in markers


def test_layout_analyzer_detects_overflow_overlap_and_text_clipping():
  result = analyze_layout_snapshot(
    {
      "scroll_width": 440,
      "elements": [
        {
          "selector": "header.hero",
          "tag": "header",
          "left": 0,
          "top": 0,
          "width": 420,
          "height": 120,
          "text": "Hero",
        },
        {
          "selector": "button.primary",
          "tag": "button",
          "left": 20,
          "top": 40,
          "width": 160,
          "height": 40,
          "text": "Primary action",
          "client_width": 90,
          "scroll_width": 140,
          "client_height": 20,
          "scroll_height": 48,
        },
        {
          "selector": "a.secondary",
          "tag": "a",
          "left": 30,
          "top": 50,
          "width": 150,
          "height": 40,
          "text": "Secondary",
        },
      ],
    },
    viewport={"name": "mobile", "width": 390, "height": 844},
  )

  issue_types = {issue["type"] for issue in result["issues"]}
  assert result["status"] == "failed"
  assert result["severity"] == "high"
  assert "horizontal_overflow" in issue_types
  assert "offscreen_element" in issue_types
  assert "text_overflow" in issue_types
  assert "clipped_text" in issue_types
  assert "overlap" in issue_types


def test_browser_preview_qa_fails_with_high_severity_layout_issues(tmp_path, monkeypatch):
  browser_path = write_fake_browser(tmp_path / "Fake Browser")
  settings = visual_settings(tmp_path, visual_qa_browser_command=str(browser_path))

  def fake_layout_qa(**kwargs):
    return {
      "status": "failed",
      "layout_checked": True,
      "viewport_results": [
        {
          "name": "mobile",
          "width": 390,
          "height": 844,
          "status": "failed",
          "severity": "high",
          "issues": [{"type": "horizontal_overflow", "severity": "high"}],
        }
      ],
      "layout_issues": [{"type": "horizontal_overflow", "severity": "high", "viewport": "mobile"}],
      "severity": "high",
      "warnings": [],
    }

  monkeypatch.setattr("backend.visual_qa.runner.run_browser_layout_qa", fake_layout_qa)

  result = run_browser_preview_qa(settings=settings, project_id="project-1", preview_url="/api/previews/project-1/v1/")

  assert result["status"] == "failed"
  assert result["layout_checked"] is True
  assert result["severity"] == "high"
  assert result["layout_issues"][0]["viewport"] == "mobile"
  assert any(check["name"] == "layout_probe" and check["status"] == "failed" for check in result["checks"])


def visual_settings(tmp_path, *, visual_qa_browser_command=""):
  return Settings(
    database_url="postgres://example",
    frontend_origins=[],
    dev_user_email="dev@example.com",
    gemini_api_key="",
    gemini_model="gemini-test",
    app_root=tmp_path,
    local_workspace_roots=[tmp_path],
    backend_public_base_url="http://localhost:8787",
    visual_qa_browser_command=visual_qa_browser_command,
  )


def write_fake_browser(path):
  path.write_text(
    dedent(
      """\
      #!/usr/bin/env python3
      import struct
      import sys
      import zlib

      screenshot_path = None
      for arg in sys.argv[1:]:
        if arg.startswith("--screenshot="):
          screenshot_path = arg.split("=", 1)[1]
          break
      if not screenshot_path:
        raise SystemExit(2)

      width, height = 640, 480
      rows = []
      for y in range(height):
        row = bytearray([0])
        for x in range(width):
          row.extend(((x * 3 + y) % 256, (x + y * 5) % 256, (x * y) % 256, 255))
        rows.append(bytes(row))
      raw = b"".join(rows)

      def chunk(kind, data):
        return (
          struct.pack(">I", len(data))
          + kind
          + data
          + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

      png = (
        b"\\x89PNG\\r\\n\\x1a\\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
      )
      with open(screenshot_path, "wb") as file:
        file.write(png)
      """
    ),
    encoding="utf-8",
  )
  os.chmod(path, 0o755)
  return path


def write_failing_browser(path):
  path.write_text(
    dedent(
      """\
      #!/usr/bin/env python3
      import sys
      print("render failed", file=sys.stderr)
      raise SystemExit(7)
      """
    ),
    encoding="utf-8",
  )
  os.chmod(path, 0o755)
  return path
