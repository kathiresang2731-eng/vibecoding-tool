from __future__ import annotations

import hashlib
import html
import re
from typing import Any

from .values import text_or_default


SUPPORTED_COLOR_NAMES = {
  "red",
  "yellow",
  "orange",
  "amber",
  "blue",
  "purple",
  "green",
  "teal",
  "black",
  "white",
}


def clean_targeted_text_value(value: str) -> str:
  cleaned = value.strip().strip("\"'`“”‘’")
  cleaned = re.split(r"\s+(?:and|but|only|while|with)\s+", cleaned, maxsplit=1, flags=re.IGNORECASE)[0].strip()
  cleaned = re.sub(r"[.?!,;:]+$", "", cleaned).strip()
  return cleaned[:80]


def targeted_text_request(kind: str, new_value: str, *, old_value: str = "") -> dict[str, Any]:
  return {
    "kind": kind,
    "old_value": old_value,
    "new_value": new_value,
    "palette_label": new_value,
  }


def targeted_update_label(request: dict[str, Any]) -> str:
  kind = text_or_default(request.get("kind"), "targeted_update")
  if kind == "theme_color_update":
    return f"{request['palette_label']} theme"
  if kind == "brand_name_update":
    return f"brand name '{request.get('new_value')}'"
  if kind == "document_title_update":
    return f"document title '{request.get('new_value')}'"
  if kind == "cta_text_update":
    return f"CTA text '{request.get('new_value')}'"
  if kind == "pagination_page_size_update":
    return f"pagination page size {request.get('page_size')} items"
  return "targeted update"


def targeted_update_goal(request: dict[str, Any]) -> str:
  kind = text_or_default(request.get("kind"), "targeted_update")
  if kind == "theme_color_update":
    return f"Applied the requested {request['palette_label']} theme."
  if request.get("old_value"):
    return f"Updated '{request.get('old_value')}' to '{request.get('new_value')}'."
  if kind == "brand_name_update":
    return f"Updated high-confidence brand/name locations to '{request.get('new_value')}'."
  if kind == "document_title_update":
    return f"Updated document title metadata to '{request.get('new_value')}'."
  if kind == "cta_text_update":
    return f"Updated the primary CTA text to '{request.get('new_value')}'."
  if kind == "pagination_page_size_update":
    return f"Updated pagination to show {request.get('page_size')} items per page."
  return "Applied the requested targeted update."


def build_project_file_keyword_index(files: list[dict[str, str]]) -> list[dict[str, Any]]:
  index: list[dict[str, Any]] = []
  for file_item in files:
    path = file_item["path"]
    content = file_item["content"]
    lowered_path = path.lower()
    lowered_content = content.lower()
    keywords = set(re.findall(r"[a-z][a-z0-9_]{2,}", lowered_path.replace("/", " ")))
    for marker in ("theme", "color", "background", "tailwind", "classname", "cart", "checkout", "product", "auth", "login", "register", "token", "module"):
      if marker in lowered_content:
        keywords.add(marker)
    role = "style" if path.endswith(".css") or "tailwind.config" in path else "component" if path.endswith((".jsx", ".tsx")) else "data" if "/data/" in path else "config" if path.endswith((".json", ".js", ".mjs", ".ts")) else "asset"
    imports = extract_file_imports(content)
    exports = extract_file_exports(content)
    routes = extract_file_routes(content)
    symbols = extract_file_symbols(content)
    components = extract_file_components(path, content, symbols)
    css_references = extract_css_references(content)
    index.append(
      {
        "path": path,
        "role": role,
        "keywords": sorted(keywords)[:20],
        "char_count": len(content),
        "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "imports": imports,
        "exports": exports,
        "routes": routes,
        "components": components,
        "symbols": symbols,
        "css_references": css_references,
        "last_changed_run_id": str(file_item.get("last_changed_run_id") or ""),
      }
    )
  return index


def extract_file_imports(content: str) -> list[str]:
  imports: list[str] = []
  patterns = (
    r"\bimport\s+(?:[^;\n]*?\s+from\s+)?[\"']([^\"']+)[\"']",
    r"\brequire\(\s*[\"']([^\"']+)[\"']\s*\)",
    r"^\s*from\s+([A-Za-z_][\w.]*)\s+import\b",
    r"^\s*import\s+([A-Za-z_][\w.]*)",
  )
  for pattern in patterns:
    imports.extend(re.findall(pattern, content, re.MULTILINE))
  return sorted(set(imports))[:40]


def extract_file_exports(content: str) -> list[str]:
  exports: set[str] = set()
  for match in re.finditer(
    r"\bexport\s+(?:default\s+)?(?:async\s+)?(?:function|class|const|let|var)\s+([A-Za-z_$][\w$]*)",
    content,
  ):
    exports.add(match.group(1))
  for match in re.finditer(r"\bexport\s*\{([^}]+)\}", content, re.DOTALL):
    for item in match.group(1).split(","):
      name = item.strip().split(" as ", 1)[-1].strip()
      if re.fullmatch(r"[A-Za-z_$][\w$]*", name):
        exports.add(name)
  if re.search(r"\bexport\s+default\b", content):
    exports.add("default")
  return sorted(exports)[:40]


def extract_file_routes(content: str) -> list[str]:
  routes: set[str] = set()
  patterns = (
    r"\bpath\s*=\s*[\"']([^\"']+)[\"']",
    r"\bpath\s*:\s*[\"']([^\"']+)[\"']",
    r"\b(?:router|app)\.(?:get|post|put|patch|delete|use)\(\s*[\"']([^\"']+)[\"']",
  )
  for pattern in patterns:
    routes.update(re.findall(pattern, content))
  return sorted(routes)[:40]


def extract_file_symbols(content: str) -> list[str]:
  symbols: set[str] = set()
  patterns = (
    r"\b(?:async\s+)?function\s+([A-Za-z_$][\w$]*)",
    r"\bclass\s+([A-Za-z_$][\w$]*)",
    r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=",
    r"^\s*def\s+([A-Za-z_][\w]*)\s*\(",
  )
  for pattern in patterns:
    symbols.update(re.findall(pattern, content, re.MULTILINE))
  return sorted(symbols)[:80]


def extract_file_components(path: str, content: str, symbols: list[str]) -> list[str]:
  if not path.endswith((".jsx", ".tsx", ".js", ".ts")):
    return []
  components = {
    symbol
    for symbol in symbols
    if symbol[:1].isupper()
    and (
      re.search(rf"<{re.escape(symbol)}(?:\s|/|>)", content)
      or re.search(rf"\b{re.escape(symbol)}\s*=\s*(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>", content)
      or re.search(rf"\bfunction\s+{re.escape(symbol)}\s*\(", content)
    )
  }
  return sorted(components)[:40]


def extract_css_references(content: str) -> list[str]:
  references: set[str] = set()
  for match in re.finditer(r"\bclassName\s*=\s*[\"']([^\"']+)[\"']", content):
    references.update(item for item in match.group(1).split() if item)
  for match in re.finditer(r"\bclass\s*=\s*[\"']([^\"']+)[\"']", content):
    references.update(item for item in match.group(1).split() if item)
  references.update(re.findall(r"@import\s+[\"']([^\"']+)[\"']", content))
  return sorted(references)[:80]


def apply_targeted_file_update(files: list[dict[str, str]], request: dict[str, Any]) -> list[dict[str, str]]:
  kind = text_or_default(request.get("kind"), "")
  if kind in {"brand_name_update", "document_title_update"}:
    return apply_brand_or_title_update(files, request)
  if kind == "cta_text_update":
    return apply_cta_text_update(files, request)
  if kind == "pagination_page_size_update":
    return apply_pagination_page_size_update(files, request)
  return []


def apply_brand_or_title_update(files: list[dict[str, str]], request: dict[str, Any]) -> list[dict[str, str]]:
  changed: list[dict[str, str]] = []
  old_value = text_or_default(request.get("old_value"), "")
  new_value = text_or_default(request.get("new_value"), "")
  kind = text_or_default(request.get("kind"), "brand_name_update")
  if not new_value:
    return []
  inferred_brand_candidates = infer_existing_brand_candidates(files) if kind == "brand_name_update" and not old_value else []

  for file_item in files:
    path = file_item["path"]
    content = file_item["content"]
    if not is_brand_update_safe_path(path):
      continue
    updated = content
    if old_value:
      updated = replace_exact_text(updated, old_value, new_value)
    elif kind == "document_title_update":
      updated = replace_document_title_metadata(path, updated, new_value)
    else:
      updated = replace_document_title_metadata(path, updated, new_value)
      for candidate in inferred_brand_candidates:
        updated = replace_brand_candidate_text(updated, candidate, new_value)
      updated = replace_named_brand_constants(updated, new_value)
      updated = replace_brand_accessibility_attributes(updated, new_value)
      updated = replace_brand_like_jsx_text(updated, new_value)
    if updated != content:
      changed.append({"path": path, "content": updated})
  return changed


def is_brand_update_safe_path(path: str) -> bool:
  if not path.endswith((".html", ".js", ".jsx", ".ts", ".tsx", ".json")):
    return False
  lowered = path.lower()
  blocked_fragments = ("/data/products", "/products.", "/catalog.", "/inventory.", "package-lock.json")
  return not any(fragment in lowered for fragment in blocked_fragments)


def replace_exact_text(content: str, old_value: str, new_value: str) -> str:
  return content.replace(old_value, new_value)


def replace_brand_candidate_text(content: str, old_value: str, new_value: str) -> str:
  updated = replace_exact_text(content, old_value, new_value)
  escaped_old = html.escape(old_value, quote=False)
  escaped_new = html.escape(new_value, quote=False)
  if escaped_old != old_value:
    updated = replace_exact_text(updated, escaped_old, escaped_new)
  unescaped_old = html.unescape(old_value)
  if unescaped_old != old_value:
    updated = replace_exact_text(updated, unescaped_old, new_value)
  return updated


def infer_existing_brand_candidates(files: list[dict[str, str]]) -> list[str]:
  candidates: list[str] = []
  for file_item in files:
    path = file_item["path"]
    content = file_item["content"]
    if not is_brand_update_safe_path(path):
      continue
    candidates.extend(infer_brand_candidates_from_content(path, content))
  unique_candidates: list[str] = []
  seen: set[str] = set()
  for candidate in sorted(candidates, key=len, reverse=True):
    cleaned = normalize_brand_candidate(candidate)
    if not cleaned:
      continue
    key = cleaned
    if key in seen:
      continue
    seen.add(key)
    unique_candidates.append(cleaned)
  return unique_candidates[:8]


def infer_brand_candidates_from_content(path: str, content: str) -> list[str]:
  candidates: list[str] = []
  if path == "index.html":
    for match in re.finditer(r"<title>\s*(.*?)\s*</title>", content, re.IGNORECASE | re.DOTALL):
      candidates.append(match.group(1))
    for match in re.finditer(r"<meta\b[^>]*(?:application-name|og:site_name)[^>]*\bcontent\s*=\s*([\"'])(.*?)\1", content, re.IGNORECASE | re.DOTALL):
      candidates.append(match.group(2))

  string_patterns = (
    r"\b(?:const|let|var)\s+(?:siteName|brandName|companyName|appName|SITE_NAME|BRAND_NAME|COMPANY_NAME|APP_NAME)\s*=\s*([\"'])(.*?)\1",
    r"\b(?:siteName|brandName|companyName|appName|SITE_NAME|BRAND_NAME|COMPANY_NAME|APP_NAME|brand|company)\s*:\s*([\"'])(.*?)\1",
  )
  for pattern in string_patterns:
    for match in re.finditer(pattern, content, re.DOTALL):
      candidates.append(match.group(2))

  jsx_pattern = re.compile(
    r"<(?P<tag>[A-Za-z][\w.]*)\b(?P<attrs>[^>]*)>\s*(?P<text>[^<>{}\n]{2,80})\s*</(?P=tag)>",
    re.IGNORECASE,
  )
  for match in jsx_pattern.finditer(content):
    text = match.group("text")
    attrs = match.group("attrs")
    prefix = content[max(0, match.start() - 700):match.start()].lower()
    if is_likely_brand_jsx_text(text, attrs, prefix):
      candidates.append(text)

  for match in re.finditer(r"([A-Za-z][A-Za-z0-9]*(?:\s*&(?:amp;)?\s*[A-Za-z][A-Za-z0-9]*){1,2})", content):
    prefix = content[max(0, match.start() - 250):match.start()].lower()
    if "brand" in prefix or "logo" in prefix or prefix.rfind("<header") > prefix.rfind("</header"):
      candidates.append(match.group(1))
  return candidates


def normalize_brand_candidate(value: str) -> str:
  cleaned = html.unescape(value).strip().strip("\"'`“”‘’")
  cleaned = re.sub(r"\s+", " ", cleaned)
  cleaned = re.sub(r"\s+(?:website|site)$", "", cleaned, flags=re.IGNORECASE).strip()
  if not cleaned or len(cleaned) < 2 or len(cleaned) > 60:
    return ""
  if re.search(r"[.!?]\s", cleaned):
    return ""
  generic = {
    "home",
    "shop",
    "about",
    "support",
    "contact",
    "catalog",
    "checkout",
    "all collections",
    "search",
    "view cart",
    "shop collection",
    "e-commerce",
    "e-commerce website",
    "generated website",
  }
  if cleaned.lower() in generic:
    return ""
  return cleaned


def is_likely_brand_jsx_text(text: str, attrs: str, prefix: str) -> bool:
  cleaned = normalize_brand_candidate(text)
  if not cleaned:
    return False
  lowered_attrs = attrs.lower()
  if re.search(r"\b(?:brand|logo|site-name|company-name|navbar-brand)\b", lowered_attrs):
    return True
  in_header = prefix.rfind("<header") > prefix.rfind("</header")
  if in_header and ("&" in cleaned or re.search(r"\b(?:font-bold|font-black|tracking|text-xl|text-2xl|text-3xl)\b", lowered_attrs)):
    return True
  return False


def replace_document_title_metadata(path: str, content: str, new_value: str) -> str:
  if path != "index.html":
    return content
  title_value = html.escape(new_value, quote=False)
  attribute_value = html.escape(new_value, quote=True)
  updated = re.sub(
    r"(<title>\s*)(.*?)(\s*</title>)",
    lambda match: f"{match.group(1)}{title_value}{match.group(3)}",
    content,
    count=1,
    flags=re.IGNORECASE | re.DOTALL,
  )

  def meta_replacer(match: re.Match[str]) -> str:
    tag = match.group(0)
    lowered = tag.lower()
    metadata_keys = ("application-name", "og:site_name", "twitter:title", "og:title")
    if not any(key in lowered for key in metadata_keys):
      return tag
    return re.sub(
      r"(content\s*=\s*)([\"'])(.*?)(\2)",
      lambda content_match: f"{content_match.group(1)}{content_match.group(2)}{attribute_value}{content_match.group(4)}",
      tag,
      count=1,
      flags=re.IGNORECASE | re.DOTALL,
    )

  updated = re.sub(r"<meta\b[^>]*>", meta_replacer, updated, flags=re.IGNORECASE | re.DOTALL)
  return updated


def replace_named_brand_constants(content: str, new_value: str) -> str:
  identifier = r"(?:siteName|brandName|companyName|appName|siteTitle|brandTitle|SITE_NAME|BRAND_NAME|COMPANY_NAME|APP_NAME|SITE_TITLE|BRAND_TITLE|brand|company)"
  assignment_pattern = re.compile(
    rf"(\b(?:const|let|var)\s+{identifier}\s*=\s*)([\"'])(.*?)(\2)",
    re.DOTALL,
  )
  property_pattern = re.compile(
    rf"(\b{identifier}\s*:\s*)([\"'])(.*?)(\2)",
    re.DOTALL,
  )

  def replacer(match: re.Match[str]) -> str:
    return f"{match.group(1)}{match.group(2)}{new_value}{match.group(4)}"

  updated = assignment_pattern.sub(replacer, content)
  updated = property_pattern.sub(replacer, updated)
  return updated


def replace_brand_accessibility_attributes(content: str, new_value: str) -> str:
  pattern = re.compile(
    r"((?:aria-label|alt|title)\s*=\s*)([\"'])([^\"']*(?:brand|logo|home|site)[^\"']*)(\2)",
    re.IGNORECASE,
  )

  def replacer(match: re.Match[str]) -> str:
    previous = match.group(3).lower()
    label = f"{new_value} logo" if "logo" in previous else f"{new_value} home" if "home" in previous else new_value
    return f"{match.group(1)}{match.group(2)}{label}{match.group(4)}"

  return pattern.sub(replacer, content)


def replace_brand_like_jsx_text(content: str, new_value: str) -> str:
  pattern = re.compile(
    r"(<(?P<tag>[A-Za-z][\w.]*)\b(?=[^>]*(?:brand|logo|site-name|company-name|navbar-brand))[^>]*>\s*)(?P<text>[^<>{}\n]{2,80})(\s*</(?P=tag)>)",
    re.IGNORECASE,
  )
  return pattern.sub(lambda match: f"{match.group(1)}{new_value}{match.group(4)}", content)


def apply_cta_text_update(files: list[dict[str, str]], request: dict[str, Any]) -> list[dict[str, str]]:
  new_value = text_or_default(request.get("new_value"), "")
  if not new_value:
    return []
  changed: list[dict[str, str]] = []
  for file_item in files:
    path = file_item["path"]
    content = file_item["content"]
    if not path.endswith((".jsx", ".tsx")):
      continue
    updated = replace_first_cta_text(content, new_value)
    if updated != content:
      changed.append({"path": path, "content": updated})
      break
  return changed


def replace_first_cta_text(content: str, new_value: str) -> str:
  cta_pattern = re.compile(
    r"(<(?:button|a)\b(?=[^>]*(?:cta|primary|button|btn))[^>]*>\s*)([^<>{}\n]{2,80})(\s*</(?:button|a)>)",
    re.IGNORECASE,
  )
  return cta_pattern.sub(lambda match: f"{match.group(1)}{new_value}{match.group(3)}", content, count=1)


def apply_pagination_page_size_update(files: list[dict[str, str]], request: dict[str, Any]) -> list[dict[str, str]]:
  try:
    page_size = int(request.get("page_size"))
  except (TypeError, ValueError):
    return []
  if page_size < 1 or page_size > 200:
    return []

  changed: list[dict[str, str]] = []
  for file_item in files:
    path = file_item["path"]
    content = file_item["content"]
    if not path.endswith((".js", ".jsx", ".ts", ".tsx")):
      continue
    updated = replace_pagination_page_size_constants(content, page_size)
    if updated != content:
      changed.append({"path": path, "content": updated})
  return changed


def replace_pagination_page_size_constants(content: str, page_size: int) -> str:
  identifiers = (
    "ITEMS_PER_PAGE",
    "PRODUCTS_PER_PAGE",
    "PRODUCTS_PER_PAGE_COUNT",
    "PAGE_SIZE",
    "pageSize",
    "itemsPerPage",
    "productsPerPage",
    "catalogPageSize",
    "paginationPageSize",
  )
  identifier_pattern = "|".join(re.escape(identifier) for identifier in identifiers)
  assignment_pattern = re.compile(
    rf"(\b(?:const|let|var)\s+(?:{identifier_pattern})\s*=\s*)(\d+)\b"
  )
  property_pattern = re.compile(
    rf"(\b(?:{identifier_pattern})\s*:\s*)(\d+)\b"
  )
  state_pattern = re.compile(
    rf"(\b(?:const|let)\s*\[[^\]]*(?:{identifier_pattern})[^\]]*\]\s*=\s*useState\(\s*)(\d+)(\s*\))",
    re.IGNORECASE,
  )
  updated = assignment_pattern.sub(lambda match: f"{match.group(1)}{page_size}", content)
  updated = property_pattern.sub(lambda match: f"{match.group(1)}{page_size}", updated)
  updated = state_pattern.sub(lambda match: f"{match.group(1)}{page_size}{match.group(3)}", updated)
  return updated


def infer_project_title_from_files(files: list[dict[str, str]]) -> str:
  for file_item in files:
    if file_item["path"] == "index.html":
      match = re.search(r"<title>(.*?)</title>", file_item["content"], re.IGNORECASE | re.DOTALL)
      if match and match.group(1).strip():
        return match.group(1).strip()
  for file_item in files:
    if file_item["path"].endswith((".jsx", ".tsx", ".js")):
      match = re.search(r"\b(?:const|let|var)\s+(?:brand|siteTitle|title)\s*=\s*['\"]([^'\"]+)['\"]", file_item["content"])
      if match:
        return match.group(1).strip()
  return ""


def targeted_update_workflow_plan(request: dict[str, Any], changed_paths: list[str]) -> dict[str, Any]:
  label = targeted_update_label(request)
  return {
    "domain": "targeted_update",
    "scope": "small",
    "tasks": [{"id": "targeted_simple_update", "name": "Targeted simple update", "required_capability": "targeted_code_update", "runtime_action": "APPLY_TARGETED_UPDATE_SHORTCUT", "dependencies": [], "risk_level": "low", "optional": False}],
    "assignments": [{"task_id": "targeted_simple_update", "agent_id": "targeted-update-agent", "agent_name": "Targeted Update Agent", "capability": "targeted_code_update", "assignment_type": "model_selected_executor", "confidence": 0.96, "reason": f"Model selected a simple {label}; Python can apply it without full regeneration."}],
    "dependency_graph": {"targeted_simple_update": []},
    "parallel_groups": [["targeted_simple_update"]],
    "completion_proof": ["artifact_valid", "staged_preview_ready", "visual_qa_passed", "files_committed", "memory_prepared"],
    "active_agents": [{"id": "targeted-update-agent", "name": "Targeted Update Agent", "role": "Patch existing project files for low-risk simple updates.", "capabilities": ["targeted_code_update"], "lifecycle": "core", "assigned_tasks": ["targeted_simple_update"]}],
    "created_agent_ids": [],
    "reused_agent_ids": ["targeted-update-agent"],
    "planning_source": "model_selected_targeted_patch",
    "planner_reason": f"Patched only {', '.join(changed_paths)} for a low-risk model-selected {label}.",
  }


def targeted_update_review(trace_label: str) -> dict[str, Any]:
  return {
    "status": "reviewed",
    "issues": [],
    "recommendations": ["Preserve existing layout, components, and interactions; validate preview before commit."],
    "control_fallback": {
      "source": f"model_selected_targeted_{trace_label}",
      "reason": "Simple targeted update skipped broad review agents to preserve scope and reduce token use.",
    },
  }
