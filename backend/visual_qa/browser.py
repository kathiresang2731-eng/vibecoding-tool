from __future__ import annotations

import os
import shlex
import shutil
from pathlib import Path

try:
  from ..config import Settings
except ImportError:
  from config import Settings

from .types import BrowserCommand


def resolve_browser_command(settings: Settings | None) -> BrowserCommand | None:
  for source, configured in configured_browser_commands(settings):
    command = parse_browser_command(configured, source=source)
    if command:
      return command

  for candidate in browser_candidates():
    command = parse_browser_command(candidate, source="candidate")
    if command:
      return command
  return None

def configured_browser_commands(settings: Settings | None) -> list[tuple[str, str]]:
  candidates: list[tuple[str, str]] = []
  if settings is not None:
    configured = str(getattr(settings, "visual_qa_browser_command", "") or "").strip()
    if configured:
      candidates.append(("settings.visual_qa_browser_command", configured))
  for name in (
    "VISUAL_QA_BROWSER_COMMAND",
    "CHROME_PATH",
    "CHROMIUM_PATH",
    "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH",
    "BROWSER",
  ):
    value = os.environ.get(name, "").strip()
    if value:
      candidates.append((name, value))
  return candidates

def parse_browser_command(candidate: str, *, source: str) -> BrowserCommand | None:
  cleaned = candidate.strip()
  if not cleaned:
    return None

  expanded_whole = Path(cleaned).expanduser()
  if expanded_whole.exists():
    return BrowserCommand(parts=[str(expanded_whole)], source=source)

  try:
    parts = shlex.split(cleaned)
  except ValueError:
    parts = [cleaned]
  if not parts:
    return None

  executable = str(Path(parts[0]).expanduser())
  if Path(executable).exists():
    return BrowserCommand(parts=[executable, *parts[1:]], source=source)
  resolved = shutil.which(parts[0])
  if resolved:
    return BrowserCommand(parts=[resolved, *parts[1:]], source=source)
  return None

def browser_candidates() -> list[str]:
  return [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Google Chrome 2.app/Contents/MacOS/Google Chrome",
    "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
    "/Applications/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/snap/bin/chromium",
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "msedge",
    "microsoft-edge",
    "brave-browser",
    "chrome",
  ]
