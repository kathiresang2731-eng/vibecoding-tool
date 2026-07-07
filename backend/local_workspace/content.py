from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import Any

from .constants import BINARY_PUBLIC_ASSET_EXTENSIONS
from .errors import LocalWorkspaceError


def normalize_file_content(file_item: dict[str, Any]) -> str:
  content = file_item.get("content")
  if content is None:
    content = file_item.get("code")
  if not isinstance(content, str):
    raise LocalWorkspaceError("Project file content must be text.")
  return content


def is_binary_project_asset(relative_path: str) -> bool:
  return Path(relative_path).suffix.lower() in BINARY_PUBLIC_ASSET_EXTENSIONS


def encode_file_as_data_url(path: Path, relative_path: str) -> str:
  mime_type = mimetypes.guess_type(relative_path)[0] or "application/octet-stream"
  encoded = base64.b64encode(path.read_bytes()).decode("ascii")
  return f"data:{mime_type};base64,{encoded}"


def write_project_file_content(destination: Path, relative_path: str, content: str) -> None:
  if is_binary_project_asset(relative_path) and content.startswith("data:") and ";base64," in content:
    _, encoded = content.split(";base64,", 1)
    destination.write_bytes(base64.b64decode(encoded))
    return
  destination.write_text(content, encoding="utf-8")
