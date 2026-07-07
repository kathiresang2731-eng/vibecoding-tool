from __future__ import annotations

import base64
import textwrap
from typing import Any

from backend.agents.artifacts import ArtifactValidationError, validate_project_artifact
from backend.agents.project_workspace import is_standalone_code_source_path
from backend.agents.schema import ResponseContractError
from backend.agents.theme_inference import ThemeContractError, merge_theme_with_context

DOCUMENT_ARTIFACT_EXTENSIONS = (".md", ".txt", ".csv", ".pdf")
DOCUMENT_ARTIFACT_PREFIXES = ("docs/", "reports/", "research/", "plans/", "notes/")


def enrich_artifact_response_from_runtime(runtime_result: dict[str, Any]) -> dict[str, Any]:
  artifact = (
    dict(runtime_result.get("artifact_response") or {})
    if isinstance(runtime_result.get("artifact_response"), dict)
    else {}
  )
  runtime = runtime_result.get("runtime") if isinstance(runtime_result.get("runtime"), dict) else {}
  if runtime:
    artifact["runtime"] = runtime
    for key in ("changed_paths", "changed_file_paths", "output_text", "status", "clarification_question"):
      if not artifact.get(key) and runtime.get(key):
        artifact[key] = runtime[key]
  return artifact


def normalize_generated_website_artifact(response: dict[str, Any]) -> dict[str, Any]:
  if not isinstance(response, dict):
    raise ResponseContractError("Website artifact response must be a JSON object.")

  generated_website = response.get("generated_website")
  if generated_website is None:
    orchestration_flow = response.get("orchestration_flow")
    if isinstance(orchestration_flow, dict):
      generated_website = orchestration_flow.get("generated_website")

  if not isinstance(generated_website, dict):
    raise ResponseContractError("Website artifact response missing generated_website.")

  return normalize_generated_website(generated_website)


def normalize_simple_code_artifact(response: dict[str, Any]) -> dict[str, Any]:
  if not isinstance(response, dict):
    raise ResponseContractError("Simple code response must be a JSON object.")

  generated_website = response.get("generated_website")
  if not isinstance(generated_website, dict):
    raise ResponseContractError("Simple code response missing generated_website.")

  files = generated_website.get("files") if isinstance(generated_website.get("files"), list) else []
  standalone_files = [
    file_item
    for file_item in files
    if isinstance(file_item, dict) and is_standalone_code_source_path(str(file_item.get("path") or ""))
  ]
  if standalone_files:
    files = standalone_files
  elif files:
    raise ResponseContractError("Simple code response must return standalone code files, not website scaffold files.")
  first_path = ""
  for file_item in files:
    if isinstance(file_item, dict) and isinstance(file_item.get("path"), str) and file_item["path"].strip():
      first_path = file_item["path"].strip()
      break

  normalized = {
    **generated_website,
    "title": text_value(generated_website.get("title"), "Standalone Code"),
    "headline": text_value(generated_website.get("headline"), "Standalone Code File"),
    "subheadline": text_value(
      generated_website.get("subheadline"),
      f"Generated standalone code file{f' {first_path}' if first_path else ''}.",
    ),
    "primary_cta": text_value(generated_website.get("primary_cta"), "Open code"),
    "secondary_cta": text_value(generated_website.get("secondary_cta"), "Run code"),
    "preview_html": "",
    "theme": normalize_theme(generated_website.get("theme") or _default_non_website_artifact_theme()),
    "sections": generated_website.get("sections") if isinstance(generated_website.get("sections"), list) and generated_website.get("sections") else [
      {
        "name": "Generated File",
        "purpose": "Record the standalone code artifact.",
        "content": f"Generated {first_path or 'code file'}.",
        "items": [first_path] if first_path else [],
      }
    ],
    "files": files,
  }
  return normalize_generated_website(normalized)


def normalize_document_artifact(response: dict[str, Any], *, user_prompt: str = "") -> dict[str, Any]:
  if not isinstance(response, dict):
    raise ResponseContractError("Document artifact response must be a JSON object.")

  generated_website = response.get("generated_website")
  if not isinstance(generated_website, dict):
    document_artifact = response.get("document_artifact")
    generated_website = document_artifact if isinstance(document_artifact, dict) else {}

  raw_files = generated_website.get("files") if isinstance(generated_website.get("files"), list) else []
  wants_pdf = _document_request_wants_pdf(user_prompt) or any(
    isinstance(file_item, dict) and str(file_item.get("path") or "").strip().lower().endswith(".pdf")
    for file_item in raw_files
  )
  files: list[dict[str, Any]] = []
  for file_item in raw_files:
    if not isinstance(file_item, dict):
      continue
    path = text_value(file_item.get("path"), "")
    content = file_item.get("code") if "code" in file_item else file_item.get("content")
    if not path or not isinstance(content, str) or not content.strip():
      continue
    normalized_path = _normalize_document_artifact_path(path, wants_pdf=wants_pdf)
    normalized_content = (
      _build_pdf_data_url_from_text(content, title=text_value(generated_website.get("title"), "Document Artifact"))
      if normalized_path.lower().endswith(".pdf")
      else content
    )
    files.append(
      {
        "path": normalized_path,
        "purpose": text_value(file_item.get("purpose"), "Generated document artifact."),
        "code": normalized_content,
      }
    )

  if not files:
    raise ResponseContractError("Document artifact response must include at least one .md, .txt, .csv, or .pdf file.")

  first_path = files[0]["path"]
  normalized = {
    **generated_website,
    "title": text_value(generated_website.get("title"), "Document Artifact"),
    "headline": text_value(generated_website.get("headline"), "Generated Document"),
    "subheadline": text_value(
      generated_website.get("subheadline"),
      f"Generated document file {first_path}.",
    ),
    "primary_cta": text_value(generated_website.get("primary_cta"), "Open document"),
    "secondary_cta": text_value(generated_website.get("secondary_cta"), "Review content"),
    "preview_html": "",
    "theme": normalize_theme(generated_website.get("theme") or _default_non_website_artifact_theme()),
    "sections": generated_website.get("sections") if isinstance(generated_website.get("sections"), list) and generated_website.get("sections") else [
      {
        "name": "Generated Document",
        "purpose": "Record the requested documentation, research, or planning artifact.",
        "content": f"Generated {first_path}.",
        "items": [item["path"] for item in files],
      }
    ],
    "files": files,
  }
  return normalize_generated_website(normalized)


def _normalize_document_artifact_path(path: str, *, wants_pdf: bool = False) -> str:
  cleaned = str(path or "").replace("\\", "/").strip().strip("/")
  while cleaned.startswith("./"):
    cleaned = cleaned[2:]
  lowered = cleaned.lower()
  if "/" in cleaned:
    if not cleaned.startswith(DOCUMENT_ARTIFACT_PREFIXES):
      cleaned = f"docs/{cleaned.split('/')[-1]}"
      lowered = cleaned.lower()
  if wants_pdf:
    if lowered.endswith(".pdf.md"):
      cleaned = cleaned[:-3]
      lowered = cleaned.lower()
    elif lowered.endswith((".md", ".txt", ".csv")):
      cleaned = f"{cleaned.rsplit('.', 1)[0]}.pdf"
      lowered = cleaned.lower()
    elif not lowered.endswith(".pdf"):
      cleaned = f"{cleaned}.pdf"
      lowered = cleaned.lower()
  elif not lowered.endswith(DOCUMENT_ARTIFACT_EXTENSIONS):
    cleaned = f"{cleaned}.md"
  return cleaned


def _default_non_website_artifact_theme() -> dict[str, Any]:
  return {
    "colors": {
      "primary": "#111827",
      "secondary": "#4f46e5",
      "accent": "#0f766e",
      "background": "#ffffff",
      "text": "#111827",
    },
    "style_direction": "Clean document-first artifact",
  }


def _document_request_wants_pdf(prompt: str) -> bool:
  lowered = str(prompt or "").strip().lower()
  return bool(lowered) and any(token in lowered for token in (" as pdf", " in pdf", ".pdf", "pdf file", "pdf format"))


def _build_pdf_data_url_from_text(text: str, *, title: str = "Document") -> str:
  pdf_bytes = _build_simple_pdf_bytes(text, title=title)
  return "data:application/pdf;base64," + base64.b64encode(pdf_bytes).decode("ascii")


def _build_simple_pdf_bytes(text: str, *, title: str = "Document") -> bytes:
  wrapped_lines: list[str] = []
  for raw_line in str(text or "").splitlines() or [""]:
    line = raw_line.rstrip()
    chunks = textwrap.wrap(line, width=92, break_long_words=True, break_on_hyphens=False) or [""]
    wrapped_lines.extend(chunks)
  page_size = 44
  pages = [wrapped_lines[index:index + page_size] for index in range(0, len(wrapped_lines), page_size)] or [[""]]

  def escape_pdf(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

  objects: list[bytes] = []
  page_refs: list[int] = []
  font_obj = 3
  next_obj = 4
  for page_lines in pages:
    content_stream = ["BT", "/F1 11 Tf", "50 785 Td", "14 TL"]
    for line in page_lines:
      content_stream.append(f"({escape_pdf(line[:200])}) Tj")
      content_stream.append("T*")
    content_stream.append("ET")
    stream_bytes = "\n".join(content_stream).encode("latin-1", errors="replace")
    content_obj = next_obj
    page_obj = next_obj + 1
    next_obj += 2
    objects.append(
      (
        f"{content_obj} 0 obj\n<< /Length {len(stream_bytes)} >>\nstream\n".encode("latin-1")
        + stream_bytes
        + b"\nendstream\nendobj\n"
      )
    )
    objects.append(
      (
        f"{page_obj} 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        f"/Resources << /Font << /F1 {font_obj} 0 R >> >> /Contents {content_obj} 0 R >>\nendobj\n"
      ).encode("latin-1")
    )
    page_refs.append(page_obj)

  catalog = b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
  pages_obj = (
    f"2 0 obj\n<< /Type /Pages /Count {len(page_refs)} /Kids [{' '.join(f'{ref} 0 R' for ref in page_refs)}] >>\nendobj\n"
  ).encode("latin-1")
  font = b"3 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n"
  info_obj_num = next_obj
  info = (
    f"{info_obj_num} 0 obj\n<< /Title ({escape_pdf(title[:120])}) /Producer (Worktual) >>\nendobj\n"
  ).encode("latin-1")

  object_blobs = [catalog, pages_obj, font, *objects, info]
  pdf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
  offsets = [0]
  for blob in object_blobs:
    offsets.append(len(pdf))
    pdf.extend(blob)
  startxref = len(pdf)
  object_count = len(object_blobs)
  pdf.extend(f"xref\n0 {object_count + 1}\n".encode("latin-1"))
  pdf.extend(b"0000000000 65535 f \n")
  for offset in offsets[1:]:
    pdf.extend(f"{offset:010d} 00000 n \n".encode("latin-1"))
  pdf.extend(
    (
      f"trailer\n<< /Size {object_count + 1} /Root 1 0 R /Info {info_obj_num} 0 R >>\n"
      f"startxref\n{startxref}\n%%EOF"
    ).encode("latin-1")
  )
  return bytes(pdf)


def normalize_generated_website(generated_website: dict[str, Any]) -> dict[str, Any]:
  try:
    return validate_project_artifact(generated_website)
  except ArtifactValidationError as exc:
    raise ResponseContractError(str(exc)) from exc


def normalize_loose_generated_website(
  generated_website: dict[str, Any],
  *,
  intent: str = "",
  prompt: str = "",
  artifact_response: dict[str, Any] | None = None,
) -> dict[str, Any]:
  raw = dict(generated_website) if isinstance(generated_website, dict) else {}
  artifact = artifact_response if isinstance(artifact_response, dict) else {}
  summary = str(
    raw.get("subheadline")
    or raw.get("summary")
    or artifact.get("summary")
    or artifact.get("clarification_question")
    or prompt
    or ""
  ).strip()
  default_sub = (
    "Website updated from your prompt."
    if intent == "website_update"
    else "Website generated from your prompt."
  )
  title = str(raw.get("title") or "Generated Website").strip() or "Generated Website"
  sections = raw.get("sections") if isinstance(raw.get("sections"), list) else []
  if not sections:
    sections = [
      {
        "name": "Overview",
        "purpose": "Describe the generated or updated website.",
        "content": summary or default_sub,
        "items": [],
      }
    ]
  files = raw.get("files") if isinstance(raw.get("files"), list) else []
  theme: dict[str, Any] | None = None
  if isinstance(raw.get("theme"), dict):
    try:
      theme = merge_theme_with_context(
        raw.get("theme"),
        prompt,
        title,
        raw.get("headline"),
        summary,
      )
    except ThemeContractError as exc:
      raise ResponseContractError(str(exc)) from exc
  elif intent != "website_update":
    raise ResponseContractError(
      "Generated website theme is missing. Backend static theme fallback is disabled; "
      "retry the model artifact with explicit LLM/user theme values."
    )

  normalized = {
    **raw,
    "title": title,
    "headline": str(raw.get("headline") or title).strip() or title,
    "subheadline": summary or default_sub,
    "primary_cta": str(raw.get("primary_cta") or "Preview site").strip() or "Preview site",
    "secondary_cta": str(raw.get("secondary_cta") or "Edit files").strip() or "Edit files",
    "preview_html": str(raw.get("preview_html") or ""),
    "sections": sections,
    "files": files,
  }
  if theme is not None:
    normalized["theme"] = theme
  return normalized


def normalize_theme(theme: Any) -> dict[str, Any]:
  try:
    return merge_theme_with_context(theme)
  except ThemeContractError as exc:
    raise ResponseContractError(str(exc)) from exc


def normalize_sections(sections: Any) -> list[dict[str, Any]]:
  normalized: list[dict[str, Any]] = []
  if isinstance(sections, list):
    for index, section in enumerate(sections, start=1):
      if not isinstance(section, dict):
        continue
      name = text_value(section.get("name"), f"Section {index}")
      normalized.append(
        {
          "name": name,
          "purpose": text_value(section.get("purpose"), f"Define the {name} section."),
          "content": text_value(section.get("content"), f"{name} content generated from the prompt."),
          "items": normalize_string_list(
            section.get("items"),
            [f"{name} copy", "Responsive layout", "Conversion-focused CTA"],
          ),
        }
      )

  if normalized:
    return normalized

  return [
    {
      "name": "Hero",
      "purpose": "Introduce the generated website.",
      "content": "A clear hero section generated from the user prompt.",
      "items": ["Headline", "Subheadline", "Primary CTA"],
    }
  ]


def normalize_files(files: Any, title: str, headline: str) -> list[dict[str, Any]]:
  normalized: list[dict[str, Any]] = []
  if isinstance(files, list):
    for file_item in files:
      if not isinstance(file_item, dict):
        continue
      path = text_value(file_item.get("path"), "src/pages/Home.jsx")
      normalized.append(
        {
          "path": path,
          "purpose": text_value(file_item.get("purpose"), "Generated website file."),
          "code": text_value(file_item.get("code"), build_default_home_code(title, headline)),
        }
      )

  if normalized:
    return normalized

  return [
    {
      "path": "src/pages/Home.jsx",
      "purpose": "Generated React homepage.",
      "code": build_default_home_code(title, headline),
    }
  ]


def build_default_home_code(title: str, headline: str) -> str:
  return (
    "export default function Home() {\n"
    "  return (\n"
    "    <main className=\"min-h-screen bg-[var(--page-bg)] px-6 py-16 text-[var(--page-text)]\">\n"
    f"      <p className=\"text-sm font-bold text-[var(--accent-color)]\">{title}</p>\n"
    f"      <h1 className=\"mt-4 max-w-3xl text-5xl font-black\">{headline}</h1>\n"
    "    </main>\n"
    "  );\n"
    "}\n"
  )


def normalize_string_list(value: Any, fallback: list[str]) -> list[str]:
  if isinstance(value, list):
    normalized = [item.strip() for item in value if isinstance(item, str) and item.strip()]
    if normalized:
      return normalized
  return fallback


def text_value(value: Any, fallback: str) -> str:
  if isinstance(value, str) and value.strip():
    return value.strip()
  return fallback
