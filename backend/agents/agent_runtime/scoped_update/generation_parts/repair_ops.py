from __future__ import annotations

import re
import posixpath
from typing import Any

from ....artifacts import normalize_generated_file_code
from ...values import object_value, string_list, text_or_default
from ..response_parts import scoped_update_has_effective_change
from .feature_ops import (
  component_name_from_path,
  deterministic_feature_component_code,
  deterministic_feature_items_for_task,
)

def deterministic_created_component_content_changes(
  *,
  task: dict[str, Any],
  update_analysis: dict[str, Any],
  working_files: list[dict[str, str]],
  created_candidate_paths: list[str],
) -> list[dict[str, str]]:
  if text_or_default(update_analysis.get("update_mode"), "") != "feature_patch":
    return []
  created_path_set = set(created_candidate_paths)
  if not created_path_set:
    return []
  working_by_path = {
    text_or_default(file_item.get("path"), ""): text_or_default(file_item.get("content"), "")
    for file_item in working_files
    if isinstance(file_item, dict) and text_or_default(file_item.get("path"), "")
  }
  component_path = next(
    (
      path
      for path in created_candidate_paths
      if path in working_by_path and path.endswith((".jsx", ".tsx"))
    ),
    "",
  )
  if not component_path:
    return []
  items = deterministic_feature_items_for_task(task, update_analysis)
  if not items:
    return []
  component_name = component_name_from_path(component_path)
  if not component_name:
    return []
  return [
    {
      "path": component_path,
      "content": deterministic_feature_component_code(
        component_name=component_name,
        items=items,
        feature_plan=object_value(update_analysis.get("feature_plan")),
      ),
    }
  ]


def deterministic_onboarding_chat_update_changes(
  *,
  prompt: str,
  update_analysis: dict[str, Any],
  existing_files: list[dict[str, str]],
) -> list[dict[str, str]]:
  _ = prompt, update_analysis, existing_files
  return []


def deterministic_undefined_name_runtime_fix_changes(
  *,
  prompt: str,
  update_analysis: dict[str, Any],
  existing_files: list[dict[str, str]],
) -> list[dict[str, str]]:
  candidate_paths = set(string_list(update_analysis.get("candidate_files"), []))
  if not candidate_paths:
    return []
  request_text = scoped_update_request_text(prompt, update_analysis)
  lowered = request_text.lower()
  if "name" not in lowered:
    return []
  if "cannot read properties" not in lowered and "undefined (reading" not in lowered:
    return []

  for file_item in existing_files:
    path = text_or_default(file_item.get("path"), "")
    content = text_or_default(file_item.get("content"), "")
    if path not in candidate_paths or not path.endswith((".jsx", ".tsx", ".js", ".ts")):
      continue
    updated = deterministic_undefined_name_runtime_fix_code(path=path, content=content)
    if updated != content and updated.strip():
      return [{"path": path, "content": updated}]
  return []


def deterministic_undefined_name_runtime_fix_code(*, path: str, content: str) -> str:
  if not path.endswith((".jsx", ".tsx", ".js", ".ts")):
    return content
  updated = content
  if "config" in updated and ("config.name" in updated or "config={config}" in updated or "useState(null)" in updated):
    updated = ensure_default_config_declaration(updated)
    updated = re.sub(
      r"(const\s+\[\s*config\s*,\s*setConfig\s*\]\s*=\s*useState\()\s*null\s*(\))",
      r"\1DEFAULT_CONFIG\2",
      updated,
      count=1,
    )
    updated = updated.replace("config={config}", "config={config || DEFAULT_CONFIG}")

  fallback_labels = {
    "config": "Worktual AI",
    "setupData": "Worktual AI",
    "workspace": "Workspace",
    "project": "Project",
    "company": "Company",
    "account": "Account",
    "profile": "Profile",
    "customer": "Customer",
    "user": "User",
    "item": "Untitled",
  }
  for identifier, fallback in fallback_labels.items():
    updated = re.sub(rf"\b{re.escape(identifier)}\.name\b", f'({identifier}?.name || "{fallback}")', updated)
  return updated


UNDEFINED_REFERENCE_PATTERNS = (
  re.compile(r"\bReferenceError:\s*([A-Za-z_$][\w$]*)", re.IGNORECASE),
  re.compile(r"\b([A-Za-z_$][\w$]*)\s+is\s+not\s+defined\b", re.IGNORECASE),
)
UNDEFINED_REFERENCE_SKIP_NAMES = {"react", "undefined", "null", "window", "document", "console", "module", "exports"}
JS_IDENTIFIER_NAME_PATTERN = re.compile(r"^[A-Za-z_$][\w$]*$")


def extract_undefined_reference_names(prompt: str, update_analysis: dict[str, Any]) -> list[str]:
  text = scoped_update_request_text(prompt, update_analysis)
  names: list[str] = []
  seen: set[str] = set()
  for pattern in UNDEFINED_REFERENCE_PATTERNS:
    for match in pattern.finditer(text):
      name = text_or_default(match.group(1), "")
      if not name or name.lower() in UNDEFINED_REFERENCE_SKIP_NAMES or name in seen:
        continue
      seen.add(name)
      names.append(name)
  for symbol in string_list(update_analysis.get("target_symbols"), []):
    if (
      not symbol
      or symbol.lower() in UNDEFINED_REFERENCE_SKIP_NAMES
      or symbol in seen
      or not JS_IDENTIFIER_NAME_PATTERN.match(symbol)
    ):
      continue
    seen.add(symbol)
    names.append(symbol)
  return names[:4]


JSX_CONDITIONAL_GUARD_RE = re.compile(r"\{\s*([A-Za-z_$][\w$]*)\s*&&")


def infer_undeclared_jsx_conditional_identifiers(content: str) -> list[str]:
  names: list[str] = []
  seen: set[str] = set()
  for match in JSX_CONDITIONAL_GUARD_RE.finditer(content):
    name = text_or_default(match.group(1), "")
    if not name or name.lower() in UNDEFINED_REFERENCE_SKIP_NAMES or name in seen:
      continue
    if identifier_is_declared_in_content(content, name):
      continue
    seen.add(name)
    names.append(name)
  return names[:4]


def identifier_is_declared_in_content(content: str, identifier: str) -> bool:
  patterns = (
    rf"\b(?:const|let|var|function)\s+{re.escape(identifier)}\b",
    rf"\b(?:const|let|var)\s+\[[^\]]*\b{re.escape(identifier)}\b",
    rf"import\s+.+\b{re.escape(identifier)}\b",
    rf"\bfunction\s+{re.escape(identifier)}\s*\(",
  )
  return any(re.search(pattern, content) for pattern in patterns)


def _remove_braced_expression_block(content: str, *, start_index: int) -> str:
  depth = 0
  for idx in range(start_index, len(content)):
    char = content[idx]
    if char == "{":
      depth += 1
    elif char == "}":
      depth -= 1
      if depth == 0:
        return content[:start_index] + content[idx + 1 :]
  return content


def remove_undeclared_identifier_usage(content: str, identifier: str) -> str:
  if identifier_is_declared_in_content(content, identifier):
    return content

  updated = content
  search_from = 0
  while search_from < len(updated):
    match = re.search(rf"\{{\s*{re.escape(identifier)}\s*&&", updated[search_from:])
    if not match:
      break
    start = search_from + match.start()
    updated = _remove_braced_expression_block(updated, start_index=start)
    search_from = start

  search_from = 0
  while search_from < len(updated):
    match = re.search(rf"\{{\s*{re.escape(identifier)}\s*\?", updated[search_from:])
    if not match:
      break
    start = search_from + match.start()
    updated = _remove_braced_expression_block(updated, start_index=start)
    search_from = start

  setter = f"set{identifier[0].upper()}{identifier[1:]}" if identifier else ""
  if setter:
    updated = re.sub(rf"^\s*{re.escape(setter)}\([^)]*\);\s*$", "", updated, flags=re.MULTILINE)

  cleaned_lines: list[str] = []
  for line in updated.splitlines():
    if identifier not in line or identifier_is_declared_in_content(line, identifier):
      cleaned_lines.append(line)
      continue
    if re.search(rf"\b{re.escape(identifier)}\b", line):
      continue
    cleaned_lines.append(line)
  updated = "\n".join(cleaned_lines)
  updated = re.sub(r"\n{3,}", "\n\n", updated)
  return updated


def deterministic_undefined_reference_fix_code(*, path: str, content: str, identifiers: list[str]) -> str:
  if not path.endswith((".jsx", ".tsx", ".js", ".ts")):
    return content
  updated = content
  for identifier in identifiers:
    updated = remove_undeclared_identifier_usage(updated, identifier)
  return updated


def deterministic_undefined_reference_fix_changes(
  *,
  prompt: str,
  update_analysis: dict[str, Any],
  existing_files: list[dict[str, str]],
) -> list[dict[str, str]]:
  if text_or_default(update_analysis.get("request_kind"), "") == "interaction_wiring_update":
    return []
  identifiers = extract_undefined_reference_names(prompt, update_analysis)
  candidate_paths = set(string_list(update_analysis.get("candidate_files"), []))
  if not candidate_paths:
    return []

  if not identifiers and text_or_default(update_analysis.get("update_mode"), "") == "bug_fix":
    for file_item in existing_files:
      path = text_or_default(file_item.get("path"), "")
      content = text_or_default(file_item.get("content"), "")
      if path not in candidate_paths:
        continue
      for name in infer_undeclared_jsx_conditional_identifiers(content):
        if name not in identifiers:
          identifiers.append(name)
      if len(identifiers) >= 4:
        break
  if not identifiers:
    return []

  for file_item in existing_files:
    path = text_or_default(file_item.get("path"), "")
    content = text_or_default(file_item.get("content"), "")
    if path not in candidate_paths:
      continue
    updated = deterministic_undefined_reference_fix_code(path=path, content=content, identifiers=identifiers)
    normalized = normalize_generated_file_code(path, updated) if updated.strip() else ""
    if normalized and scoped_update_has_effective_change(path, content, normalized):
      return [{"path": path, "content": normalized}]
  return []


def ensure_default_config_declaration(content: str) -> str:
  if "DEFAULT_CONFIG" in content:
    return content
  declaration = 'const DEFAULT_CONFIG = { name: "Worktual AI", companyName: "Worktual AI" };\n\n'
  import_matches = list(re.finditer(r"^import .+?;\s*$", content, flags=re.MULTILINE))
  if not import_matches:
    return declaration + content
  insert_at = import_matches[-1].end()
  return content[:insert_at] + "\n\n" + declaration + content[insert_at:].lstrip("\n")


def scoped_update_request_text(prompt: str, update_analysis: dict[str, Any]) -> str:
  feature_plan = object_value(update_analysis.get("feature_plan"))
  diagnosis = object_value(update_analysis.get("error_diagnosis"))
  parts = [
    prompt,
    text_or_default(update_analysis.get("summary"), ""),
    " ".join(string_list(update_analysis.get("target_symbols"), [])),
    text_or_default(feature_plan.get("name"), ""),
    " ".join(string_list(feature_plan.get("items"), [])),
    text_or_default(feature_plan.get("interaction"), ""),
    " ".join(string_list(diagnosis.get("root_cause_hints"), [])),
    " ".join(string_list(diagnosis.get("categories"), [])),
    " ".join(string_list(diagnosis.get("mentioned_paths"), [])),
  ]
  return " ".join(part for part in parts if part)


def deterministic_onboarding_chat_component_code(path: str) -> str:
  extension = path.rsplit(".", 1)[-1]
  type_suffix = "" if extension == "jsx" else ": Record<string, string>"
  return (
    'import React, { useMemo, useState } from "react";\n\n'
    "const onboardingSteps = [\n"
    "  {\n"
    '    id: "company",\n'
    '    label: "Company basics",\n'
    '    prompt: "Tell me the company name, industry, and the team size.",\n'
    '    helper: "This sets the context for the workspace.",\n'
    '    placeholder: "Worktual, SaaS, 50 people",\n'
    "  },\n"
    "  {\n"
    '    id: "goals",\n'
    '    label: "Primary goals",\n'
    '    prompt: "What should this workspace help your team accomplish first?",\n'
    '    helper: "Focus on the first measurable business outcome.",\n'
    '    placeholder: "Improve lead follow-up speed",\n'
    "  },\n"
    "  {\n"
    '    id: "channels",\n'
    '    label: "Channels",\n'
    '    prompt: "Which customer channels should the AI assistant connect with?",\n'
    '    helper: "Mention web chat, WhatsApp, email, calls, or CRM data.",\n'
    '    placeholder: "Website chat and CRM contacts",\n'
    "  },\n"
    "  {\n"
    '    id: "automation",\n'
    '    label: "Automation style",\n'
    '    prompt: "How proactive should the AI be during onboarding and follow-up?",\n'
    '    helper: "Choose a light assistant or a more automated workflow.",\n'
    '    placeholder: "Suggest next steps but ask before sending",\n'
    "  },\n"
    "  {\n"
    '    id: "review",\n'
    '    label: "Review and launch",\n'
    '    prompt: "Add any approval rules, owner names, or launch notes.",\n'
    '    helper: "The final answer is passed into the project setup.",\n'
    '    placeholder: "Manager approval before customer messages",\n'
    "  },\n"
    "];\n\n"
    "export default function OnboardingWizard({ onComplete = () => {} }) {\n"
    "  const [activeStep, setActiveStep] = useState(0);\n"
    f"  const [answers, setAnswers] = useState({{}}{type_suffix});\n"
    "  const currentStep = onboardingSteps[activeStep];\n"
    "  const progress = Math.round(((activeStep + 1) / onboardingSteps.length) * 100);\n"
    "  const transcript = useMemo(\n"
    "    () => onboardingSteps.slice(0, activeStep + 1).map((step) => ({\n"
    "      ...step,\n"
    '      answer: answers[step.id] || "",\n'
    "    })),\n"
    "    [activeStep, answers],\n"
    "  );\n\n"
    "  const updateAnswer = (value) => {\n"
    "    setAnswers((current) => ({ ...current, [currentStep.id]: value }));\n"
    "  };\n\n"
    "  const goNext = () => {\n"
    "    if (activeStep < onboardingSteps.length - 1) {\n"
    "      setActiveStep((step) => step + 1);\n"
    "      return;\n"
    "    }\n"
    "    onComplete({\n"
    "      answers,\n"
    "      completedSteps: onboardingSteps.length,\n"
    "      completedAt: new Date().toISOString(),\n"
    "    });\n"
    "  };\n\n"
    "  return (\n"
    '    <section className="min-h-[720px] bg-[var(--page-bg)] px-4 py-8 text-[var(--page-text)] sm:px-6 lg:px-8">\n'
    '      <div className="mx-auto grid max-w-6xl gap-6 lg:grid-cols-[0.9fr_1.1fr]">\n'
    '        <aside className="rounded-2xl border border-[var(--border-color)] bg-[var(--card-bg)] p-6 shadow-2xl">\n'
    '          <p className="text-sm font-semibold uppercase tracking-[0.18em] text-[var(--accent-color)]">AI onboarding</p>\n'
    '          <h1 className="mt-3 text-3xl font-bold tracking-tight">5-step conversational setup</h1>\n'
    '          <p className="mt-3 text-sm leading-6 text-[var(--muted-text)]">\n'
    "            Guide the user through setup as a focused chat instead of a traditional long form.\n"
    "          </p>\n"
    '          <div className="mt-6 h-2 overflow-hidden rounded-full bg-[var(--track-bg)]">\n'
    '            <div className="h-full rounded-full bg-[var(--accent-color)] transition-all" style={{ width: `${progress}%` }} />\n'
    "          </div>\n"
    '          <p className="mt-3 text-sm text-[var(--muted-text)]">{progress}% complete</p>\n'
    '          <div className="mt-6 space-y-3">\n'
    "            {onboardingSteps.map((step, index) => (\n"
    "              <button\n"
    "                key={step.id}\n"
    '                type="button"\n'
    "                onClick={() => setActiveStep(index)}\n"
    '                className={`w-full rounded-xl border px-4 py-3 text-left transition ${\n'
    "                  index === activeStep\n"
    '                    ? "border-[var(--accent-color)] bg-[var(--accent-soft)] text-[var(--page-text)]"\n'
    '                    : "border-[var(--border-color)] bg-[var(--card-bg)] text-[var(--muted-text)] hover:border-[var(--accent-color)]"\n'
    "                }`}\n"
    "              >\n"
    '                <span className="text-xs font-semibold uppercase text-[var(--muted-text)]">Step {index + 1}</span>\n'
    '                <span className="mt-1 block font-semibold">{step.label}</span>\n'
    "              </button>\n"
    "            ))}\n"
    "          </div>\n"
    "        </aside>\n\n"
    '        <div className="rounded-2xl border border-[var(--border-color)] bg-[var(--card-bg)] p-4 shadow-2xl sm:p-6">\n'
    '          <div className="flex items-center justify-between border-b border-[var(--border-color)] pb-4">\n'
    "            <div>\n"
    '              <p className="text-sm font-semibold text-[var(--accent-color)]">Vibe AI</p>\n'
    '              <h2 className="text-xl font-bold">Conversational onboarding chat</h2>\n'
    "            </div>\n"
    '            <span className="rounded-full bg-[var(--accent-soft)] px-3 py-1 text-xs font-semibold text-[var(--accent-color)]">Live</span>\n'
    "          </div>\n\n"
    '          <div className="mt-6 space-y-5">\n'
    "            {transcript.map((step, index) => (\n"
    '              <div key={step.id} className="space-y-3">\n'
    '                <div className="max-w-[88%] rounded-2xl rounded-tl-sm bg-[var(--assistant-bubble-bg)] px-4 py-3">\n'
    '                  <p className="text-sm font-semibold text-[var(--accent-color)]">AI Assistant · Step {index + 1}</p>\n'
    '                  <p className="mt-1 text-sm leading-6">{step.prompt}</p>\n'
    '                  <p className="mt-2 text-xs text-[var(--muted-text)]">{step.helper}</p>\n'
    "                </div>\n"
    "                {step.answer && (\n"
    '                  <div className="ml-auto max-w-[88%] rounded-2xl rounded-tr-sm bg-[var(--accent-color)] px-4 py-3 text-[var(--accent-text)]">\n'
    '                    <p className="text-xs font-semibold uppercase opacity-80">You</p>\n'
    '                    <p className="mt-1 text-sm leading-6">{step.answer}</p>\n'
    "                  </div>\n"
    "                )}\n"
    "              </div>\n"
    "            ))}\n"
    "          </div>\n\n"
    '          <div className="mt-6 rounded-2xl border border-[var(--border-color)] bg-[var(--panel-bg)] p-4">\n'
    '            <label className="text-sm font-semibold" htmlFor="onboarding-answer">\n'
    "              {currentStep.label}\n"
    "            </label>\n"
    "            <textarea\n"
    '              id="onboarding-answer"\n'
    '              className="mt-3 min-h-28 w-full resize-none rounded-xl border border-[var(--border-color)] bg-[var(--input-bg)] px-4 py-3 text-sm outline-none transition placeholder:text-[var(--muted-text)] focus:border-[var(--accent-color)]"\n'
    "              value={answers[currentStep.id] || \"\"}\n"
    "              onChange={(event) => updateAnswer(event.target.value)}\n"
    "              placeholder={currentStep.placeholder}\n"
    "            />\n"
    '            <div className="mt-4 flex flex-wrap items-center justify-between gap-3">\n'
    "              <button\n"
    '                type="button"\n'
    "                onClick={() => setActiveStep((step) => Math.max(0, step - 1))}\n"
    "                disabled={activeStep === 0}\n"
    '                className="rounded-xl border border-[var(--border-color)] px-4 py-2 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-40"\n'
    "              >\n"
    "                Back\n"
    "              </button>\n"
    '              <div className="flex gap-3">\n'
    "                <button\n"
    '                  type="button"\n'
    "                  onClick={goNext}\n"
    '                  className="rounded-xl bg-[var(--accent-color)] px-5 py-2 text-sm font-bold text-[var(--accent-text)] shadow-lg hover:opacity-90"\n'
    "                >\n"
    "                  {activeStep === onboardingSteps.length - 1 ? \"Complete setup\" : \"Next step\"}\n"
    "                </button>\n"
    "              </div>\n"
    "            </div>\n"
    "          </div>\n"
    "        </div>\n"
    "      </div>\n"
    "    </section>\n"
    "  );\n"
    "}\n"
  )


def deterministic_interaction_modal_fix_changes(
  *,
  prompt: str,
  update_analysis: dict[str, Any],
  existing_files: list[dict[str, str]],
) -> list[dict[str, str]]:
  lowered_prompt = prompt.lower()
  if not any(term in lowered_prompt for term in ("button", "click", "modal", "not working", "no modal")):
    return []

  candidate_paths = set(string_list(update_analysis.get("candidate_files"), []))
  if not candidate_paths:
    return []
  if "new project" in lowered_prompt:
    for file_item in existing_files:
      path = text_or_default(file_item.get("path"), "")
      if path not in candidate_paths or not path.endswith((".jsx", ".tsx")):
        continue
      content = text_or_default(file_item.get("content"), "")
      updated = deterministic_new_project_modal_fix_code(content)
      if updated and updated != content:
        return [{"path": path, "content": updated}]
    return []

  if not any(term in lowered_prompt for term in ("modal", "popup", "pop up", "dialog")):
    return []
  contract = interaction_contract_from_update_analysis(update_analysis)
  if not interaction_contract_active(update_analysis, contract):
    contract = {
      "component": modal_button_hint_from_prompt(prompt),
      "trigger": "click",
      "expected": "open modal",
      "source_page": "",
      "target_page_or_route": "",
      "confidence": 0.6,
    }
  if not text_or_default(contract.get("component"), ""):
    contract["component"] = modal_button_hint_from_prompt(prompt)

  existing_by_path = {
    text_or_default(file_item.get("path"), ""): text_or_default(file_item.get("content"), "")
    for file_item in existing_files
    if isinstance(file_item, dict) and text_or_default(file_item.get("path"), "")
  }
  source_path, button_match = select_modal_source_button(
    contract=contract,
    prompt=prompt,
    existing_by_path=existing_by_path,
    candidate_paths={path for path in candidate_paths if path in existing_by_path},
  )
  if not source_path or button_match is None:
    return []
  content = existing_by_path[source_path]
  updated = wire_button_to_modal(
    source_path=source_path,
    content=content,
    button_match=button_match,
    prompt=prompt,
    contract=contract,
  )
  if not updated or not scoped_update_has_effective_change(source_path, content, updated):
    return []
  return [{"path": source_path, "content": normalize_generated_file_code(source_path, updated)}]


def modal_button_hint_from_prompt(prompt: str) -> str:
  text = text_or_default(prompt, "")
  patterns = (
    r"\b(create\s+action\s+plan)\b",
    r"\b(new\s+project)\b",
    r"\b([A-Za-z][A-Za-z0-9 &/-]{2,60}?)\s+button\b",
  )
  for pattern in patterns:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if match:
      return re.sub(r"\s+", " ", match.group(1)).strip()
  return ""


def select_modal_source_button(
  *,
  contract: dict[str, Any],
  prompt: str,
  existing_by_path: dict[str, str],
  candidate_paths: set[str],
) -> tuple[str, re.Match[str] | None]:
  best: tuple[int, str, re.Match[str]] | None = None
  prompt_tokens = text_tokens(prompt)
  for path in sorted(candidate_paths):
    if not path.endswith((".jsx", ".tsx")):
      continue
    content = existing_by_path.get(path, "")
    for match in JSX_BUTTON_BLOCK_RE.finditer(content):
      attrs = text_or_default(match.group("attrs"), "")
      body = visible_jsx_text(match.group("body"))
      score = score_interaction_button(path, match, contract)
      score += len(text_tokens(body) & prompt_tokens) * 160
      if re.search(r"\bonClick\s*=", attrs):
        score += 80
      if any(term in attrs.lower() for term in ("alert", "toast", "notify")):
        score += 180
      if score <= 0:
        continue
      candidate = (score, path, match)
      if best is None or candidate[0] > best[0]:
        best = candidate
  if best is not None:
    return best[1], best[2]
  return "", None


def wire_button_to_modal(
  *,
  source_path: str,
  content: str,
  button_match: re.Match[str],
  prompt: str,
  contract: dict[str, Any],
) -> str:
  button_label = visible_jsx_text(button_match.group("body")) or modal_button_hint_from_prompt(prompt) or "Action"
  state_base = modal_state_base(button_label)
  state_name = f"show{state_base}Modal"
  setter_name = f"setShow{state_base}Modal"
  updated = ensure_react_use_state_import(content)
  if state_name not in updated:
    component_match = re.search(
      r"(?P<decl>(?:export\s+default\s+)?(?:function|const)\s+[A-Z][A-Za-z0-9_]*\s*(?:=\s*\([^)]*\)\s*=>|\([^)]*\))\s*\{)",
      updated,
    )
    if not component_match:
      return ""
    updated = updated[: component_match.end()] + f"\n  const [{state_name}, {setter_name}] = useState(false);" + updated[component_match.end() :]

  button_block = button_match.group(0)
  relocated_start = updated.find(button_block)
  if relocated_start < 0:
    return ""
  button_start = relocated_start
  button_end = relocated_start + len(button_block)
  opening_match = JSX_BUTTON_OPENING_RE.match(button_block)
  if not opening_match:
    return ""
  opening = opening_match.group(0)
  previous_handler = button_onclick_handler_name(opening)
  replacement_opening = set_button_modal_onclick(opening, setter_name)
  updated_button = replacement_opening + button_block[opening_match.end() :]
  updated = updated[:button_start] + updated_button + updated[button_end:]
  if previous_handler:
    updated = remove_unused_popup_handler(updated, previous_handler)

  if state_name not in updated[button_start + len(updated_button) :]:
    title = modal_title_from_context(button_label, prompt, contract)
    modal_markup = generic_modal_markup(
      state_name=state_name,
      setter_name=setter_name,
      title=title,
      description=modal_description_from_context(title),
    )
    updated = insert_jsx_before_last_root_close(updated, modal_markup)
  return updated


def modal_state_base(label: str) -> str:
  words = re.findall(r"[A-Za-z0-9]+", text_or_default(label, "Action"))
  selected = [word for word in words if word.lower() not in {"button", "the", "a", "an"}][:5]
  if not selected:
    selected = ["Action"]
  return "".join(word[:1].upper() + word[1:] for word in selected)


def set_button_modal_onclick(opening: str, setter_name: str) -> str:
  onclick = f"onClick={{() => {setter_name}(true)}}"
  if re.search(r"\sonClick\s*=", opening):
    return re.sub(r"\s+onClick\s*=\s*(?:\{[^}]*\}|['\"][^'\"]*['\"])", f" {onclick}", opening, count=1)
  return opening[:-1].rstrip() + f" {onclick}>"


def button_onclick_handler_name(opening: str) -> str:
  match = re.search(r"\sonClick\s*=\s*\{\s*([A-Za-z_$][A-Za-z0-9_$]*)\s*\}", text_or_default(opening, ""))
  return match.group(1) if match else ""


def remove_unused_popup_handler(content: str, handler_name: str) -> str:
  if not handler_name or content.count(handler_name) != 1:
    return content
  pattern = re.compile(
    rf"\n(?P<indent>[ \t]*)(?:const|let|var)\s+{re.escape(handler_name)}\s*=\s*"
    r"(?:\([^)]*\)|[A-Za-z_$][A-Za-z0-9_$]*)?\s*=>\s*\{(?P<body>[\s\S]{0,700}?)\}\s*;\n?",
    flags=re.MULTILINE,
  )

  def replace_if_popup(match: re.Match[str]) -> str:
    body = match.group("body").lower()
    if any(term in body for term in ("alert(", "toast", "notify", "notification")):
      return "\n"
    return match.group(0)

  return pattern.sub(replace_if_popup, content, count=1)


def modal_title_from_context(button_label: str, prompt: str, contract: dict[str, Any]) -> str:
  component = text_or_default(contract.get("component"), "") or modal_button_hint_from_prompt(prompt)
  label = component or button_label or "Action"
  cleaned = re.sub(r"\bbutton\b", "", label, flags=re.IGNORECASE)
  cleaned = re.sub(r"\s+", " ", cleaned).strip()
  return " ".join(word[:1].upper() + word[1:] for word in cleaned.split()) or "Action Details"


def modal_description_from_context(title: str) -> str:
  return f"Review and continue with the {title.lower()} workflow from this page."


def generic_modal_markup(*, state_name: str, setter_name: str, title: str, description: str) -> str:
  safe_title = title.replace("{", "").replace("}", "")
  safe_description = description.replace("{", "").replace("}", "")
  return (
    f"\n      {{{state_name} && (\n"
    "        <div className=\"fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4\">\n"
    "          <div className=\"w-full max-w-lg rounded-2xl border border-slate-700 bg-slate-950 p-6 text-white shadow-2xl\">\n"
    "            <div className=\"flex items-start justify-between gap-4\">\n"
    "              <div>\n"
    f"                <h2 className=\"text-xl font-bold\">{safe_title}</h2>\n"
    f"                <p className=\"mt-2 text-sm text-slate-300\">{safe_description}</p>\n"
    "              </div>\n"
    "              <button\n"
    "                type=\"button\"\n"
    f"                onClick={{() => {setter_name}(false)}}\n"
    "                className=\"rounded-lg border border-slate-700 px-3 py-1 text-sm font-semibold text-slate-200 hover:bg-slate-800\"\n"
    "              >\n"
    "                Close\n"
    "              </button>\n"
    "            </div>\n"
    "            <div className=\"mt-5 rounded-xl border border-slate-800 bg-slate-900/80 p-4 text-sm text-slate-200\">\n"
    "              The requested action is ready to continue from this modal instead of a browser popup.\n"
    "            </div>\n"
    "          </div>\n"
    "        </div>\n"
    "      )}\n"
  )


def deterministic_navigation_interaction_fix_changes(
  *,
  prompt: str,
  update_analysis: dict[str, Any],
  existing_files: list[dict[str, str]],
) -> list[dict[str, str]]:
  """Bounded recovery for no-patch navigation interaction failures.

  This is intentionally not a router. It only runs after the scoped model
  returned no usable patch, and it only edits an approved candidate file when
  actual anchors exist: a matching JSX button/control and an existing route.
  """
  contract = interaction_contract_from_update_analysis(update_analysis)
  if not interaction_contract_active(update_analysis, contract):
    return []

  existing_by_path = {
    text_or_default(file_item.get("path"), ""): text_or_default(file_item.get("content"), "")
    for file_item in existing_files
    if isinstance(file_item, dict) and text_or_default(file_item.get("path"), "")
  }
  candidate_paths = {
    path
    for path in string_list(update_analysis.get("candidate_files"), [])
    if path in existing_by_path
  }
  if not existing_by_path or not candidate_paths:
    return []

  target_hint = navigation_target_hint_from_contract(contract)
  if not target_hint:
    return []
  target_route = resolve_existing_navigation_route(target_hint, existing_by_path)
  if not target_route:
    return []

  source_path, button_match = select_navigation_source_button(
    contract=contract,
    existing_by_path=existing_by_path,
    candidate_paths=candidate_paths,
  )
  if not source_path or button_match is None:
    return []

  content = existing_by_path[source_path]
  updated = wire_button_to_navigation_route(
    source_path=source_path,
    content=content,
    button_match=button_match,
    target_route=target_route,
    existing_paths=set(existing_by_path),
  )
  if not updated or not scoped_update_has_effective_change(source_path, content, updated):
    return []
  return [{"path": source_path, "content": normalize_generated_file_code(source_path, updated)}]


def interaction_contract_from_update_analysis(update_analysis: dict[str, Any]) -> dict[str, Any]:
  interaction = object_value(update_analysis.get("interaction"))
  feature_plan = object_value(update_analysis.get("feature_plan"))
  return {
    "component": text_or_default(
      interaction.get("component")
      or interaction.get("element")
      or interaction.get("name")
      or feature_plan.get("name"),
      "",
    ),
    "trigger": text_or_default(interaction.get("trigger") or interaction.get("action"), ""),
    "expected": text_or_default(
      interaction.get("expected")
      or interaction.get("behavior")
      or interaction.get("outcome")
      or feature_plan.get("interaction")
      or update_analysis.get("interaction_summary"),
      "",
    ),
    "source_page": text_or_default(
      interaction.get("source_page")
      or interaction.get("source")
      or interaction.get("source_component")
      or interaction.get("from_page"),
      "",
    ),
    "target_page_or_route": text_or_default(
      interaction.get("target_page_or_route")
      or interaction.get("target_route")
      or interaction.get("target_page")
      or interaction.get("destination")
      or interaction.get("to_page"),
      "",
    ),
    "confidence": interaction.get("confidence", 0.0),
  }


def interaction_contract_active(update_analysis: dict[str, Any], contract: dict[str, Any]) -> bool:
  request_kind = text_or_default(update_analysis.get("request_kind"), "").lower()
  profile = text_or_default(update_analysis.get("enrichment_profile"), "").lower()
  if request_kind != "interaction_wiring_update" and profile != "interaction_wiring":
    return False
  return any(
    text_or_default(contract.get(key), "")
    for key in ("component", "trigger", "expected", "source_page", "target_page_or_route")
  )


def navigation_target_hint_from_contract(contract: dict[str, Any]) -> str:
  explicit = text_or_default(contract.get("target_page_or_route"), "")
  if explicit:
    return explicit
  expected = text_or_default(contract.get("expected"), "")
  if not expected:
    return ""
  route_match = re.search(r"(#[/][A-Za-z0-9_./-]+|/[A-Za-z0-9_./-]+)", expected)
  if route_match:
    return route_match.group(1)
  behavior_match = re.search(
    r"(?:navigate|redirect|open|show|display|land|go)\s+(?:the\s+user\s+)?(?:to|on|into)?\s*(?:the\s+)?([A-Za-z][A-Za-z0-9 _&/-]{1,80}?)(?:\s+(?:page|screen|route|module|flow))?(?:[.,;]|$)",
    expected,
    flags=re.IGNORECASE,
  )
  if behavior_match:
    return behavior_match.group(1).strip()
  return ""


def resolve_existing_navigation_route(target_hint: str, existing_by_path: dict[str, str]) -> str:
  normalized_hint = normalize_route_hint(target_hint)
  route_records = collect_existing_route_records(existing_by_path)
  if not route_records:
    return ""
  hint_tokens = text_tokens(target_hint)
  best_score = 0
  best_route = ""
  for route, context in route_records:
    normalized_route = normalize_route_hint(route)
    route_tokens = text_tokens(f"{route} {context}")
    score = 0
    if normalized_hint and normalized_route == normalized_hint:
      score += 1000
    if normalized_hint and normalized_route.strip("/") == normalized_hint.strip("/"):
      score += 900
    score += len(hint_tokens & route_tokens) * 140
    if score > best_score:
      best_score = score
      best_route = route
  return normalize_route_for_navigate(best_route) if best_score > 0 else ""


def collect_existing_route_records(existing_by_path: dict[str, str]) -> list[tuple[str, str]]:
  records: list[tuple[str, str]] = []
  route_pattern = re.compile(
    r"(?:<Route\b[^>]*\bpath\s*=\s*['\"](?P<route_path>[^'\"]+)['\"][^>]*>|"
    r"\bto\s*=\s*['\"](?P<link_path>/[^'\"]+)['\"]|"
    r"\bnavigate\s*\(\s*['\"](?P<navigate_path>/[^'\"]+)['\"])",
    flags=re.IGNORECASE | re.DOTALL,
  )
  for path, content in existing_by_path.items():
    if not path.endswith((".jsx", ".tsx", ".js", ".ts")):
      continue
    for match in route_pattern.finditer(content):
      route = text_or_default(
        match.group("route_path")
        or match.group("link_path")
        or match.group("navigate_path"),
        "",
      )
      if not route or route.startswith("http"):
        continue
      start = max(0, match.start() - 280)
      end = min(len(content), match.end() + 360)
      records.append((route, f"{path}\n{content[start:end]}"))
  return records


def normalize_route_hint(value: str) -> str:
  raw = text_or_default(value, "").strip().lower()
  if not raw:
    return ""
  if raw.startswith("#/"):
    raw = raw[1:]
  if raw.startswith("/"):
    return "/" + raw.strip("/").replace(" ", "-")
  raw = re.sub(r"\b(page|screen|route|module|flow)\b", "", raw)
  raw = re.sub(r"[^a-z0-9/ -]+", " ", raw)
  raw = re.sub(r"\s+", "-", raw.strip())
  return f"/{raw}" if raw else ""


def normalize_route_for_navigate(route: str) -> str:
  cleaned = text_or_default(route, "").strip()
  if cleaned.startswith("#/"):
    cleaned = cleaned[1:]
  if not cleaned.startswith("/"):
    cleaned = f"/{cleaned.strip('/')}"
  return cleaned or "/"


def select_navigation_source_button(
  *,
  contract: dict[str, Any],
  existing_by_path: dict[str, str],
  candidate_paths: set[str],
) -> tuple[str, re.Match[str] | None]:
  best: tuple[int, str, re.Match[str]] | None = None
  for path in sorted(candidate_paths):
    if not path.endswith((".jsx", ".tsx")):
      continue
    content = existing_by_path.get(path, "")
    for match in JSX_BUTTON_BLOCK_RE.finditer(content):
      score = score_interaction_button(path, match, contract)
      if score <= 0:
        continue
      candidate = (score, path, match)
      if best is None or candidate[0] > best[0]:
        best = candidate
  if best is not None:
    return best[1], best[2]
  return "", None


JSX_BRACED_ATTR_PATTERN = r"\{(?:[^{}]|\{[^{}]*\})*\}"
JSX_BUTTON_ATTR_PATTERN = rf"(?:[^>{{}}]|{JSX_BRACED_ATTR_PATTERN})*"
JSX_BUTTON_BLOCK_RE = re.compile(
  rf"<button\b(?P<attrs>{JSX_BUTTON_ATTR_PATTERN})>(?P<body>[\s\S]{{0,1600}}?)</button>",
  re.IGNORECASE,
)
JSX_BUTTON_OPENING_RE = re.compile(
  rf"<button\b{JSX_BUTTON_ATTR_PATTERN}>",
  re.IGNORECASE | re.DOTALL,
)


def score_interaction_button(path: str, button_match: re.Match[str], contract: dict[str, Any]) -> int:
  attrs = text_or_default(button_match.group("attrs"), "")
  body = visible_jsx_text(button_match.group("body"))
  component = text_or_default(contract.get("component"), "")
  expected = text_or_default(contract.get("expected"), "")
  source_page = text_or_default(contract.get("source_page"), "")
  target = text_or_default(contract.get("target_page_or_route"), "")
  label_tokens = text_tokens(component)
  body_tokens = text_tokens(body)
  context_tokens = text_tokens(f"{path} {source_page} {expected} {target}")
  score = 0
  normalized_body = normalize_visible_text(body)
  normalized_component = normalize_visible_text(component)
  if normalized_component and normalized_component in normalized_body:
    score += 1200
  score += len(label_tokens & body_tokens) * 180
  score += len(body_tokens & context_tokens) * 35
  if source_page and text_tokens(source_page) & text_tokens(path):
    score += 220
  if "onclick" not in attrs.lower():
    score += 120
  if len(body_tokens) == 0:
    score -= 120
  return score


def visible_jsx_text(value: str) -> str:
  without_tags = re.sub(r"<[^>]+>", " ", value)
  without_expressions = re.sub(r"\{[^}]*\}", " ", without_tags)
  return re.sub(r"\s+", " ", without_expressions).strip()


def normalize_visible_text(value: str) -> str:
  return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text_or_default(value, "").lower())).strip()


def text_tokens(value: str) -> set[str]:
  return {
    token
    for token in re.findall(r"[a-z0-9]+", text_or_default(value, "").lower())
    if len(token) >= 3
  }


def wire_button_to_navigation_route(
  *,
  source_path: str,
  content: str,
  button_match: re.Match[str],
  target_route: str,
  existing_paths: set[str],
) -> str:
  updated = ensure_use_navigate_import(source_path=source_path, content=content, existing_paths=existing_paths)
  updated = ensure_navigate_hook(updated)
  button_block = button_match.group(0)
  if updated != content:
    relocated_start = updated.find(button_block)
    if relocated_start < 0:
      return ""
    button_start = relocated_start
    button_end = relocated_start + len(button_block)
  else:
    button_start = button_match.start()
    button_end = button_match.end()
  opening_match = JSX_BUTTON_OPENING_RE.match(button_block)
  if not opening_match:
    return ""
  opening = opening_match.group(0)
  replacement_opening = set_button_onclick(opening, target_route)
  if replacement_opening == opening:
    return ""
  updated_button = replacement_opening + button_block[opening_match.end() :]
  return updated[:button_start] + updated_button + updated[button_end:]


def ensure_use_navigate_import(*, source_path: str, content: str, existing_paths: set[str]) -> str:
  if re.search(r"import\s+\{[^}]*\buseNavigate\b[^}]*\}\s+from\s+['\"][^'\"]+['\"]", content):
    return content
  for module in ("./worktual-router-shim.jsx", "../worktual-router-shim.jsx", "react-router-dom"):
    pattern = re.compile(
      rf"import\s+\{{(?P<imports>[^}}]*)\}}\s+from\s+['\"](?P<module>{re.escape(module)})['\"];",
      flags=re.MULTILINE,
    )
    match = pattern.search(content)
    if match:
      imports = append_named_import(match.group("imports"), "useNavigate")
      return content[: match.start()] + f"import {{ {imports} }} from '{match.group('module')}';" + content[match.end() :]
  shim_path = "src/worktual-router-shim.jsx" if "src/worktual-router-shim.jsx" in existing_paths else ""
  module_path = relative_import_path(source_path, shim_path) if shim_path else "react-router-dom"
  import_line = f"import {{ useNavigate }} from '{module_path}';\n"
  import_matches = list(re.finditer(r"^import .+?;\s*$", content, flags=re.MULTILINE))
  if not import_matches:
    return import_line + content
  insert_at = import_matches[-1].end()
  return content[:insert_at] + "\n" + import_line + content[insert_at:].lstrip("\n")


def relative_import_path(source_path: str, target_path: str) -> str:
  if not target_path:
    return "react-router-dom"
  source_dir = posixpath.dirname(source_path) or "."
  relative = posixpath.relpath(target_path, source_dir)
  if not relative.startswith("."):
    relative = f"./{relative}"
  return relative


def ensure_navigate_hook(content: str) -> str:
  if re.search(r"\b(?:const|let|var)\s+navigate\s*=\s*useNavigate\s*\(", content):
    return content
  component_match = re.search(
    r"(?P<decl>(?:export\s+default\s+)?function\s+[A-Z][A-Za-z0-9_]*\s*\([^)]*\)\s*\{)",
    content,
  )
  if component_match:
    return content[: component_match.end()] + "\n  const navigate = useNavigate();" + content[component_match.end() :]
  component_match = re.search(
    r"(?P<decl>(?:export\s+)?const\s+[A-Z][A-Za-z0-9_]*\s*=\s*(?:\([^)]*\)|[A-Za-z0-9_$]+)?\s*=>\s*\{)",
    content,
  )
  if component_match:
    return content[: component_match.end()] + "\n  const navigate = useNavigate();" + content[component_match.end() :]
  return content


def set_button_onclick(opening: str, target_route: str) -> str:
  route_literal = js_string_literal(target_route)
  onclick = f"onClick={{() => navigate({route_literal})}}"
  if re.search(r"\sonClick\s*=", opening):
    return re.sub(r"\s+onClick\s*=\s*\{[^}]*\}", f" {onclick}", opening, count=1)
  return opening[:-1].rstrip() + f" {onclick}>"


def js_string_literal(value: str) -> str:
  escaped = text_or_default(value, "").replace("\\", "\\\\").replace("'", "\\'")
  return f"'{escaped}'"


def deterministic_new_project_modal_fix_code(content: str) -> str:
  button_match = re.search(r"<button\b(?P<attrs>[^>]*)>(?P<body>[\s\S]{0,900}?New Project[\s\S]{0,900}?)</button>", content)
  if not button_match:
    return ""
  button_block = button_match.group(0)
  if "onClick" in button_match.group("attrs"):
    return ""

  updated = ensure_react_use_state_import(content)
  state_name = "isNewProjectModalOpen"
  setter_name = "setIsNewProjectModalOpen"
  if state_name not in updated:
    component_match = re.search(
      r"(?P<decl>(?:export\s+default\s+)?(?:function|const)\s+[A-Z][A-Za-z0-9_]*\s*(?:=\s*\([^)]*\)\s*=>|\([^)]*\))\s*\{)",
      updated,
    )
    if not component_match:
      return ""
    updated = updated[: component_match.end()] + f"\n  const [{state_name}, {setter_name}] = useState(false);" + updated[component_match.end() :]

  new_button_block = button_block.replace("<button", f"<button onClick={{() => {setter_name}(true)}}", 1)
  updated = updated.replace(button_block, new_button_block, 1)

  if "Create New Project" not in updated:
    modal_markup = (
      "\n      {isNewProjectModalOpen && (\n"
      "        <div className=\"fixed inset-0 z-50 flex items-center justify-center bg-[var(--modal-backdrop)] p-4\">\n"
      "          <div className=\"w-full max-w-md rounded-2xl border border-[var(--border-color)] bg-[var(--modal-bg)] p-6 shadow-2xl\">\n"
      "            <div className=\"flex items-start justify-between gap-4\">\n"
      "              <div>\n"
      "                <h2 className=\"text-xl font-bold\">Create New Project</h2>\n"
      "                <p className=\"mt-2 text-sm text-[var(--muted-text)]\">Start a new project from this workspace.</p>\n"
      "              </div>\n"
      "              <button\n"
      "                type=\"button\"\n"
      "                onClick={() => setIsNewProjectModalOpen(false)}\n"
      "                className=\"rounded-lg border border-[var(--border-color)] px-3 py-1 text-sm font-semibold hover:bg-[var(--hover-bg)]\"\n"
      "              >\n"
      "                Close\n"
      "              </button>\n"
      "            </div>\n"
      "          </div>\n"
      "        </div>\n"
      "      )}\n"
    )
    updated = insert_jsx_before_last_root_close(updated, modal_markup)
  return updated


def ensure_react_use_state_import(content: str) -> str:
  if re.search(r"import\s+React\s*,\s*\{[^}]*\buseState\b[^}]*\}\s+from\s+['\"]react['\"]", content):
    return content
  if re.search(r"import\s+\{[^}]*\buseState\b[^}]*\}\s+from\s+['\"]react['\"]", content):
    return content
  updated = re.sub(
    r"import\s+React\s+from\s+(['\"]react['\"]);",
    r"import React, { useState } from \1;",
    content,
    count=1,
  )
  if updated != content:
    return updated
  updated = re.sub(
    r"import\s+React\s*,\s*\{([^}]*)\}\s+from\s+(['\"]react['\"]);",
    lambda match: f"import React, {{ {append_named_import(match.group(1), 'useState')} }} from {match.group(2)};",
    content,
    count=1,
  )
  if updated != content:
    return updated
  updated = re.sub(
    r"import\s+\{([^}]*)\}\s+from\s+(['\"]react['\"]);",
    lambda match: f"import {{ {append_named_import(match.group(1), 'useState')} }} from {match.group(2)};",
    content,
    count=1,
  )
  if updated != content:
    return updated
  return f'import {{ useState }} from "react";\n{content}'


def append_named_import(imports: str, name: str) -> str:
  parts = [part.strip() for part in imports.split(",") if part.strip()]
  if name not in parts:
    parts.append(name)
  return ", ".join(parts)


def insert_jsx_before_last_root_close(content: str, insertion: str) -> str:
  candidates = [(index, tag) for tag in ("</main>", "</section>", "</div>") if (index := content.rfind(tag)) >= 0]
  if not candidates:
    return ""
  index, _tag = max(candidates, key=lambda item: item[0])
  return f"{content[:index]}{insertion}{content[index:]}"
