from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_SESSION_DIR = Path(".worktual/terminal_sessions")


def session_path(project_id: str, *, base_dir: Path | None = None) -> Path:
  safe_id = "".join(char if char.isalnum() or char in "-_" else "_" for char in project_id)
  root = base_dir or DEFAULT_SESSION_DIR
  return root / f"{safe_id}.json"


def load_session(path: Path) -> dict[str, Any]:
  if not path.exists():
    return {}
  payload = json.loads(path.read_text(encoding="utf-8"))
  return payload if isinstance(payload, dict) else {}


def save_session(path: Path, payload: dict[str, Any]) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def merge_session_state(state: dict[str, Any], saved: dict[str, Any]) -> dict[str, Any]:
  if not saved:
    return state
  merged = dict(state)
  for key, value in saved.items():
    if key.startswith("_"):
      continue
    if value is not None:
      merged[key] = value
  merged["prompt"] = saved.get("prompt") or merged.get("prompt")
  return merged
