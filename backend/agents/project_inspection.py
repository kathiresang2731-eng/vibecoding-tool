from __future__ import annotations

import re
from typing import Any


KEY_PROJECT_PATHS = (
  "package.json",
  "index.html",
  "src/app.jsx",
  "src/app.tsx",
  "src/main.jsx",
  "src/main.tsx",
)
PROJECT_INFO_MAX_FILES = 10
PROJECT_INFO_MAX_CHARS_PER_FILE = 2600


def build_project_inspection_context(
  files: list[dict[str, Any]] | None,
  *,
  question: str = "",
  project_name: str = "",
  local_path: str = "",
  chat_messages: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
  source_files = [
    {
      "path": str(item.get("path") or "").replace("\\", "/").strip(),
      "content": str(item.get("content") or item.get("code") or ""),
    }
    for item in files or []
    if isinstance(item, dict) and str(item.get("path") or "").strip()
  ]
  resolved_reference = resolve_project_info_reference_path(
    question,
    source_files,
    chat_messages=chat_messages,
  )
  target_resolution = build_target_resolution(
    question,
    source_files,
    chat_messages=chat_messages,
    resolved_reference=resolved_reference,
  )
  selected = select_project_info_files(
    source_files,
    question=question,
    preferred_path=resolved_reference.get("path", ""),
  )
  return {
    "project_name": project_name,
    "local_path": local_path,
    "file_count": len(source_files),
    "file_tree": [item["path"] for item in source_files[:240]],
    "resolved_reference": resolved_reference,
    "target_resolution": target_resolution,
    "selected_live_files": [
      {
        "path": item["path"],
        "content_excerpt": project_info_excerpt(
          item["content"],
          question=question,
        ),
        "button_facts": extract_button_facts(item["content"]),
      }
      for item in selected
    ],
    "inspection_policy": (
      "Answer from these live files. Distinguish the folder/project name, package name, "
      "HTML page title, and visible website brand. Never invent missing values."
    ),
  }


def build_target_resolution(
  question: str,
  files: list[dict[str, Any]] | None,
  *,
  chat_messages: list[dict[str, Any]] | None = None,
  resolved_reference: dict[str, Any] | None = None,
) -> dict[str, Any]:
  """Resolve the page/file/button the user is referring to from live project anchors."""
  source_files = [
    {
      "path": str(item.get("path") or "").replace("\\", "/").strip(),
      "content": str(item.get("content") or item.get("code") or ""),
    }
    for item in files or []
    if isinstance(item, dict) and str(item.get("path") or "").strip()
  ]
  prompt = str(question or "")
  messages = list(chat_messages or [])
  reference = resolved_reference if isinstance(resolved_reference, dict) else {}
  sources: list[str] = []
  path = str(reference.get("path") or "").strip()
  if path:
    sources.append(str(reference.get("source") or "reference_resolution"))
  if not path:
    path = explicit_project_path_from_text(prompt, source_files)
    if path:
      sources.append("current_prompt_path")
  if not path:
    path = best_page_path_for_text(prompt, source_files)
    if path:
      sources.append("current_prompt_page")
  if not path and asks_with_contextual_reference(prompt):
    for message in reversed(messages):
      content = str(message.get("content") or message.get("display_content") or "")
      path = explicit_project_path_from_text(content, source_files) or best_page_path_for_text(content, source_files)
      if path:
        sources.append("chat_history")
        break

  selected_file = next((item for item in source_files if item["path"] == path), None)
  if selected_file is None and path:
    path = ""

  button = _resolve_target_button(prompt, selected_file, messages) if selected_file else {}
  if button:
    sources.append(button.get("source") or "button_anchor")

  confidence = 0.0
  if path:
    confidence += 0.42
  if "chat_history" in sources:
    confidence += 0.18
  if any(source.startswith("current_prompt") for source in sources):
    confidence += 0.18
  if button:
    confidence += 0.22
  confidence = min(0.99, round(confidence, 2))

  page_name = _page_name_for_path(path)
  route = _route_for_path(path)
  status = "resolved" if path else ("unresolved" if asks_with_contextual_reference(prompt) else "not_needed")
  resolved_files = [path] if path else []
  summary_parts = []
  if page_name:
    summary_parts.append(page_name)
  if path:
    summary_parts.append(path)
  if button.get("label"):
    summary_parts.append(f"button: {button['label']}")

  return {
    "status": status,
    "resolved_page": page_name,
    "resolved_route": route,
    "resolved_files": resolved_files,
    "resolved_component": page_name,
    "resolved_element": button or {},
    "resolved_button": str(button.get("label") or "") if button else "",
    "confidence": confidence,
    "source": " + ".join(list(dict.fromkeys(source for source in sources if source))) or "",
    "summary": " | ".join(summary_parts),
  }


def clarification_for_ambiguous_update_target(
  prompt: str,
  files: list[dict[str, Any]] | None,
  *,
  target_resolution: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
  source_files = [
    {
      "path": str(item.get("path") or "").replace("\\", "/").strip(),
      "content": str(item.get("content") or item.get("code") or ""),
    }
    for item in files or []
    if isinstance(item, dict) and str(item.get("path") or "").strip()
  ]
  resolution = target_resolution if isinstance(target_resolution, dict) else {}
  resolved_path = str(resolution.get("resolved_files", [""])[0] if isinstance(resolution.get("resolved_files"), list) and resolution.get("resolved_files") else "").strip()
  resolved_button = str(resolution.get("resolved_button") or "").strip()
  selected_file = next((item for item in source_files if item["path"] == resolved_path), None)
  if not selected_file:
    return None
  lowered = str(prompt or "").lower()
  if not _looks_like_ambiguous_button_issue(lowered):
    return None
  if resolved_button and _is_referential_button_followup(lowered):
    return None
  facts = extract_button_facts(selected_file.get("content", ""))
  labels = [str(label).strip() for label in facts.get("labels") or [] if str(label).strip()]
  if len(labels) <= 1:
    return None
  page_name = str(resolution.get("resolved_page") or _page_name_for_path(resolved_path) or "that")
  label_preview = ", ".join(labels[:6])
  if len(labels) > 6:
    label_preview += f", and {len(labels) - 6} more"
  return {
    "missing_fields": ["button_identifier", "expected_behavior"],
    "clarification_question": (
      f"I can fix that on the {page_name} page. Which button is not working, and what should happen when you click it? "
      f"Visible buttons I found: {label_preview}."
    ),
  }


def build_resolved_update_target_context(
  prompt: str,
  files: list[dict[str, Any]] | None,
  *,
  chat_messages: list[dict[str, Any]] | None = None,
) -> str:
  resolution = build_target_resolution(prompt, files, chat_messages=chat_messages)
  path = str((resolution.get("resolved_files") or [""])[0] if isinstance(resolution.get("resolved_files"), list) and resolution.get("resolved_files") else "").strip()
  page = str(resolution.get("resolved_page") or "").strip()
  button = str(resolution.get("resolved_button") or "").strip()
  if not path and not page and not button:
    return ""
  lines = [
    "Resolved active update target from same-topic memory and live project anchors:",
  ]
  if page:
    lines.append(f"- page: {page}")
  if path:
    lines.append(f"- file: {path}")
  if button:
    lines.append(f"- button: {button}")
  lines.append("Use this resolved target unless the latest message explicitly changes the page or control.")
  return "\n".join(lines)


def select_project_info_files(
  files: list[dict[str, str]],
  *,
  question: str,
  preferred_path: str = "",
) -> list[dict[str, str]]:
  terms = {
    value
    for value in re.findall(r"[a-z][a-z0-9_-]{2,}", question.lower())
    if value not in {"what", "which", "this", "that", "website", "project", "current"}
  }

  def score(item: dict[str, str]) -> tuple[int, int, str]:
    path = item["path"].lower()
    content = item["content"].lower()
    value = 0
    if preferred_path and item["path"] == preferred_path:
      value += 5000
    if path in KEY_PROJECT_PATHS:
      value += 100
    if any(marker in path for marker in ("header", "navbar", "footer", "brand", "layout")):
      value += 70
    if "<title" in content or '"name"' in content:
      value += 60
    if any(marker in content for marker in ("copyright", "logo", "brand")):
      value += 40
    value += sum(20 for term in terms if term in path or term in content)
    return (-value, len(path), path)

  return sorted(files, key=score)[:PROJECT_INFO_MAX_FILES]


def resolve_project_info_reference_path(
  question: str,
  files: list[dict[str, str]],
  *,
  chat_messages: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
  current = str(question or "")
  has_contextual_reference = asks_with_contextual_reference(current)
  if has_contextual_reference:
    for message in reversed(chat_messages or []):
      content = str(message.get("content") or message.get("display_content") or "")
      path = explicit_project_path_from_text(content, files) or best_page_path_for_text(content, files)
      if path:
        return {
          "status": "resolved",
          "path": path,
          "source": "chat_history",
          "reason": "Resolved contextual reference from the recent conversation.",
        }
    return {
      "status": "unresolved",
      "path": "",
      "source": "chat_history",
      "reason": "The question used a contextual reference, but no prior page/file anchor was found.",
    }

  current_path = best_page_path_for_text(current, files)
  if not current_path:
    return {"status": "not_needed", "path": "", "source": "", "reason": ""}
  return {
    "status": "resolved",
    "path": current_path,
    "source": "current_question",
    "reason": "Current question names a page/file that exists in the project.",
  }


def asks_with_contextual_reference(question: str) -> bool:
  lowered = str(question or "").lower()
  return bool(re.search(r"\b(that|this|there|above|same|current)\s+(page|screen|module|file)?\b|\bthat page\b|\bin that page\b|\bthere\b", lowered))


def explicit_project_path_from_text(text: str, files: list[dict[str, str]]) -> str:
  paths = {item["path"] for item in files}
  for match in re.finditer(r"(src/[A-Za-z0-9_./-]+\.(?:jsx|tsx|js|ts))", str(text or "")):
    candidate = match.group(1)
    if candidate in paths:
      return candidate
  return ""


def best_page_path_for_text(text: str, files: list[dict[str, str]]) -> str:
  tokens = project_info_tokens(text)
  if not tokens:
    return ""
  best: tuple[int, str] | None = None
  for item in files:
    path = item["path"]
    if not path.startswith("src/pages/") or not path.endswith((".jsx", ".tsx", ".js", ".ts")):
      continue
    page_tokens = project_info_tokens(path.replace("src/pages/", "").rsplit(".", 1)[0])
    content_tokens = project_info_tokens(item.get("content", "")[:1200])
    score = len(tokens & page_tokens) * 100 + len(tokens & content_tokens) * 12
    if score <= 0:
      continue
    candidate = (score, path)
    if best is None or candidate[0] > best[0]:
      best = candidate
  return best[1] if best else ""


def project_info_tokens(value: str) -> set[str]:
  synonyms = {"operations": "operation", "operation": "operation", "hub": "hub"}
  stop_words = {
    "about",
    "button",
    "buttons",
    "count",
    "current",
    "file",
    "have",
    "many",
    "module",
    "page",
    "screen",
    "that",
    "there",
    "this",
    "total",
    "what",
    "which",
  }
  tokens = set()
  for token in re.findall(r"[a-z0-9]+", str(value or "").lower()):
    if len(token) < 3 or token in stop_words:
      continue
    tokens.add(synonyms.get(token, token))
  return tokens


def _page_name_for_path(path: str) -> str:
  if not path:
    return ""
  name = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
  words = re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?=[A-Z]|$)", name.replace("_", " ").replace("-", " "))
  return " ".join(word.capitalize() for word in words) or name


def _route_for_path(path: str) -> str:
  if not path.startswith("src/pages/"):
    return ""
  name = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
  route = re.sub(r"(?<!^)([A-Z])", r"-\1", name).replace("_", "-").lower()
  if route in {"dashboard", "home", "index"}:
    return "/" if route in {"home", "index"} else f"/{route}"
  return f"/{route}"


def _resolve_target_button(
  prompt: str,
  selected_file: dict[str, str] | None,
  chat_messages: list[dict[str, Any]],
) -> dict[str, Any]:
  if not selected_file:
    return {}
  if not _prompt_wants_specific_element(prompt):
    return {}
  facts = extract_button_facts(selected_file.get("content", ""))
  labels = [str(label).strip() for label in facts.get("labels") or [] if str(label).strip()]
  if not labels:
    return {}
  prompt_text = str(prompt or "")
  chat_text = "\n".join(
    str(item.get("content") or item.get("display_content") or "")
    for item in chat_messages[-8:]
    if isinstance(item, dict)
  )
  scored: list[tuple[int, str, str]] = []
  for label in labels:
    label_lower = label.lower()
    score = _label_score(label, prompt_text) * 3
    source = "current_prompt_button"
    if score <= 0:
      score = _label_score(label, chat_text)
      source = "chat_history_button"
    if label_lower in prompt_text.lower():
      score += 40
      source = "current_prompt_button"
    elif label_lower in chat_text.lower():
      score += 28
      source = "chat_history_button"
    if score > 0:
      scored.append((score, label, source))
  if not scored:
    return {}
  scored.sort(key=lambda item: (-item[0], item[1]))
  score, label, source = scored[0]
  return {
    "kind": "button",
    "label": label,
    "source": source,
    "score": score,
  }


def _label_score(label: str, text: str) -> int:
  label_tokens = project_info_tokens(label)
  text_tokens = project_info_tokens(text)
  if not label_tokens or not text_tokens:
    return 0
  score = len(label_tokens & text_tokens) * 10
  normalized_label = " ".join(_meaningful_element_tokens(label))
  normalized_text_tokens = _meaningful_element_tokens(text)
  normalized_text = " ".join(normalized_text_tokens)
  if normalized_label and normalized_text:
    if normalized_label in normalized_text or normalized_text in normalized_label:
      score += 18
  if normalized_text_tokens:
    ordered_overlap = 0
    label_parts = normalized_label.split()
    text_parts = normalized_text.split()
    for index, token in enumerate(text_parts):
      if token in label_parts:
        ordered_overlap += 1
        if index + 1 < len(text_parts):
          pair = f"{token} {text_parts[index + 1]}"
          if pair in normalized_label:
            ordered_overlap += 1
    score += ordered_overlap * 4
  return score


def _prompt_wants_specific_element(prompt: str) -> bool:
  lowered = str(prompt or "").lower()
  if asks_button_count_question(lowered):
    return False
  return bool(
    re.search(
      r"\b(that|this|specific)\s+button\b|\b(click|clicked|open|show|modal|popup|pop up|alert|navigate|redirect|fix|update|remove)\b",
      lowered,
    )
    or ("button" in lowered and "not working" in lowered)
    or ("button" in lowered and "does not work" in lowered)
  )


def _looks_like_ambiguous_button_issue(prompt: str) -> bool:
  lowered = str(prompt or "").lower()
  if "button" not in lowered:
    return False
  ambiguous_reference = bool(
    re.search(r"\b(one|a|any|some|that|this)\s+button\b", lowered)
    or "button is not working" in lowered
    or "button not working" in lowered
  )
  missing_expected_behavior = not bool(
    re.search(r"\b(should|when clicked|on click|redirect|navigate|open|show|close|delete|submit|filter|reset|save)\b", lowered)
  )
  return ambiguous_reference and missing_expected_behavior


def _is_referential_button_followup(prompt: str) -> bool:
  lowered = str(prompt or "").lower()
  return bool(
    re.search(r"\b(that|this|it)\s+button\b", lowered)
    or asks_with_contextual_reference(lowered)
  )


def _meaningful_element_tokens(value: str) -> list[str]:
  stop_words = {
    "button",
    "buttons",
    "page",
    "screen",
    "module",
    "section",
    "click",
    "clicked",
    "working",
    "works",
    "not",
    "is",
    "in",
    "on",
    "the",
  }
  alias_map = {
    "btn": "button",
    "deal": "deals",
  }
  tokens: list[str] = []
  for token in re.findall(r"[a-z0-9]+", str(value or "").lower()):
    mapped = alias_map.get(token, token)
    if len(mapped) < 3 or mapped in stop_words:
      continue
    tokens.append(mapped)
  return tokens


def build_grounded_project_info_response(question: str, project_context: dict[str, Any] | None) -> dict[str, Any] | None:
  context = project_context if isinstance(project_context, dict) else {}
  if not asks_button_count_question(question):
    return None

  selected_files = [
    item
    for item in context.get("selected_live_files") or []
    if isinstance(item, dict)
  ]
  if not selected_files:
    return None

  resolved_path = str((context.get("resolved_reference") or {}).get("path") or "")
  target = next((item for item in selected_files if item.get("path") == resolved_path), selected_files[0])
  facts = target.get("button_facts") if isinstance(target.get("button_facts"), dict) else {}
  count = int(facts.get("button_count") or 0)
  labels = [str(label).strip() for label in facts.get("labels") or [] if str(label).strip()]
  path = str(target.get("path") or "the selected file")

  if count == 0:
    message = (
      f"Summary\n"
      f"I inspected {path} from the current project context.\n\n"
      f"Result\n"
      f"No JSX button elements were found in that file."
    )
  else:
    visible = labels[:12]
    hidden_count = max(0, count - len(visible))
    label_lines = "\n".join(f"{index + 1}. {label}" for index, label in enumerate(visible))
    extra_line = f"\n\nAnd {hidden_count} more button{'s' if hidden_count != 1 else ''} in the same file." if hidden_count else ""
    message = (
      f"Summary\n"
      f"I inspected {path} from the current project context.\n\n"
      f"Result\n"
      f"The page has {count} JSX button{'s' if count != 1 else ''}.\n\n"
      f"Visible buttons\n"
      f"{label_lines}{extra_line}\n\n"
      f"Note\n"
      f"I counted rendered JSX button elements and cleaned the labels from their visible text, aria-label, or title."
    )

  return {
    "message": message,
    "next_prompt_guidance": [
      f"Ask for a button-by-button behavior audit in {path}.",
      f"Ask to update one specific button in {path}.",
      "Ask for another page's exact UI element count.",
    ],
    "grounding": {
      "path": path,
      "button_count": count,
      "labels": labels,
    },
  }


def asks_button_count_question(question: str) -> bool:
  lowered = str(question or "").lower()
  has_button = bool(re.search(r"\bbuttons?\b", lowered))
  asks_count = bool(re.search(r"\b(count|total|how many|what are|list|there)\b", lowered))
  return has_button and asks_count


def extract_button_facts(content: str) -> dict[str, Any]:
  labels: list[str] = []
  for button in iter_jsx_button_blocks(content or ""):
    label = visible_jsx_text(button["body"]).strip()
    attrs = button["attrs"] or ""
    aria = re.search(r"\baria-label\s*=\s*['\"]([^'\"]+)['\"]", attrs)
    title = re.search(r"\btitle\s*=\s*['\"]([^'\"]+)['\"]", attrs)
    label = label or (aria.group(1).strip() if aria else "") or (title.group(1).strip() if title else "")
    labels.append(clean_button_label(label) or "Unlabeled button")
  return {
    "button_count": len(labels),
    "labels": labels,
  }


def iter_jsx_button_blocks(content: str) -> list[dict[str, str]]:
  blocks: list[dict[str, str]] = []
  lowered = content.lower()
  cursor = 0
  while True:
    start = lowered.find("<button", cursor)
    if start < 0:
      break
    open_end = find_jsx_tag_end(content, start + len("<button"))
    if open_end < 0:
      cursor = start + len("<button")
      continue
    close_start = lowered.find("</button>", open_end + 1)
    if close_start < 0:
      cursor = open_end + 1
      continue
    blocks.append({
      "attrs": content[start + len("<button"):open_end],
      "body": content[open_end + 1:close_start],
    })
    cursor = close_start + len("</button>")
  return blocks


def find_jsx_tag_end(content: str, start: int) -> int:
  quote = ""
  brace_depth = 0
  index = start
  while index < len(content):
    char = content[index]
    if quote:
      if char == quote and (quote != "`" or content[index - 1:index] != "\\"):
        quote = ""
    elif char in {"'", '"', "`"}:
      quote = char
    elif char == "{":
      brace_depth += 1
    elif char == "}":
      brace_depth = max(0, brace_depth - 1)
    elif char == ">" and brace_depth == 0:
      return index
    index += 1
  return -1


def clean_button_label(label: str) -> str:
  cleaned = re.sub(r"\s+", " ", str(label or "")).strip()
  cleaned = re.sub(r"\b(className|onClick|navigate|set[A-Z][A-Za-z0-9]*|handle[A-Z][A-Za-z0-9]*)\b.*", "", cleaned).strip()
  cleaned = cleaned.strip(" ,;:-→")
  return cleaned[:120].strip()


def visible_jsx_text(value: str) -> str:
  without_tags = re.sub(r"<[^>]+>", " ", str(value or ""))
  without_expressions = re.sub(r"\{[^}]*\}", " ", without_tags)
  without_entities = without_expressions.replace("&amp;", "&")
  return re.sub(r"\s+", " ", without_entities).strip()


def project_info_excerpt(content: str, *, question: str) -> str:
  if len(content) <= PROJECT_INFO_MAX_CHARS_PER_FILE:
    return content
  terms = [
    value
    for value in re.findall(r"[a-z][a-z0-9_-]{2,}", question.lower())
    if value not in {"what", "which", "this", "that", "website", "project", "current"}
  ]
  markers = [*terms, "<title", '"name"', "brand", "logo", "copyright"]
  lowered = content.lower()
  positions = [lowered.find(marker) for marker in markers if lowered.find(marker) >= 0]
  if not positions:
    return content[:PROJECT_INFO_MAX_CHARS_PER_FILE]
  anchor = min(positions)
  start = max(0, anchor - 600)
  end = min(len(content), start + PROJECT_INFO_MAX_CHARS_PER_FILE)
  return content[start:end]
