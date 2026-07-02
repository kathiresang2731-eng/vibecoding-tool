from __future__ import annotations

import base64
import binascii
from typing import Any

from ..budget_config import AGENT_BUDGETS

MAX_PROMPT_ATTACHMENTS = 8
MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024
TEXT_FILE_EXTENSIONS = {
  ".txt",
  ".md",
  ".markdown",
  ".json",
  ".js",
  ".jsx",
  ".ts",
  ".tsx",
  ".css",
  ".html",
  ".htm",
  ".log",
  ".csv",
  ".xml",
  ".yaml",
  ".yml",
  ".py",
  ".env",
  ".svg",
}
IMAGE_MIME_PREFIX = "image/"


def _attachment_name(item: dict[str, Any]) -> str:
  return str(item.get("name") or item.get("filename") or "attachment").strip() or "attachment"


def _attachment_mime(item: dict[str, Any]) -> str:
  mime = str(item.get("mime_type") or item.get("mimeType") or item.get("type") or "").strip().lower()
  if mime:
    return mime
  name = _attachment_name(item).lower()
  if name.endswith((".png",)):
    return "image/png"
  if name.endswith((".jpg", ".jpeg")):
    return "image/jpeg"
  if name.endswith(".gif"):
    return "image/gif"
  if name.endswith(".webp"):
    return "image/webp"
  if name.endswith(".svg"):
    return "image/svg+xml"
  return "application/octet-stream"


def _attachment_kind(item: dict[str, Any], mime: str) -> str:
  explicit = str(item.get("kind") or "").strip().lower()
  if explicit in {"image", "file"}:
    return explicit
  return "image" if mime.startswith(IMAGE_MIME_PREFIX) else "file"


def _decode_attachment_bytes(item: dict[str, Any]) -> bytes:
  raw = str(item.get("content_base64") or item.get("data") or "").strip()
  if not raw:
    return b""
  if raw.startswith("data:") and ";base64," in raw:
    raw = raw.split(";base64,", 1)[1]
  try:
    return base64.b64decode(raw, validate=False)
  except (binascii.Error, ValueError):
    return b""


def normalize_prompt_attachments(raw: Any) -> list[dict[str, str]]:
  if not isinstance(raw, list):
    return []

  normalized: list[dict[str, str]] = []
  for item in raw[:MAX_PROMPT_ATTACHMENTS]:
    if not isinstance(item, dict):
      continue
    payload = item.get("attachment") if isinstance(item.get("attachment"), dict) else item
    if not isinstance(payload, dict):
      continue
    content_bytes = _decode_attachment_bytes(payload)
    if not content_bytes:
      continue
    if len(content_bytes) > MAX_ATTACHMENT_BYTES:
      raise ValueError(f"Attachment {_attachment_name(payload)} exceeds the 5 MB limit.")
    mime = _attachment_mime(payload)
    kind = _attachment_kind(payload, mime)
    normalized.append(
      {
        "name": _attachment_name(payload),
        "mime_type": mime,
        "kind": kind,
        "content_base64": base64.b64encode(content_bytes).decode("ascii"),
      }
    )
  return normalized


def gemini_inline_image_parts(attachments: list[dict[str, str]]) -> list[dict[str, Any]]:
  parts: list[dict[str, Any]] = []
  for item in attachments:
    if item.get("kind") != "image":
      continue
    mime = str(item.get("mime_type") or "")
    if not mime.startswith(IMAGE_MIME_PREFIX):
      continue
    data = str(item.get("content_base64") or "").strip()
    if not data:
      continue
    parts.append({"inlineData": {"mimeType": mime, "data": data}})
  return parts


def _is_text_attachment(item: dict[str, str]) -> bool:
  mime = str(item.get("mime_type") or "")
  if mime.startswith("text/") or mime in {"application/json", "application/javascript", "image/svg+xml"}:
    return True
  name = _attachment_name(item).lower()
  return any(name.endswith(ext) for ext in TEXT_FILE_EXTENSIONS)


def format_attachment_context_block(attachments: list[dict[str, str]]) -> str:
  if not attachments:
    return ""

  lines = [
    "User-provided attachments (use these together with the text prompt):",
  ]
  image_names = [_attachment_name(item) for item in attachments if item.get("kind") == "image"]
  if image_names:
    lines.append(
      "- Image attachment(s) are included inline in this request: "
      + ", ".join(image_names)
      + ". Inspect them for UI bugs, layout issues, screenshots, or design references."
    )

  for item in attachments:
    if item.get("kind") == "image" or not _is_text_attachment(item):
      if item.get("kind") != "image":
        lines.append(f"- Binary file attached: {_attachment_name(item)} ({item.get('mime_type') or 'unknown type'})")
      continue
    raw = _decode_attachment_bytes(item)
    try:
      text = raw.decode("utf-8")
    except UnicodeDecodeError:
      lines.append(f"- Could not decode text attachment: {_attachment_name(item)}")
      continue
    if len(text) > AGENT_BUDGETS.attachment_text_chars:
      text = text[:AGENT_BUDGETS.attachment_text_chars] + "\n... (truncated)"
    lines.append(f"\n### Attached file: {_attachment_name(item)}\n```\n{text}\n```")
  return "\n".join(lines)


def chat_attachment_views(attachments: list[dict[str, str]]) -> list[dict[str, Any]]:
  views: list[dict[str, Any]] = []
  for item in attachments:
    mime = str(item.get("mime_type") or "")
    kind = str(item.get("kind") or "file")
    content_base64 = str(item.get("content_base64") or "")
    preview_url = f"data:{mime};base64,{content_base64}" if kind == "image" and content_base64 else ""
    views.append(
      {
        "name": _attachment_name(item),
        "mime_type": mime,
        "kind": kind,
        "preview_url": preview_url,
        "content_base64": content_base64 if kind == "image" else "",
      }
    )
  return views


def enrich_prompt_with_attachments(prompt: str, attachments: list[dict[str, str]]) -> str:
  block = format_attachment_context_block(attachments)
  cleaned = str(prompt or "").strip()
  if block and cleaned:
    return f"{cleaned}\n\n{block}"
  if block:
    return block
  return cleaned
