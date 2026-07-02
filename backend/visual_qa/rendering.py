from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from .constants import BROWSER_QA_TIMEOUT_SECONDS, DEFAULT_VIEWPORT, RUNTIME_ERROR_MARKERS
from .types import BrowserCommand


def render_preview_with_browser(
  *,
  browser_command: BrowserCommand,
  target_url: str,
  screenshot_path: Path,
  profile_path: Path,
  viewport: str = DEFAULT_VIEWPORT,
) -> dict[str, Any]:
  attempts = ["--headless=new", "--headless"]
  last_reason = ""
  for headless_flag in attempts:
    if screenshot_path.exists():
      screenshot_path.unlink()
    command = [
      *browser_command.parts,
      headless_flag,
      "--disable-gpu",
      "--disable-dev-shm-usage",
      "--enable-logging=stderr",
      "--hide-scrollbars",
      "--no-first-run",
      "--no-default-browser-check",
      "--no-sandbox",
      f"--user-data-dir={profile_path}",
      f"--window-size={viewport}",
      f"--screenshot={screenshot_path}",
      target_url,
    ]
    try:
      completed = subprocess.run(
        command,
        text=True,
        capture_output=True,
        timeout=BROWSER_QA_TIMEOUT_SECONDS,
        check=False,
      )
    except subprocess.TimeoutExpired as exc:
      last_reason = f"Browser render timed out after {BROWSER_QA_TIMEOUT_SECONDS}s using {headless_flag}: {exc}"
      continue
    except OSError as exc:
      last_reason = f"Browser render could not start: {exc}"
      break

    output = "\n".join(part for part in [completed.stdout, completed.stderr] if part).strip()
    runtime_markers = browser_runtime_error_markers(output)
    if runtime_markers:
      return {
        "status": "failed",
        "failure_kind": "runtime_error",
        "reason": f"Browser runtime error markers found: {', '.join(runtime_markers)}. {output[:800]}",
      }
    if completed.returncode == 0 and screenshot_path.exists():
      return {"status": "passed", "headless_flag": headless_flag}
    last_reason = f"Browser render failed with exit code {completed.returncode} using {headless_flag}: {output[:800]}"
  return {"status": "failed", "reason": last_reason or "Browser render failed."}

def browser_runtime_error_markers(output: str) -> list[str]:
  lowered = output.lower()
  return [marker for marker in RUNTIME_ERROR_MARKERS if marker in lowered]
