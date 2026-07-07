"""Platform-owned files that must not be modified during website updates."""

from __future__ import annotations

from typing import Any

LOCKED_PLATFORM_UPDATE_PATHS: frozenset[str] = frozenset(
  {
    "index.html",
    "package.json",
    "package-lock.json",
    "src/index.css",
    "tailwind.config.js",
    "vite.config.js",
  }
)

LOCKED_PLATFORM_UPDATE_BASENAMES: frozenset[str] = frozenset(
  path.rsplit("/", 1)[-1].lower() for path in LOCKED_PLATFORM_UPDATE_PATHS
)

VISUAL_STYLE_UPDATE_KINDS: frozenset[str] = frozenset(
  {
    "theme_color_update",
    "style_reference_update",
  }
)

TITLE_METADATA_UPDATE_KINDS: frozenset[str] = frozenset(
  {
    "brand_name_update",
    "document_title_update",
  }
)

SCAFFOLD_EXEMPT_PERSIST_REASONS: frozenset[str] = frozenset(
  {
    "platform_vite_scaffold",
    "scaffold_repair",
    "greenfield_scaffold",
  }
)

WEBSITE_UPDATE_INTENTS: frozenset[str] = frozenset({"website_update"})


def normalize_platform_path(path: str) -> str:
  return str(path or "").strip().replace("\\", "/")


def is_locked_platform_update_path(path: str) -> bool:
  normalized = normalize_platform_path(path)
  if not normalized:
    return False
  if normalized in LOCKED_PLATFORM_UPDATE_PATHS:
    return True
  basename = normalized.rsplit("/", 1)[-1].lower()
  if basename in LOCKED_PLATFORM_UPDATE_BASENAMES:
    return True
  if basename.startswith("vite.config.") or basename.startswith("tailwind.config."):
    return basename.rsplit(".", 1)[0] in {"vite.config", "tailwind.config"}
  return False


def is_platform_lock_exempt_for_request(path: str, *, request_kind: str = "") -> bool:
  """Allow real app-owned update surfaces for matching update intents only.

  The lock still protects dependency/build/runtime files by default. For live
  website updates, though, global CSS/theme files and HTML title metadata are
  legitimate app surfaces, not static backend shortcuts.
  """

  normalized = normalize_platform_path(path)
  lowered = normalized.lower()
  basename = lowered.rsplit("/", 1)[-1]
  kind = str(request_kind or "").strip().lower()
  if kind in VISUAL_STYLE_UPDATE_KINDS:
    return lowered == "src/index.css" or basename.startswith("tailwind.config.")
  if kind in TITLE_METADATA_UPDATE_KINDS:
    return lowered == "index.html"
  return False


def platform_file_locks_active(
  *,
  intent: str = "",
  persist_reason: str = "",
) -> bool:
  if str(persist_reason or "").strip() in SCAFFOLD_EXEMPT_PERSIST_REASONS:
    return False
  return str(intent or "").strip().lower() in WEBSITE_UPDATE_INTENTS


def guard_locked_platform_write(
  path: str,
  *,
  intent: str = "",
  persist_reason: str = "",
  previous_content: str | None = None,
  request_kind: str = "",
) -> dict[str, Any] | None:
  if not platform_file_locks_active(intent=intent, persist_reason=persist_reason):
    return None
  if not is_locked_platform_update_path(path):
    return None
  if is_platform_lock_exempt_for_request(path, request_kind=request_kind):
    return None
  if previous_content is not None and not str(previous_content).strip():
    return None
  return {
    "error": (
      f"Blocked update to locked platform file {normalize_platform_path(path)}. "
      "During website updates, index.html, package.json, package-lock.json, "
      "src/index.css, tailwind.config.js, and vite.config.js are read-only. "
      "Edit app pages, components, or src/App.jsx instead."
    ),
    "path": normalize_platform_path(path),
    "recoverable": True,
    "blocked_platform_lock": True,
    "locked_platform_file": True,
  }


def filter_locked_platform_writes(
  write_payload: list[dict[str, str]],
  *,
  files_before_map: dict[str, str] | None = None,
  intent: str = "",
  persist_reason: str = "",
  request_kind: str = "",
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
  if not platform_file_locks_active(intent=intent, persist_reason=persist_reason):
    return write_payload, []

  before = files_before_map or {}
  accepted: list[dict[str, str]] = []
  rejected: list[dict[str, Any]] = []
  for item in write_payload:
    path = normalize_platform_path(str(item.get("path") or ""))
    content = str(item.get("content") or "")
    if not path:
      continue
    previous = before.get(path, "")
    blocked = guard_locked_platform_write(
      path,
      intent=intent,
      persist_reason=persist_reason,
      previous_content=previous if path in before else "",
      request_kind=request_kind,
    )
    if blocked and (path in before or previous.strip()):
      rejected.append(
        {
          "path": path,
          "reason": "locked_platform_file",
          "detail": blocked.get("error"),
        }
      )
      continue
    accepted.append({"path": path, "content": content})
  return accepted, rejected


def locked_platform_paths_label() -> str:
  return ", ".join(sorted(LOCKED_PLATFORM_UPDATE_PATHS))
