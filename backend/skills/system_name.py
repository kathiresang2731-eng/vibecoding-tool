"""Resolve per-machine Linux username for skills storage."""

from __future__ import annotations

import getpass
import re
from pathlib import Path

_SYSTEM_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_HOME_USER_RE = re.compile(r"^/home/([^/]+)(?:/|$)")


def normalize_system_name(value: str | None) -> str:
    cleaned = re.sub(r"[^a-z0-9_-]", "", str(value or "").strip().lower())
    if cleaned and _SYSTEM_NAME_RE.match(cleaned):
        return cleaned
    return "default"


def derive_system_name_from_path(path: str | Path | None) -> str | None:
    if not path:
        return None
    normalized = str(path).replace("\\", "/").strip()
    match = _HOME_USER_RE.match(normalized)
    if not match:
        return None
    name = normalize_system_name(match.group(1))
    return name if name != "default" else None


def resolve_system_name(
    *,
    explicit: str | None = None,
    workspace_root: Path | str | None = None,
    local_path: str | Path | None = None,
) -> str:
    # Linked workspace folders under /home/<user>/ always use that user's skills home
    # so skills created in one folder are installed for that same folder context.
    for candidate in (local_path, workspace_root):
        derived = derive_system_name_from_path(candidate)
        if derived:
            return derived

    if explicit and str(explicit).strip():
        normalized = normalize_system_name(explicit)
        if normalized != "default":
            return normalized

    return normalize_system_name(getpass.getuser())
