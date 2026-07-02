import base64

import pytest

from backend.agents.gemini_tool_calling.messages import messages_to_gemini_contents
from backend.agents.prompting.attachments import (
  chat_attachment_views,
  enrich_prompt_with_attachments,
  gemini_inline_image_parts,
  normalize_prompt_attachments,
)


def test_normalize_prompt_attachments_accepts_image_payload():
  png_bytes = base64.b64encode(b"fake-png").decode("ascii")
  attachments = normalize_prompt_attachments(
    [
      {
        "name": "screenshot.png",
        "mime_type": "image/png",
        "content_base64": png_bytes,
        "kind": "image",
      }
    ]
  )
  assert len(attachments) == 1
  assert attachments[0]["name"] == "screenshot.png"
  assert attachments[0]["kind"] == "image"


def test_chat_attachment_views_builds_data_url_preview() -> None:
  png_bytes = base64.b64encode(b"fake-png").decode("ascii")
  views = chat_attachment_views(
    [{"name": "screenshot.png", "mime_type": "image/png", "kind": "image", "content_base64": png_bytes}]
  )
  assert views[0]["preview_url"].startswith("data:image/png;base64,")
  assert views[0]["content_base64"] == png_bytes


def test_enrich_prompt_with_attachments_adds_text_file_contents():
  text = base64.b64encode(b"export const value = 1;").decode("ascii")
  enriched = enrich_prompt_with_attachments(
    "Fix this module",
    normalize_prompt_attachments(
      [
        {
          "name": "src/App.jsx",
          "mime_type": "text/javascript",
          "content_base64": text,
        }
      ]
    ),
  )
  assert "Fix this module" in enriched
  assert "Attached file: src/App.jsx" in enriched
  assert "export const value = 1;" in enriched


def test_messages_to_gemini_contents_includes_inline_image_parts():
  png_bytes = base64.b64encode(b"fake-png").decode("ascii")
  contents = messages_to_gemini_contents(
    [
      {
        "role": "user",
        "content": "Fix the UI bug in the screenshot.",
        "attachments": [
          {
            "name": "bug.png",
            "mime_type": "image/png",
            "content_base64": png_bytes,
            "kind": "image",
          }
        ],
      }
    ]
  )
  assert len(contents) == 1
  parts = contents[0]["parts"]
  assert any("inlineData" in part for part in parts)
  assert any("text" in part for part in parts)
