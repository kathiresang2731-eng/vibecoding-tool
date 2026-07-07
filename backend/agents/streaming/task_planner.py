from __future__ import annotations

import re
from typing import Any

from .update_validation import brand_title_target_paths, is_brand_rename_prompt

try:
  from ..chat_history import primary_update_prompt
except ImportError:
  from agents.chat_history import primary_update_prompt

try:
  from ..project_workspace import is_scaffold_only_codebase
except ImportError:
  from agents.project_workspace import is_scaffold_only_codebase


def _is_scaffold_only_generation(project_files: list[dict[str, Any]]) -> bool:
  return is_scaffold_only_codebase(project_files)


SECTION_KEYWORDS = (
  "hero",
  "header",
  "footer",
  "navbar",
  "nav bar",
  "sidebar",
  "about",
  "contact",
  "pricing",
  "testimonial",
  "cta",
  "gallery",
)

IMPORT_RE = re.compile(
  r"(?:from|import)\s+['\"](\.?\.?/[^'\"]+)['\"]",
  re.MULTILINE,
)

try:
  from ..project_workspace import is_meaningful_project_source_path, meaningful_project_source_files
except ImportError:
  from agents.project_workspace import is_meaningful_project_source_path, meaningful_project_source_files

FOLDER_PREFIXES = ("src/pages/", "src/components/", "src/layouts/", "src/features/")
ENV_EXAMPLE_PATH = ".env.example"
SECRET_ENV_BASENAMES = frozenset(
  {
    ".env",
    ".env.local",
    ".env.development",
    ".env.production",
    ".env.test",
  }
)

# Legacy offline fallback hints. Runtime planning must prefer
# `_llm_plan_file_work()` whenever an artifact provider is available; do not
# add new active routing behavior here.
DATA_UPDATE_SIGNALS = frozenset(
  {
    "data",
    "dataset",
    "entry",
    "entries",
    "lead",
    "leads",
    "mock",
    "mockdata",
    "negotiation",
    "record",
    "records",
    "row",
    "rows",
    "status",
  }
)

CONTENT_MATCH_STOPWORDS = {
  "about",
  "after",
  "also",
  "button",
  "change",
  "code",
  "file",
  "from",
  "have",
  "just",
  "like",
  "make",
  "modal",
  "need",
  "page",
  "please",
  "popup",
  "provide",
  "that",
  "the",
  "this",
  "update",
  "user",
  "want",
  "with",
  "your",
}


def _prompt_tokens(prompt: str) -> set[str]:
  return set(re.findall(r"[a-z0-9]+", prompt.lower()))


def is_explicit_greenfield_website_request(prompt: str) -> bool:
  lowered = str(prompt or "").strip().lower()
  if not lowered:
    return False
  wants_build = any(marker in lowered for marker in ("build ", "create ", "generate ", "regenerate", "rebuild", "make "))
  if not wants_build:
    return False
  tokens = _prompt_tokens(lowered)
  website_tokens = {
    "website",
    "web",
    "app",
    "webapp",
    "frontend",
    "dashboard",
    "landing",
    "site",
    "page",
    "pages",
  }
  return bool(tokens & website_tokens or "web app" in lowered or "web site" in lowered)


def _structured_prompt_items(prompt: str) -> int:
  return len(re.findall(r"(?:^|\s)(?:[-*]|->|\d+[.)])\s+", str(prompt or ""), flags=re.MULTILINE))


def _extract_prompt_page_labels(prompt: str, *, max_labels: int = 12) -> list[str]:
  """Derive page/module labels from prompt structure — no preset domain layouts."""
  labels: list[str] = []
  seen: set[str] = set()
  stopwords = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "with",
    "for",
    "to",
    "of",
    "in",
    "on",
    "after",
    "before",
    "once",
    "done",
    "provide",
    "include",
    "add",
    "create",
    "build",
    "generate",
    "module",
    "modules",
    "page",
    "pages",
    "section",
    "sections",
    "feature",
    "features",
    "requirement",
    "requirements",
    "website",
    "app",
    "type",
    "types",
    "report",
    "reports",
    "analytics",
    "main",
    "new",
    "all",
  }

  def add_label(raw: str) -> None:
    normalized = re.sub(
      r"^(?:modules?|pages?|sections?|features?|screens?|views?)\s*[:：]\s*",
      "",
      str(raw or "").strip(),
      flags=re.IGNORECASE,
    )
    if not normalized:
      return
    parts = re.split(r"\s*(?:,|/|&| and )\s*", normalized)
    for part in parts:
      cleaned = re.sub(r"[^a-z0-9 &/-]+", " ", part.lower()).strip()
      if not cleaned:
        continue
      words = [word for word in cleaned.split() if word and word not in stopwords]
      if not words:
        continue
      label = " ".join(words[:4]).strip()
      if len(label) < 2 or label in seen:
        continue
      seen.add(label)
      labels.append(label)
      if len(labels) >= max_labels:
        return

  for match in re.finditer(r"(?:^|\n)\s*(?:\d+[.)]|[-*]|->)\s*(.+)$", str(prompt or ""), flags=re.MULTILINE):
    add_label(match.group(1))
    if len(labels) >= max_labels:
      break

  for match in re.finditer(
    r"\b(?:modules?|pages?|sections?|features?|screens?|views?)\s*[:：]\s*([^\n]+)",
    str(prompt or ""),
    flags=re.IGNORECASE,
  ):
    add_label(match.group(1))
    if len(labels) >= max_labels:
      break

  for match in re.finditer(
    r"\b(?:add|create|build|generate)\s+(?:a\s+)?([a-z][a-z0-9 &/-]{2,48})\s+(?:page|screen|view|module)\b",
    str(prompt or ""),
    flags=re.IGNORECASE,
  ):
    add_label(match.group(1))
    if len(labels) >= max_labels:
      break

  return labels[:max_labels]


def is_rich_greenfield_website_request(prompt: str) -> bool:
  lowered = str(prompt or "").strip().lower()
  if not is_explicit_greenfield_website_request(lowered):
    return False
  structured_items = _structured_prompt_items(lowered)
  page_labels = _extract_prompt_page_labels(prompt)
  word_count = len(re.findall(r"\w+", lowered))
  enterprise_signals = {
    "enterprise",
    "crm",
    "saas",
    "platform",
    "workspace",
    "dashboard",
    "modules",
    "module",
    "copilot",
    "analytics",
    "pipeline",
    "onboarding",
    "authentication",
  }
  if tokens := _prompt_tokens(lowered):
    if len(tokens & enterprise_signals) >= 2:
      return True
  return structured_items >= 5 or len(page_labels) >= 6 or word_count > 200


def is_moderate_greenfield_website_request(prompt: str) -> bool:
  lowered = str(prompt or "").strip().lower()
  if not is_explicit_greenfield_website_request(lowered):
    return False
  if is_rich_greenfield_website_request(prompt):
    return True
  structured_items = _structured_prompt_items(lowered)
  page_labels = _extract_prompt_page_labels(prompt)
  word_count = len(re.findall(r"\w+", lowered))
  return structured_items >= 3 or len(page_labels) >= 3 or word_count > 120 or "requirement" in lowered


def is_requirement_rebuild_request(prompt: str) -> bool:
  lowered = str(prompt or "").strip().lower()
  if not lowered:
    return False
  rebuild_signals = (
    "single static page",
    "static page",
    "missing module",
    "missing modules",
    "not based on requirement",
    "not based on my requirement",
    "failed to generate",
    "generate based on",
    "rebuild",
    "regenerate",
    "complete website",
    "complete crm",
  )
  return any(signal in lowered for signal in rebuild_signals) and (
    is_explicit_greenfield_website_request(lowered)
    or "crm" in lowered
    or "website" in lowered
    or "dashboard" in lowered
  )


def _has_frontend_application_files(paths: list[str]) -> bool:
  return any(
    path in GREENFIELD_SCAFFOLD_PATHS
    or path.startswith(("src/pages/", "src/components/", "src/layouts/", "src/features/"))
    for path in paths
  )


def _mentioned_paths(prompt: str, paths: list[str]) -> list[str]:
  prompt_lower = prompt.lower()
  env_mentions = {name for name in SECRET_ENV_BASENAMES if name in prompt_lower}
  if env_mentions:
    for candidate in (ENV_EXAMPLE_PATH, "env.example", "example.env"):
      if candidate in paths:
        return [candidate]
    return []
  mentioned: list[str] = []
  for path in paths:
    if "worktual-" in path.lower() and "shim" in path.lower():
      continue
    base = path.rsplit("/", 1)[-1]
    name_no_ext = base.rsplit(".", 1)[0] if "." in base else base
    if path.lower() in prompt_lower or base.lower() in prompt_lower:
      mentioned.append(path)
      continue
    if len(name_no_ext) >= 3 and name_no_ext.lower() in prompt_lower:
      mentioned.append(path)
  return list(dict.fromkeys(mentioned))


def _prompt_mentions_file_like_token(prompt: str) -> bool:
  lowered = prompt.lower()
  if any(name in lowered for name in (*SECRET_ENV_BASENAMES, ENV_EXAMPLE_PATH, "env.example")):
    return True
  return bool(
    re.search(
      r"\b(?:src/)?[a-z0-9_.-]+(?:/[a-z0-9_.-]+)*\.(?:js|jsx|ts|tsx|css|html|json|py|java|go|php|rb|sql)\b",
      lowered,
    )
  )


def _content_match_paths(prompt: str, files_map: dict[str, str], *, max_results: int = 2) -> list[str]:
  tokens = [
    token
    for token in _prompt_tokens(prompt)
    if len(token) >= 4 and token not in CONTENT_MATCH_STOPWORDS
  ]
  if len(tokens) < 2:
    return []
  scored: list[tuple[int, str]] = []
  for path, content in files_map.items():
    if _is_noise_path(path):
      continue
    if not path.startswith(("src/pages/", "src/components/", "src/layouts/", "src/features/")):
      continue
    lowered = content.lower()
    score = sum(1 for token in tokens if token in lowered)
    if score >= 2:
      scored.append((score, path))
  scored.sort(key=lambda item: (-item[0], item[1]))
  return [path for _, path in scored[:max_results]]


def _related_import_paths(primary_paths: list[str], files_map: dict[str, str], *, max_extra: int = 1) -> list[str]:
  known_paths = set(files_map)
  extras: list[str] = []
  for path in primary_paths:
    content = files_map.get(path, "")
    for imported in _import_dependencies(path, content, known_paths):
      if imported not in primary_paths and imported not in extras:
        extras.append(imported)
    if len(extras) >= max_extra:
      break
  return extras[:max_extra]


def _resolve_import(source_path: str, import_path: str) -> str | None:
  source_dir = source_path.rsplit("/", 1)[0] if "/" in source_path else ""
  normalized = import_path.strip()
  if normalized.startswith("./"):
    normalized = normalized[2:]
  elif normalized.startswith("../"):
    parts = source_dir.split("/") if source_dir else []
    remainder = normalized
    while remainder.startswith("../"):
      remainder = remainder[3:]
      if parts:
        parts.pop()
    candidate = "/".join([*parts, remainder]) if parts or remainder else remainder
    return candidate.replace("//", "/")
  candidate = f"{source_dir}/{normalized}" if source_dir else normalized
  return candidate.replace("//", "/")


def _import_dependencies(path: str, content: str, known_paths: set[str]) -> set[str]:
  deps: set[str] = set()
  for match in IMPORT_RE.findall(content):
    resolved = _resolve_import(path, match)
    if not resolved:
      continue
    for candidate in {resolved, f"src/{resolved}", resolved.replace("src/", "")}:
      if candidate in known_paths:
        deps.add(candidate)
        break
  return deps


def _detect_sections(prompt: str, path: str) -> list[str]:
  lowered = prompt.lower()
  base = path.rsplit("/", 1)[-1].lower()
  if base not in lowered and path.lower() not in lowered:
    return []
  sections = [word for word in SECTION_KEYWORDS if word in lowered]
  return sections[:4]


NOISE_BASENAMES = frozenset(
  {
    "postcss.config.js",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
  }
)

MODULE_KEYWORDS: dict[str, tuple[str, ...]] = {
  "lead": ("lead", "leads"),
  "contact": ("contact", "contacts"),
  "deal": ("deal", "deals"),
  "dashboard": ("dashboard",),
  "auth": ("auth", "login", "onboarding"),
  "finance": ("finance",),
  "copilot": ("copilot",),
}

MODULE_FEATURE_KEYWORDS = (
  "nav",
  "navbar",
  "secondary",
  "sidebar",
  "history",
  "call",
  "email",
  "sms",
  "module",
  "sub module",
  "submodule",
)


def _is_noise_path(path: str) -> bool:
  base = path.rsplit("/", 1)[-1].lower()
  return base in NOISE_BASENAMES or base.startswith(".")


def _score_module_path(path: str, lowered: str, files_map: dict[str, str]) -> int:
  if _is_noise_path(path):
    return 0
  base = path.rsplit("/", 1)[-1].lower()
  name = base.rsplit(".", 1)[0]
  score = 0
  for _, tokens in MODULE_KEYWORDS.items():
    if any(token in lowered for token in tokens) and any(token in name or token in base for token in tokens):
      score += 6
  if path.startswith("src/data/") and any(
    token in lowered for token in ("history", "mock", "call", "email", "sms", "lead", "contact", "data")
  ):
    score += 5
  if path == "src/App.jsx" and any(token in lowered for token in ("nav", "route", "module", "sidebar")):
    score += 4
  if path.startswith("src/components/") and any(token in lowered for token in ("nav", "sidebar", "module")):
    score += 3
  content = files_map.get(path, "").lower()
  for keyword in MODULE_FEATURE_KEYWORDS:
    if keyword in lowered and keyword in content:
      score += 2
  return score


def _module_parallel_tasks(
  prompt: str,
  paths: list[str],
  files_map: dict[str, str],
  *,
  max_tasks: int = 5,
) -> list[dict[str, Any]]:
  lowered = prompt.lower()
  has_module_intent = any(
    token in lowered for token in (*MODULE_FEATURE_KEYWORDS, "module", "leads", "lead", "contact", "contacts", " & ")
  )
  if not has_module_intent:
    return []
  scored = [( _score_module_path(path, lowered, files_map), path) for path in paths]
  scored = [(score, path) for score, path in scored if score > 0]
  if len(scored) < 2:
    return []
  scored.sort(key=lambda item: (-item[0], item[1]))
  return [_task_for_path(path, scope="module parallel agent") for _, path in scored[:max_tasks]]


def _data_layer_tasks(prompt: str, paths: list[str]) -> list[dict[str, Any]]:
  tokens = _prompt_tokens(prompt)
  if len(tokens & DATA_UPDATE_SIGNALS) < 2:
    return []
  tasks: list[dict[str, Any]] = []
  data_paths = [
    path
    for path in paths
    if path.startswith("src/data/") or "mock" in path.lower() or path.endswith("mockData.js")
  ]
  for path in data_paths[:1]:
    tasks.append(_task_for_path(path, scope="data update"))
  for path in paths:
    base = path.rsplit("/", 1)[-1].lower()
    if path.startswith("src/pages/") and "lead" in base and "lead" in prompt.lower():
      if path not in {task["paths"][0] for task in tasks}:
        tasks.append(_task_for_path(path, scope="data display"))
  for path in paths:
    base = path.rsplit("/", 1)[-1].lower()
    if path.startswith("src/pages/") and "contact" in base and "contact" in prompt.lower():
      if path not in {task["paths"][0] for task in tasks}:
        tasks.append(_task_for_path(path, scope="data display"))
  return tasks[:4]


def _page_hint_paths(prompt: str, paths: list[str], files_map: dict[str, str] | None = None) -> list[str]:
  lowered = prompt.lower()
  scored: list[tuple[int, str]] = []
  for path in paths:
    if not path.startswith(("src/pages/", "src/data/")):
      continue
    base = path.rsplit("/", 1)[-1].lower()
    name = base.rsplit(".", 1)[0]
    score = 0
    if "page" in lowered and (name in lowered or f"{name}s" in lowered):
      score += 4
    if "negotiation" in lowered and any(token in name for token in ("lead", "deal", "negotiation")):
      score += 4
    if "dashboard" in lowered and "dashboard" in name:
      score += 4
    content = (files_map or {}).get(path, "").lower()
    if "negotiation" in lowered and "negotiation" in content:
      score += 2
    if score:
      scored.append((score, path))
  scored.sort(key=lambda item: (-item[0], item[1]))
  return [path for _, path in scored[:2]]


ONBOARDING_FLOW_SIGNALS = frozenset({"onboarding", "skip", "modal", "wizard", "welcome", "setup", "walkthrough"})


def is_auth_onboarding_flow_repair_prompt(prompt: str) -> bool:
  lowered = str(prompt or "").strip().lower()
  if not lowered:
    return False
  dashboard_terms = ("dashboard", "dashbaord")
  direct_dashboard = any(term in lowered for term in dashboard_terms) and any(
    signal in lowered
    for signal in (
      "directly showing",
      "directly sowing",
      "directly show",
      "direct showing",
      "showing the dashboard",
      "showing dashboard",
      "sowing the dashbaord",
      "dashboard directly",
      "direct to dashboard",
      "skip auth",
      "skipping auth",
      "without auth",
      "without login",
      "before login",
    )
  )
  flow_language = any(
    signal in lowered
    for signal in (
      "perfect flow",
      "proper flow",
      "correct flow",
      "auth flow",
      "login flow",
      "onboarding flow",
      "routing flow",
      "flow because",
    )
  ) and any(term in lowered for term in ("auth", "login", "onboarding", "dashboard", "dashbaord", "flow"))
  guest_trial_flow = any(
    term in lowered
    for term in (
      "guest trial",
      "guest access",
      "sandbox",
      "quick-pass",
      "trial button",
      "bypasses",
      "bypass",
      "skip signup",
      "skip login",
    )
  ) and any(
    term in lowered
    for term in ("auth", "login", "onboarding", "dashboard", "click", "button", "route", "navigate", "trial")
  )
  interaction_broken = any(
    term in lowered
    for term in ("no action", "nothing happens", "not working", "doesn't work", "does not work")
  ) and any(term in lowered for term in ("click", "button", "trial", "guest", "auth"))
  login_first_flow = any(
    term in lowered
    for term in ("login", "log in", "sign in", "signin", "auth", "authenticate")
  ) and any(
    term in lowered
    for term in ("onboarding", "dashboard", "dashbaord", "home page", "homepage", "landing")
  ) and any(
    term in lowered
    for term in (
      "first",
      "then",
      "before",
      "only after",
      "redirect",
      "redirect to",
      "want to",
      "then only",
      "process",
      "provide",
      "landing to",
      "land to",
    )
  )
  follow_up_flow = any(
    term in lowered
    for term in ("still", "again", "same issue", "not fixed", "didn't work", "did not work")
  ) and any(
    term in lowered
    for term in ("landing", "land", "home", "dashboard", "auth", "login", "onboarding", "direct")
  )
  return direct_dashboard or flow_language or guest_trial_flow or interaction_broken or login_first_flow or follow_up_flow


def auth_onboarding_flow_repair_summary(prompt: str) -> str:
  lowered = str(prompt or "").lower()
  if any(term in lowered for term in ("guest trial", "sandbox", "bypass", "skip login", "skip signup")):
    return (
      "Wire the auth/trial buttons with working onClick handlers and react-router-dom navigation. "
      "Guest trial must route to the correct onboarding or dashboard state without runtime errors."
    )
  return (
    "Implement auth -> onboarding -> dashboard routing. Users must sign in first, then complete onboarding, "
    "and only then reach dashboard/home modules. Update src/App.jsx routes and any auth/onboarding page handlers."
  )


def _auth_onboarding_flow_paths(
  prompt: str,
  paths: list[str],
  files_map: dict[str, str] | None = None,
  *,
  max_paths: int = 4,
) -> list[str]:
  if not is_auth_onboarding_flow_repair_prompt(primary_update_prompt(prompt)):
    return []
  normalized_paths = [str(path) for path in paths if str(path or "").strip()]
  if not normalized_paths:
    return []

  selected: list[str] = []

  def add_path(path: str | None) -> None:
    if path and path in normalized_paths and path not in selected and len(selected) < max_paths:
      selected.append(path)

  for app_path in ("src/App.jsx", "src/App.tsx", "src/App.js", "src/App.ts"):
    add_path(app_path)

  buckets: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("auth", ("auth", "login", "signin", "sign-in", "signup", "sign-up")),
    ("onboarding", ("onboarding", "onboariding", "welcome", "setup", "wizard")),
    ("dashboard", ("dashboard", "dashbaord")),
    ("layout", ("layout", "router", "routes")),
  )
  for _bucket, markers in buckets:
    for path in normalized_paths:
      lowered_path = path.lower()
      if any(marker in lowered_path for marker in markers):
        add_path(path)
        break

  if len(selected) < max_paths and files_map:
    scored: list[tuple[int, str]] = []
    for path, content in files_map.items():
      if path in selected:
        continue
      if not path.startswith(("src/", "app/", "pages/", "components/")):
        continue
      lowered_content = str(content or "").lower()
      score = 0
      if any(token in lowered_content for token in ("navigate(", "useNavigate", "router", "route", "pathname")):
        score += 5
      if "dashboard" in lowered_content or "dashbaord" in lowered_content:
        score += 3
      if "onboarding" in lowered_content or "auth" in lowered_content or "login" in lowered_content:
        score += 3
      if score:
        scored.append((score, path))
    scored.sort(key=lambda item: (-item[0], item[1]))
    for _score, path in scored:
      add_path(path)

  return selected[:max_paths]


def _onboarding_flow_paths(
  prompt: str,
  paths: list[str],
  files_map: dict[str, str],
  *,
  max_paths: int = 3,
) -> list[str]:
  """Locate onboarding/modal/skip UI across pages, components, and App shell."""
  primary = primary_update_prompt(prompt)
  lowered = primary.lower()
  tokens = _prompt_tokens(primary)
  if not (tokens & ONBOARDING_FLOW_SIGNALS):
    return []
  strong_flow = (
    "onboarding" in lowered
    or bool(tokens & {"wizard", "walkthrough", "welcome", "setup"})
    or (bool(tokens & {"skip"}) and bool(tokens & {"modal"}))
  )
  if not strong_flow:
    return []

  scored: list[tuple[int, str]] = []
  for path in paths:
    if _is_noise_path(path):
      continue
    if not path.startswith(("src/pages/", "src/components/", "src/layouts/")) and path != "src/App.jsx":
      continue
    base = path.rsplit("/", 1)[-1].lower()
    name = base.rsplit(".", 1)[0] if "." in base else base
    content = files_map.get(path, "").lower()
    score = 0
    if "onboarding" in name:
      score += 10
    if name.lower() == "app" or path == "src/App.jsx":
      score += 2
    if "onboarding" in lowered and "onboarding" in content:
      score += 6
    if "modal" in lowered and "modal" in content:
      score += 7
    if "skip" in lowered and "skip" in content:
      score += 5
    if "wizard" in lowered and any(token in content for token in ("step", "wizard", "stage")):
      score += 4
    if path == "src/App.jsx" and ("modal" in lowered or "onboarding" in lowered):
      score += 5
    if score > 0:
      scored.append((score, path))

  scored.sort(key=lambda item: (-item[0], item[1]))
  selected = [path for _, path in scored[:max_paths]]
  if selected:
    return selected
  hinted = _page_hint_paths(prompt, paths, files_map)
  return hinted[:max_paths]


def _onboarding_flow_tasks(
  prompt: str,
  paths: list[str],
  files_map: dict[str, str],
  *,
  max_tasks: int = 5,
) -> list[dict[str, Any]]:
  flow_paths = _onboarding_flow_paths(prompt, paths, files_map, max_paths=min(3, max_tasks))
  if not flow_paths:
    return []
  if len(flow_paths) == 1:
    return [_task_for_path(flow_paths[0], scope="onboarding flow")]
  return [_task_for_path(path, scope="onboarding flow parallel") for path in flow_paths[:max_tasks]]


def is_ui_interaction_repair_prompt(prompt: str) -> bool:
  """Detect cart/button/click fixes from the latest user turn only."""
  primary = primary_update_prompt(prompt).lower()
  if not primary:
    return False
  cart_terms = ("cart", "add to cart", "checkout", "basket", "addtocart")
  button_terms = ("button", "click", "onclick", "not working", "doesn't work", "does not work", "broken")
  nav_terms = ("navbar", "header", "nav ", "navigation", "top bar")
  has_cart = any(term in primary for term in cart_terms)
  has_button_issue = any(term in primary for term in button_terms)
  has_nav = any(term in primary for term in nav_terms)
  if has_cart and (has_button_issue or has_nav or "remove" in primary):
    return True
  if has_button_issue and has_nav:
    return True
  if "remove" in primary and "button" in primary:
    if any(term in primary for term in ("onboarding", "modal", "wizard", "walkthrough", "skip")):
      return False
    return True
  if has_button_issue and any(term in primary for term in ("product", "marketplace", "shop", "store")):
    return True
  return False


def ui_interaction_repair_summary(prompt: str) -> str:
  return (
    "Fix the reported UI interaction in the navbar/header and the relevant product or marketplace page. "
    "Wire onClick handlers, shared cart state, and remove duplicate or broken cart buttons. "
    "Do not edit Auth.jsx, Onboarding.jsx, package.json, tailwind.config.js, or other locked platform files."
  )


def _cart_interaction_paths(
  prompt: str,
  paths: list[str],
  files_map: dict[str, str] | None = None,
  *,
  max_paths: int = 4,
) -> list[str]:
  if not is_ui_interaction_repair_prompt(prompt):
    return []
  normalized_paths = [str(path) for path in paths if str(path or "").strip()]
  if not normalized_paths:
    return []

  selected: list[str] = []

  def add_path(path: str | None) -> None:
    if path and path in normalized_paths and path not in selected and len(selected) < max_paths:
      selected.append(path)

  for path in normalized_paths:
    base = path.rsplit("/", 1)[-1].lower()
    if any(token in base for token in ("navbar", "header", "nav")):
      add_path(path)
  for path in normalized_paths:
    base = path.rsplit("/", 1)[-1].lower()
    if any(token in base for token in ("marketplace", "cart", "shop", "product", "store", "catalog")):
      add_path(path)

  if files_map:
    scored: list[tuple[int, str]] = []
    for path, content in files_map.items():
      if path in selected:
        continue
      if not path.startswith(("src/pages/", "src/components/")):
        continue
      lowered = str(content or "").lower()
      score = 0
      if any(token in lowered for token in ("addtocart", "add to cart", "handleaddtocart", "cart", "usestate")):
        score += 6
      if "onclick" in lowered or "onclick" in lowered:
        score += 3
      if "shoppingcart" in lowered or "carticon" in lowered:
        score += 4
      if score:
        scored.append((score, path))
    scored.sort(key=lambda item: (-item[0], item[1]))
    for _score, path in scored:
      add_path(path)

  for app_path in ("src/App.jsx", "src/App.tsx"):
    add_path(app_path)
  return selected[:max_paths]


def _resolve_legacy_heuristic_target_paths(
  prompt: str,
  *,
  paths: list[str],
  files_map: dict[str, str],
) -> list[str]:
  cart_paths = _cart_interaction_paths(prompt, paths, files_map, max_paths=4)
  if cart_paths:
    return cart_paths
  auth_flow_paths = _auth_onboarding_flow_paths(prompt, paths, files_map, max_paths=4)
  if auth_flow_paths:
    return auth_flow_paths
  flow_paths = _onboarding_flow_paths(prompt, paths, files_map, max_paths=3)
  if flow_paths:
    extras = _related_import_paths(flow_paths[:1], files_map, max_extra=1)
    return list(dict.fromkeys([*flow_paths, *extras]))[:3]
  mentioned = _mentioned_paths(prompt, paths)
  if mentioned:
    extras = _related_import_paths(mentioned[:1], files_map, max_extra=1)
    return list(dict.fromkeys([*mentioned[:2], *extras]))[:3]
  if _prompt_mentions_file_like_token(prompt):
    return []
  page_hints = _page_hint_paths(prompt, paths, files_map)
  if page_hints:
    return page_hints
  data_tasks = _data_layer_tasks(prompt, paths)
  if data_tasks:
    return [task["paths"][0] for task in data_tasks][:3]
  return _content_match_paths(prompt, files_map, max_results=3)


def resolve_scoped_target_paths(
  prompt: str,
  *,
  paths: list[str],
  files_map: dict[str, str],
) -> list[str]:
  try:
    from ..runtime_config import legacy_parallel_updates_enabled, unified_update_engine_enabled
  except ImportError:
    from agents.runtime_config import legacy_parallel_updates_enabled, unified_update_engine_enabled

  if unified_update_engine_enabled() and not legacy_parallel_updates_enabled():
    try:
      from ..chat_history import primary_update_prompt
    except ImportError:
      from agents.chat_history import primary_update_prompt
    scope_prompt = primary_update_prompt(prompt)
    mentioned = _mentioned_paths(scope_prompt, paths)
    if mentioned:
      extras = _related_import_paths(mentioned[:1], files_map, max_extra=1)
      return list(dict.fromkeys([*mentioned[:2], *extras]))[:3]
    if _prompt_mentions_file_like_token(scope_prompt):
      return []
    page_hints = _page_hint_paths(scope_prompt, paths, files_map)
    if page_hints:
      return page_hints
    data_tasks = _data_layer_tasks(scope_prompt, paths)
    if data_tasks:
      return [task["paths"][0] for task in data_tasks][:3]
    content_matches = _content_match_paths(scope_prompt, files_map, max_results=3)
    if content_matches:
      return content_matches
    tool_files = [{"path": path, "content": files_map.get(path, "")} for path in paths]
    try:
      from ..runtime_config import code_index_enabled
    except ImportError:
      from agents.runtime_config import code_index_enabled
    if code_index_enabled():
      try:
        from ..code_index.retriever import retrieve_code_context
      except ImportError:
        from agents.code_index.retriever import retrieve_code_context
      indexed = [
        str(match.get("path") or "")
        for match in retrieve_code_context(scope_prompt, tool_files, limit=3)
        if match.get("path") in files_map
      ]
      if indexed:
        return indexed
    try:
      from ..agent_runtime.update_analysis import build_update_code_search_matches
    except ImportError:
      from agents.agent_runtime.update_analysis import build_update_code_search_matches
    searched = [
      str(match.get("path") or "")
      for match in build_update_code_search_matches(scope_prompt, tool_files)
      if match.get("path") in files_map
    ]
    return searched[:3]

  return _resolve_legacy_heuristic_target_paths(prompt, paths=paths, files_map=files_map)


def _folder_tasks(prompt: str, paths: list[str], intent: str) -> list[dict[str, Any]]:
  tokens = _prompt_tokens(prompt)
  tasks: list[dict[str, Any]] = []
  for prefix in FOLDER_PREFIXES:
    folder_name = prefix.rstrip("/").rsplit("/", 1)[-1]
    signals = {folder_name, folder_name.rstrip("s"), f"new {folder_name}"}
    if not (tokens & signals or f"{folder_name}/" in prompt.lower()):
      continue
    folder_paths = [path for path in paths if path.startswith(prefix)]
    if folder_paths:
      for index, path in enumerate(folder_paths[:8]):
        tasks.append(
          {
            "id": f"folder-{prefix.replace('/', '-')}{index}",
            "kind": "file",
            "paths": [path],
            "scope": f"Part of {prefix} update",
            "depends_on": [],
          }
        )
    elif intent == "website_generation" and folder_paths:
      tasks.append(
        {
          "id": f"folder-{prefix.replace('/', '-')}-new",
          "kind": "folder",
          "paths": [prefix],
          "scope": f"Create files under {prefix}",
          "depends_on": [],
        }
      )
  return tasks


def _task_for_path(path: str, *, scope: str = "", depends_on: list[str] | None = None) -> dict[str, Any]:
  safe_id = re.sub(r"[^a-z0-9]+", "-", path.lower()).strip("-")
  if scope:
    scope_slug = re.sub(r"[^a-z0-9]+", "-", scope.lower()).strip("-")
    safe_id = f"{safe_id}-{scope_slug}" if scope_slug else safe_id
  return {
    "id": f"file-{safe_id}",
    "kind": "file_section" if scope else "file",
    "paths": [path],
    "scope": scope,
    "depends_on": list(depends_on or []),
  }


def _task_for_paths(paths: list[str], *, scope: str = "", depends_on: list[str] | None = None) -> dict[str, Any]:
  clean_paths = [str(path).strip() for path in paths if str(path or "").strip()]
  safe_id = re.sub(r"[^a-z0-9]+", "-", "-".join(clean_paths).lower()).strip("-")
  if scope:
    scope_slug = re.sub(r"[^a-z0-9]+", "-", scope.lower()).strip("-")
    safe_id = f"{safe_id}-{scope_slug}" if scope_slug else safe_id
  return {
    "id": f"file-group-{safe_id or 'update'}",
    "kind": "file_group",
    "paths": clean_paths,
    "scope": scope,
    "depends_on": list(depends_on or []),
  }


def _safe_project_path(path: Any) -> str:
  normalized = str(path or "").strip().replace("\\", "/")
  normalized = re.sub(r"/+", "/", normalized)
  if normalized.startswith("/") or normalized.startswith("../") or "/../" in normalized:
    return ""
  if any(part in normalized.lower().split("/") for part in {"node_modules", ".git", "dist", "build"}):
    return ""
  return normalized


def _project_file_brief(files: list[dict[str, Any]], *, max_files: int = 120, content_chars: int = 500) -> list[dict[str, str]]:
  brief: list[dict[str, str]] = []
  for item in files:
    if not isinstance(item, dict):
      continue
    path = _safe_project_path(item.get("path"))
    if not path or _is_noise_path(path):
      continue
    content = str(item.get("content") or item.get("code") or "")
    brief.append({"path": path, "content_preview": content[:content_chars]})
    if len(brief) >= max_files:
      break
  return brief


def _normalize_llm_task_plan(
  payload: dict[str, Any],
  *,
  intent: str,
  files_map: dict[str, str],
  max_tasks: int,
) -> dict[str, Any] | None:
  raw_tasks = payload.get("tasks")
  if not isinstance(raw_tasks, list):
    return None
  available_paths = set(files_map)
  tasks: list[dict[str, Any]] = []
  for index, raw_task in enumerate(raw_tasks[:max_tasks]):
    if not isinstance(raw_task, dict):
      continue
    raw_paths = raw_task.get("paths")
    if not isinstance(raw_paths, list):
      continue
    clean_paths: list[str] = []
    for raw_path in raw_paths:
      path = _safe_project_path(raw_path)
      if not path:
        continue
      if intent == "website_update" and path not in available_paths:
        continue
      if intent != "website_update" and not (
        path in available_paths
        or path.startswith(("src/", "app/", "backend/"))
        or path in GREENFIELD_SCAFFOLD_PATHS
      ):
        continue
      if path not in clean_paths:
        clean_paths.append(path)
    if not clean_paths:
      continue
    scope = str(raw_task.get("scope") or raw_task.get("reason") or "model planned task").strip()[:240]
    depends_on = [str(item).strip() for item in (raw_task.get("depends_on") or []) if str(item or "").strip()]
    if len(clean_paths) == 1:
      task = _task_for_path(clean_paths[0], scope=scope, depends_on=depends_on)
    else:
      task = _task_for_paths(clean_paths, scope=scope, depends_on=depends_on)
    task["id"] = str(raw_task.get("id") or task["id"] or f"llm-task-{index + 1}").strip()[:160]
    task["kind"] = str(raw_task.get("kind") or task.get("kind") or "file").strip()[:80]
    tasks.append(task)
  if not tasks:
    return None
  task_by_id = {task["id"]: task for task in tasks}
  parallel_module = bool(payload.get("use_parallel_workers")) or len(tasks) >= 2
  waves = _resolve_wave_path_overlaps(_build_waves(tasks, files_map, parallel_module=parallel_module), task_by_id)
  scoped_targets = [
    path
    for task in tasks
    for path in (task.get("paths") or [])
    if str(path or "").strip()
  ]
  return {
    "tasks": tasks,
    "waves": waves,
    "task_count": len(tasks),
    "wave_count": len(waves),
    "parallel_waves": _parallel_worker_waves(waves),
    "planning_source": "llm_file_work_planner",
    "planning_reason": str(payload.get("reason") or "").strip()[:1000],
    "scoped_targets": scoped_targets[:max_tasks],
    "use_parallel_workers": _should_use_parallel_workers(tasks=tasks, waves=waves),
    "greenfield": bool(payload.get("greenfield")) if intent != "website_update" else False,
  }


def _llm_plan_file_work(
  *,
  artifact_provider: Any | None,
  prompt: str,
  intent: str,
  project_files: list[dict[str, Any]],
  files_map: dict[str, str],
  max_tasks: int,
  update_analysis: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
  if artifact_provider is None or not hasattr(artifact_provider, "generate_json"):
    return None
  project_brief = _project_file_brief(project_files)
  if intent == "website_update" and not project_brief:
    return None
  system_instruction = (
    "You are Worktual's file-work planning agent. Plan implementation tasks from the full user meaning, "
    "not from keyword triggers. Choose the smallest safe set of files for the requested outcome. "
    "For updates, every path must already exist in the provided project file list. For generation, propose "
    "bounded React/Vite paths only when needed. Return strict JSON only."
  )
  planning_prompt = (
    f"Intent: {intent}\n"
    f"User request:\n{primary_update_prompt(prompt)}\n\n"
    f"Project files with previews:\n{project_brief}\n\n"
    f"Existing update analysis, if any:\n{update_analysis or {}}\n\n"
    "Return JSON with keys: tasks, use_parallel_workers, greenfield, reason. "
    "Each task must have: id, kind, paths, scope, depends_on. "
    "Prefer one task per independent file group; group related route/auth/page files when they must change together."
  )
  try:
    payload = artifact_provider.generate_json(
      planning_prompt,
      system_instruction=system_instruction,
      trace_label="llm_file_work_planner",
      max_output_tokens=1800,
    )
  except Exception:
    return None
  if not isinstance(payload, dict):
    return None
  return _normalize_llm_task_plan(payload, intent=intent, files_map=files_map, max_tasks=max_tasks)


def _build_waves(
  tasks: list[dict[str, Any]],
  files_map: dict[str, str],
  *,
  parallel_module: bool = False,
) -> list[list[str]]:
  if not tasks:
    return []
  if parallel_module and len(tasks) >= 2 and not any(task.get("depends_on") for task in tasks):
    return [[task["id"] for task in tasks]]
  known_paths = set(files_map)
  task_by_id = {task["id"]: task for task in tasks}
  path_to_task_ids: dict[str, list[str]] = {}
  for task in tasks:
    for path in task.get("paths") or []:
      path_to_task_ids.setdefault(path, []).append(task["id"])

  def external_deps(task: dict[str, Any]) -> set[str]:
    deps: set[str] = set(task.get("depends_on") or [])
    for path in task.get("paths") or []:
      content = files_map.get(path, "")
      for imported in _import_dependencies(path, content, known_paths):
        for task_id in path_to_task_ids.get(imported, []):
          if task_id != task["id"]:
            deps.add(task_id)
    return deps

  remaining = {task["id"] for task in tasks}
  waves: list[list[str]] = []
  while remaining:
    ready = [
      task_id
      for task_id in remaining
      if external_deps(task_by_id[task_id]).issubset({tid for wave in waves for tid in wave})
    ]
    if not ready:
      ready = [next(iter(remaining))]
    waves.append(ready)
    remaining -= set(ready)
  return waves


def _task_paths(task: dict[str, Any]) -> set[str]:
  return {str(path).strip() for path in (task.get("paths") or []) if str(path).strip()}


def _partition_wave_disjoint_tasks(
  wave: list[str],
  task_by_id: dict[str, dict[str, Any]],
) -> list[list[str]]:
  """Split a wave so no two tasks in the same group share a file path."""
  if len(wave) <= 1:
    return [wave]
  groups: list[list[str]] = []
  group_paths: list[set[str]] = []
  for task_id in wave:
    paths = _task_paths(task_by_id.get(task_id) or {})
    placed = False
    for index, group in enumerate(groups):
      if paths.isdisjoint(group_paths[index]):
        group.append(task_id)
        group_paths[index] |= paths
        placed = True
        break
    if not placed:
      groups.append([task_id])
      group_paths.append(set(paths))
  return groups


def _resolve_wave_path_overlaps(
  waves: list[list[str]],
  task_by_id: dict[str, dict[str, Any]],
) -> list[list[str]]:
  """Ensure parallel workers never edit the same path within one wave."""
  resolved: list[list[str]] = []
  for wave in waves:
    for group in _partition_wave_disjoint_tasks(wave, task_by_id):
      if group:
        resolved.append(group)
  return resolved


def _parallel_worker_waves(waves: list[list[str]]) -> int:
  return sum(1 for wave in waves if len(wave) > 1)


def _should_use_parallel_workers(
  *,
  tasks: list[dict[str, Any]],
  waves: list[list[str]],
) -> bool:
  """Parallel workers only when at least one wave runs 2+ disjoint-path tasks."""
  if len(tasks) < 2:
    return False
  return _parallel_worker_waves(waves) > 0


GREENFIELD_SCAFFOLD_PATHS = (
  "package.json",
  "index.html",
  "vite.config.js",
  "tailwind.config.js",
  "postcss.config.js",
  "src/main.jsx",
  "src/index.css",
  "src/App.jsx",
)


def _component_name_from_path(path: str) -> str:
  base = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
  parts = [part for part in re.split(r"[^a-zA-Z0-9]+", base) if part]
  name = "".join(part[:1].upper() + part[1:] for part in parts) or "GeneratedModule"
  if name[0].isdigit():
    name = f"Generated{name}"
  return name


def _relative_import_from_app(path: str) -> str:
  if path.startswith("src/"):
    return f"./{path.removeprefix('src/')}".rsplit(".", 1)[0]
  return f"./{path}".rsplit(".", 1)[0]


def _label_to_page_path(label: str) -> str:
  export_name = _component_name_from_path(f"src/pages/{label}.jsx")
  return f"src/pages/{export_name}.jsx"


def _infer_greenfield_flow_page_paths(prompt: str) -> list[str]:
  lowered = str(prompt or "").lower()
  flow_specs = (
    ("auth", "Auth"),
    ("login", "Auth"),
    ("onboarding", "Onboarding"),
    ("dashboard", "Dashboard"),
    ("operation", "Operations"),
    ("operations hub", "Operations"),
    ("operation hub", "Operations"),
    ("settings", "Settings"),
    ("reports", "Reports"),
    ("analytics", "Analytics"),
  )
  paths: list[str] = []
  for marker, page_name in flow_specs:
    if marker in lowered:
      paths.append(f"src/pages/{page_name}.jsx")
  for segment in re.split(r"(?:->|→| then | after )", lowered):
    cleaned = segment.strip()
    if not cleaned:
      continue
    for marker, page_name in flow_specs:
      if marker in cleaned:
        candidate = f"src/pages/{page_name}.jsx"
        if candidate not in paths:
          paths.append(candidate)
  return list(dict.fromkeys(paths))


def _infer_greenfield_named_module_paths(prompt: str) -> list[str]:
  """Prioritize explicitly named product modules over verbose sentence labels."""
  lowered = str(prompt or "").lower()
  module_specs = (
    (("lead", "leads"), "Leads"),
    (("contact", "contacts"), "Contacts"),
    (("deal", "deals"), "Deals"),
    (("sales",), "Sales"),
    (("project", "projects"), "Projects"),
    (("product", "products"), "Products"),
    (("finance", "billing"), "Finance"),
    (("channel", "channels"), "Channels"),
    (("main ai chat", "ai chat", "copilot", "assistant"), "AiChat"),
    (("report", "reports"), "Reports"),
    (("analytics",), "Analytics"),
  )
  paths: list[str] = []
  for markers, page_name in module_specs:
    if any(re.search(rf"\b{re.escape(marker)}\b", lowered) for marker in markers):
      paths.append(f"src/pages/{page_name}.jsx")
  return paths


def _infer_greenfield_backend_paths(prompt: str) -> list[str]:
  lowered = str(prompt or "").lower()
  if not any(token in lowered for token in ("fastapi", "postgresql", "postgres", "backend", "database", "api", "sqlalchemy")):
    return []
  return list(
    dict.fromkeys(
      [
        "backend/main.py",
        "backend/models.py",
        "backend/schemas.py",
        "backend/database.py",
      ]
    )
  )


def _greenfield_backend_task(path: str) -> dict[str, Any]:
  export_name = _component_name_from_path(path)
  return {
    "id": _greenfield_task_id("greenfield-backend", path),
    "kind": "greenfield_backend",
    "paths": [path],
    "contract": {
      "role": "backend_worker",
      "export_type": "module",
      "export_name": export_name,
      "provides": [path],
      "imports_allowed": [],
      "acceptance": "Runnable backend module with clear exports and no frontend imports.",
    },
    "scope": (
      f"Create {path} for the requested API/database layer using FastAPI, Pydantic, and PostgreSQL conventions. "
      "Keep imports minimal and match entities named in the user brief."
    ),
    "depends_on": [],
  }


def _infer_greenfield_website_type(prompt: str) -> str:
  lowered = str(prompt or "").lower()
  if any(token in lowered for token in ("ccaas", "contact center", "call center", "omnichannel")):
    return "ccaas"
  if any(token in lowered for token in ("crm", "lead", "deal", "sales pipeline")):
    return "crm"
  if any(token in lowered for token in ("ecommerce", "e-commerce", "store", "shopping", "product catalog")):
    return "ecommerce"
  if any(token in lowered for token in ("portfolio", "personal site", "resume website")):
    return "portfolio"
  if any(token in lowered for token in ("saas", "software as a service")):
    return "saas"
  return "custom"


def _infer_greenfield_page_paths(prompt: str, *, max_pages: int = 6) -> list[str]:
  flow_paths = _infer_greenfield_flow_page_paths(prompt)
  module_paths = _infer_greenfield_named_module_paths(prompt)
  label_paths = [_label_to_page_path(label) for label in _extract_prompt_page_labels(prompt, max_labels=max_pages)]
  paths = list(dict.fromkeys([*flow_paths, *module_paths, *label_paths]))
  if not paths:
    paths = ["src/pages/Home.jsx"]
  elif not any("home" in path.lower() for path in paths):
    paths.insert(0, "src/pages/Home.jsx")
  if tokens := _prompt_tokens(prompt):
    if tokens & {"chat", "copilot", "assistant", "autonomous"}:
      paths.append("src/pages/ChatWorkspace.jsx")
  return list(dict.fromkeys(paths))[:max_pages]


def _infer_greenfield_component_paths(prompt: str) -> list[str]:
  tokens = _prompt_tokens(prompt)
  paths = ["src/components/Layout.jsx", "src/components/Navbar.jsx", "src/components/Footer.jsx"]
  if tokens & {"sidebar", "nav", "menu", "module", "modules", "dashboard", "crm", "workspace"}:
    paths.append("src/components/Sidebar.jsx")
  if tokens & {"chat", "assistant", "copilot", "ai"}:
    paths.append("src/components/CopilotPanel.jsx")
    paths.append("src/components/ChatWorkspace.jsx")
  if tokens & {"enterprise", "saas", "crm", "platform", "feature", "features"}:
    paths.append("src/components/FeatureGrid.jsx")
  return list(dict.fromkeys(paths))[:5]


def _greenfield_task_id(prefix: str, path: str) -> str:
  safe_id = re.sub(r"[^a-z0-9]+", "-", path.lower()).strip("-")
  return f"{prefix}-{safe_id}"


def _greenfield_page_task(path: str) -> dict[str, Any]:
  page_name = path.rsplit("/", 1)[-1]
  export_name = _component_name_from_path(path)
  return {
    "id": _greenfield_task_id("greenfield-page", path),
    "kind": "greenfield_page",
    "paths": [path],
    "contract": {
      "role": "page_worker",
      "export_type": "default",
      "export_name": export_name,
      "provides": [path],
      "imports_allowed": ["react"],
      "acceptance": "Standalone page component, no relative imports from same-wave co-workers, default export present.",
    },
    "scope": (
      f"Create a complete, enterprise-quality {page_name} with multiple sections, real copy, "
      f"accessible contrast, responsive layout, and working interactivity. "
      f"Every button/CTA must use real onClick handlers and react-router-dom navigation where appropriate. "
      f"Export default function {export_name} ready for App.jsx routes."
    ),
    "depends_on": [],
  }


def _greenfield_component_task(path: str) -> dict[str, Any]:
  component_name = path.rsplit("/", 1)[-1]
  export_name = _component_name_from_path(path)
  return {
    "id": _greenfield_task_id("greenfield-component", path),
    "kind": "greenfield_component",
    "paths": [path],
    "contract": {
      "role": "component_worker",
      "export_type": "default",
      "export_name": export_name,
      "provides": [path],
      "imports_allowed": ["react"],
      "acceptance": "Reusable component with default export and no dependency on pages that may still be generating.",
    },
    "scope": f"Create reusable {component_name} shared by pages (layout, nav, panels). Export default function {export_name}.",
    "depends_on": [],
  }


def _greenfield_data_file_task(path: str) -> dict[str, Any]:
  export_name = "themeTokens" if "theme" in path.lower() else "mockData"
  return {
    "id": _greenfield_task_id("greenfield-data", path),
    "kind": "greenfield_data_file",
    "paths": [path],
    "contract": {
      "role": "data_worker",
      "export_type": "named",
      "export_name": export_name,
      "provides": [path],
      "imports_allowed": [],
      "acceptance": f"Named export `{export_name}` with serializable data only.",
    },
    "scope": "Provide theme tokens or mock data aligned with the user prompt.",
    "depends_on": [],
  }


def _greenfield_coordination_contract(
  *,
  website_type: str,
  module_tasks: list[dict[str, Any]],
  app_task: dict[str, Any],
) -> dict[str, Any]:
  task_contracts: list[dict[str, Any]] = []
  for task in [*module_tasks, app_task]:
    path = (task.get("paths") or [""])[0]
    contract = dict(task.get("contract") or {})
    task_contracts.append(
      {
        "task_id": task.get("id"),
        "kind": task.get("kind"),
        "allowed_paths": list(task.get("paths") or []),
        "depends_on": list(task.get("depends_on") or []),
        "export_name": contract.get("export_name"),
        "export_type": contract.get("export_type"),
        "import_path_from_app": _relative_import_from_app(path) if path.startswith("src/") else "",
        "acceptance": contract.get("acceptance"),
      }
    )
  return {
    "website_type": website_type,
    "chief_orchestrator": "Assign workers by independent file ownership, then verify syntax/imports before commit.",
    "main_coding_agent": "Owns integration contract, route wiring, and final merge. Co-workers own one file each.",
    "worker_protocol": "worktual-parallel-a2a-v1",
    "communication_rules": [
      "Every co-worker writes only allowed_paths.",
      "Wave-1 page/component/data workers must not import files from same-wave co-workers.",
      "Workers publish staged paths and exports to shared memory after every write.",
      "The app-shell worker imports only completed exports visible in shared memory.",
    ],
    "task_contracts": task_contracts,
  }


def build_greenfield_streaming_prompt(prompt: str, *, max_tasks: int = 16) -> str:
  """Single-agent greenfield prompt: file blueprint without parallel worker cost."""
  plan = plan_greenfield_parallel_tasks(prompt, max_tasks=max_tasks)
  paths: list[str] = []
  for task in plan.get("tasks") or []:
    if not isinstance(task, dict):
      continue
    paths.extend(str(path) for path in (task.get("paths") or []) if str(path or "").strip())
  unique_paths = list(dict.fromkeys(paths))
  if not unique_paths:
    return prompt.strip()
  blueprint = "\n".join(f"- {path}" for path in unique_paths)
  website_type = str(plan.get("website_type") or "custom")
  return (
    f"{prompt.strip()}\n\n"
    "## Greenfield build blueprint\n"
    f"Website type: {website_type}\n"
    "Generate a complete working React + Vite + Tailwind project using write_file. "
    "Platform scaffold files already exist — do not rewrite "
    "index.html, package.json, package-lock.json, vite.config.js, tailwind.config.js, src/index.css, "
    "postcss.config.js, or src/main.jsx unless required to fix a build error.\n"
    "Create these files with consistent default exports, shared mock data, matching React Router wiring in src/App.jsx, "
    "and working button/link handlers (no dead CTAs):\n"
    f"{blueprint}\n\n"
    "Before finishing: ensure imports resolve, routes match page components, and the app builds without errors."
  )


def plan_greenfield_parallel_tasks(prompt: str, *, max_tasks: int = 16) -> dict[str, Any]:
  """Build a bounded greenfield plan with exactly three concurrent workers."""
  try:
    from ..runtime_config import parallel_greenfield_max_tasks
  except ImportError:
    from agents.runtime_config import parallel_greenfield_max_tasks

  configured_task_cap = parallel_greenfield_max_tasks()
  rich_greenfield = is_rich_greenfield_website_request(prompt)
  if rich_greenfield:
    configured_task_cap = max(configured_task_cap, 16)
  file_budget = max(8, min(max_tasks, configured_task_cap))
  website_type = _infer_greenfield_website_type(prompt)
  comp_paths = _infer_greenfield_component_paths(prompt)
  data_paths = ["src/data/mockData.js"] if rich_greenfield else ["src/theme/tokens.js", "src/data/mockData.js"]
  page_budget = min(12, max(6 if rich_greenfield else 3, file_budget - len(data_paths) - 1))
  page_paths = _infer_greenfield_page_paths(prompt, max_pages=page_budget)
  backend_paths = _infer_greenfield_backend_paths(prompt)
  try:
    from ..generation_engine.planning import build_three_worker_greenfield_plan
  except ImportError:
    from agents.generation_engine.planning import build_three_worker_greenfield_plan
  return build_three_worker_greenfield_plan(
    prompt=prompt,
    website_type=website_type,
    page_paths=page_paths,
    component_paths=comp_paths,
    data_paths=data_paths,
    backend_paths=backend_paths,
  )


def plan_file_work(
  prompt: str,
  *,
  intent: str,
  project_files: list[dict[str, Any]],
  max_tasks: int = 12,
  update_analysis: dict[str, Any] | None = None,
  artifact_provider: Any | None = None,
) -> dict[str, Any]:
  paths = [
    str(item.get("path") or "")
    for item in project_files
    if isinstance(item, dict) and item.get("path")
  ]
  files_map = {
    str(item.get("path") or ""): str(item.get("content") or "")
    for item in project_files
    if isinstance(item, dict) and item.get("path")
  }
  llm_work_plan = _llm_plan_file_work(
    artifact_provider=artifact_provider,
    prompt=prompt,
    intent=intent,
    project_files=project_files,
    files_map=files_map,
    max_tasks=max_tasks,
    update_analysis=update_analysis,
  )
  if llm_work_plan:
    return llm_work_plan

  if intent == "website_update" and isinstance(update_analysis, dict):
    try:
      from .update_preflight import tasks_from_update_analysis
    except ImportError:
      from agents.streaming.update_preflight import tasks_from_update_analysis
    analysis_tasks = tasks_from_update_analysis(update_analysis, max_tasks=max_tasks)
    if analysis_tasks:
      task_by_id = {task["id"]: task for task in analysis_tasks}
      parallel_module = len(analysis_tasks) >= 2
      waves = _resolve_wave_path_overlaps(
        _build_waves(analysis_tasks, files_map, parallel_module=parallel_module),
        task_by_id,
      )
      parallelizable = _parallel_worker_waves(waves)
      scoped_targets = [
        str(path)
        for task in analysis_tasks
        for path in (task.get("paths") or [])
        if str(path or "").strip()
      ]
      return {
        "tasks": analysis_tasks,
        "waves": waves,
        "task_count": len(analysis_tasks),
        "wave_count": len(waves),
        "parallel_waves": parallelizable,
        "planning_source": "update_preflight_tasks",
        "scoped_targets": scoped_targets[:max_tasks],
        "use_parallel_workers": _should_use_parallel_workers(tasks=analysis_tasks, waves=waves),
        "greenfield": False,
        "update_analysis": update_analysis,
      }

  try:
    from ..project_workspace import is_greenfield_generation
  except ImportError:
    from agents.project_workspace import is_greenfield_generation
  greenfield = is_greenfield_generation(intent=intent, files=project_files)
  explicit_website_generation = intent == "website_generation" and is_explicit_greenfield_website_request(prompt)
  rich_website_generation = intent == "website_generation" and is_rich_greenfield_website_request(prompt)
  rebuild_website_generation = intent == "website_generation" and is_requirement_rebuild_request(prompt)
  prompt_requires_greenfield = explicit_website_generation and not _has_frontend_application_files(paths)
  if (
    greenfield
    or (intent == "website_generation" and _is_scaffold_only_generation(project_files))
    or prompt_requires_greenfield
    or rich_website_generation
    or rebuild_website_generation
  ):
    return plan_greenfield_parallel_tasks(prompt, max_tasks=16 if (rich_website_generation or rebuild_website_generation) else max_tasks)

  tasks: list[dict[str, Any]] = []
  mentioned = _mentioned_paths(prompt, paths)
  parallel_module = False

  if intent == "website_update":
    try:
      from ..runtime_config import legacy_parallel_updates_enabled, unified_update_engine_enabled
    except ImportError:
      from agents.runtime_config import legacy_parallel_updates_enabled, unified_update_engine_enabled
    use_legacy_heuristics = not unified_update_engine_enabled() or legacy_parallel_updates_enabled()
    if use_legacy_heuristics:
      auth_flow_paths = _auth_onboarding_flow_paths(prompt, paths, files_map, max_paths=min(4, max_tasks))
      if auth_flow_paths:
        tasks = [
          _task_for_paths(
            auth_flow_paths,
            scope="auth onboarding dashboard flow repair",
          )
        ]

  if intent == "website_update":
    module_tasks = _module_parallel_tasks(prompt, paths, files_map, max_tasks=max_tasks)
    if not tasks and len(module_tasks) >= 2:
      tasks = module_tasks
      parallel_module = True

  if not tasks and intent == "website_update":
    flow_tasks = _onboarding_flow_tasks(prompt, paths, files_map, max_tasks=max_tasks)
    if len(flow_tasks) >= 2:
      tasks = flow_tasks
      parallel_module = True
    elif flow_tasks:
      tasks = flow_tasks

  if not tasks and intent == "website_update":
    data_tasks = _data_layer_tasks(prompt, paths)
    if len(data_tasks) >= 2:
      tasks = data_tasks
      parallel_module = True
    elif data_tasks:
      tasks = data_tasks

  if not tasks and intent == "website_update":
    page_hints = _page_hint_paths(prompt, paths, files_map)
    for path in page_hints:
      tasks.append(_task_for_path(path, scope="page hint"))

  if not tasks and intent == "website_update" and is_brand_rename_prompt(prompt):
    for path in brand_title_target_paths(paths):
      tasks.append(_task_for_path(path, scope="brand/title rename"))

  if not tasks:
    for path in mentioned[:max_tasks]:
      sections = _detect_sections(prompt, path)
      if len(sections) > 1:
        previous_id: str | None = None
        for section in sections:
          depends = [previous_id] if previous_id else []
          task = _task_for_path(path, scope=section, depends_on=depends)
          tasks.append(task)
          previous_id = task["id"]
      else:
        scope = sections[0] if sections else ""
        tasks.append(_task_for_path(path, scope=scope))

  if not tasks and intent == "website_update":
    content_matches = _content_match_paths(prompt, files_map, max_results=2)
    for path in content_matches:
      tasks.append(_task_for_path(path, scope="content match"))

  if not tasks:
    if not greenfield:
      tasks.extend(_folder_tasks(prompt, paths, intent))

  if not tasks and intent == "website_generation":
    page_paths = [path for path in paths if path.startswith("src/pages/")][:max_tasks]
    component_paths = [path for path in paths if path.startswith("src/components/")][:max_tasks]
    for path in component_paths:
      tasks.append(_task_for_path(path))
    for path in page_paths:
      task = _task_for_path(path)
      comp_ids = [t["id"] for t in tasks if t["paths"][0].startswith("src/components/")]
      if comp_ids:
        task["depends_on"] = comp_ids[:3]
      tasks.append(task)

  if not tasks and mentioned:
    tasks = [_task_for_path(path) for path in mentioned[:max_tasks]]

  if intent == "website_update" and mentioned and len(tasks) > len(mentioned):
    scoped_paths = {
      task["paths"][0]
      for task in tasks
      if task.get("paths")
      and (
        str(task.get("scope") or "")
        in {
          "data update",
          "data display",
          "content match",
          "brand/title rename",
          "page hint",
          "module parallel agent",
          "onboarding flow",
          "onboarding flow parallel",
        }
        or str(task.get("scope") or "").startswith("onboarding flow")
      )
    }
    flow_paths = set(_onboarding_flow_paths(prompt, paths, files_map, max_paths=3))
    allowed = (
      set(mentioned)
      | scoped_paths
      | flow_paths
      | set(_related_import_paths(mentioned, files_map, max_extra=1))
    )
    tasks = [task for task in tasks if task.get("paths") and task["paths"][0] in allowed]

  if len(tasks) > max_tasks:
    tasks = tasks[:max_tasks]

  if intent == "website_update" and not parallel_module and not greenfield:
    scopes = {str(task.get("scope") or "") for task in tasks}
    unique_paths = {task["paths"][0] for task in tasks if task.get("paths")}
    sequential_same_file = len(unique_paths) == 1 and len(tasks) > 1
    preserve_multi_task = (
      is_brand_rename_prompt(prompt)
      or "brand/title rename" in scopes
      or sequential_same_file
      or any(str(task.get("scope") or "").startswith(("module parallel", "onboarding flow")) for task in tasks)
    )
    if not preserve_multi_task:
      mentioned_only = _mentioned_paths(prompt, paths)
      if len(mentioned_only) <= 1 and len(tasks) > 1 and len(unique_paths) > 1:
        primary = next((task for task in tasks if task.get("paths") and task["paths"][0] in mentioned_only), tasks[0])
        tasks = [primary]

  parallel_module = parallel_module or any(
    str(task.get("scope") or "").startswith(("module parallel", "onboarding flow"))
    for task in tasks
  )
  if greenfield:
    parallel_module = False
  task_by_id = {task["id"]: task for task in tasks}
  waves = _resolve_wave_path_overlaps(_build_waves(tasks, files_map, parallel_module=parallel_module), task_by_id)
  parallelizable = _parallel_worker_waves(waves)
  scoped_targets = [
    str(path)
    for task in tasks
    for path in (task.get("paths") or [])
    if str(path or "").strip()
  ] or mentioned
  return {
    "tasks": tasks,
    "waves": waves,
    "task_count": len(tasks),
    "wave_count": len(waves),
    "parallel_waves": parallelizable,
    "planning_source": "deterministic_file_planner",
    "scoped_targets": scoped_targets[:max_tasks],
    "use_parallel_workers": _should_use_parallel_workers(tasks=tasks, waves=waves),
    "greenfield": greenfield,
  }
