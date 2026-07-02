from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..artifacts import ArtifactValidationError, validate_project_artifact
from ..project_workspace import is_standalone_code_source_path
from ..schema import ResponseContractError, sanitize_generation_response
from .state import GenerationPipelineState
from .tool_registry import log_tool_call

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
    "theme": generated_website.get("theme") if isinstance(generated_website.get("theme"), dict) else {
      "colors": {
        "primary": "#0f766e",
        "secondary": "#2563eb",
        "accent": "#14212b",
        "background": "#ffffff",
        "text": "#14212b",
      },
      "style_direction": "Code-only response",
    },
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
  """Fill missing artifact metadata fields before response assembly (streaming/clarification paths)."""
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
  theme = raw.get("theme") if isinstance(raw.get("theme"), dict) else {
    "colors": {
      "primary": "#0f766e",
      "secondary": "#2563eb",
      "accent": "#14212b",
      "background": "#ffffff",
      "text": "#14212b",
    },
    "style_direction": "Responsive React and Tailwind website",
  }
  return {
    **raw,
    "title": title,
    "headline": str(raw.get("headline") or title).strip() or title,
    "subheadline": summary or default_sub,
    "primary_cta": str(raw.get("primary_cta") or "Preview site").strip() or "Preview site",
    "secondary_cta": str(raw.get("secondary_cta") or "Edit files").strip() or "Edit files",
    "preview_html": str(raw.get("preview_html") or ""),
    "theme": theme,
    "sections": sections,
    "files": files,
  }

def normalize_theme(theme: Any) -> dict[str, Any]:
  colors = {}
  if isinstance(theme, dict) and isinstance(theme.get("colors"), dict):
    colors = theme["colors"]

  return {
    "colors": {
      "primary": text_value(colors.get("primary"), "#0f766e"),
      "secondary": text_value(colors.get("secondary"), "#2563eb"),
      "accent": text_value(colors.get("accent"), "#14212b"),
      "background": text_value(colors.get("background"), "#ffffff"),
      "text": text_value(colors.get("text"), "#14212b"),
    },
    "style_direction": text_value(
      theme.get("style_direction") if isinstance(theme, dict) else None,
      "Clean responsive React and Tailwind website",
    ),
  }

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
    "    <main className=\"min-h-screen bg-white px-6 py-16 text-slate-950\">\n"
    f"      <p className=\"text-sm font-bold text-teal-700\">{title}</p>\n"
    f"      <h1 className=\"mt-4 max-w-3xl text-5xl font-black\">{headline}</h1>\n"
    "    </main>\n"
    "  );\n"
    "}\n"
  )

_GENERIC_UPDATE_SUMMARIES = {
  "parallel file workers completed.",
  "updated project files from your prompt.",
}

_GENERIC_GENERATION_SUMMARIES = {
  "parallel file workers completed.",
  "generated project files from your prompt.",
  "streaming file agent finished",
}

def _non_empty_string_list(value: Any) -> list[str]:
  if not isinstance(value, list):
    return []
  return [str(item).strip() for item in value if str(item or "").strip()]

def _file_entry_paths(value: Any, *, changed_only: bool = False) -> list[str]:
  if not isinstance(value, list):
    return []
  paths: list[str] = []
  for item in value:
    if not isinstance(item, dict):
      continue
    path = str(item.get("path") or "").strip()
    if not path:
      continue
    purpose = str(item.get("purpose") or "").strip().lower()
    if "preserved existing project file" in purpose:
      continue
    if changed_only:
      if purpose and any(marker in purpose for marker in ("updated", "changed", "generated", "created")):
        paths.append(path)
        continue
      if str(item.get("content") or item.get("code") or "").strip():
        paths.append(path)
      continue
    paths.append(path)
  return paths

def _payload_change_containers(
  artifact_response: dict[str, Any],
  generated_website: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
  containers: list[dict[str, Any]] = [artifact_response]
  for key in (
    "targeted_update",
    "scoped_update",
    "update_result",
    "runtime",
    "agentic_runtime",
    "final_output",
  ):
    value = artifact_response.get(key)
    if isinstance(value, dict):
      containers.append(value)

  artifact_generated = artifact_response.get("generated_website")
  if isinstance(artifact_generated, dict):
    containers.append(artifact_generated)
  if isinstance(generated_website, dict):
    containers.append(generated_website)
  return containers

def _payload_has_code_change_evidence(
  artifact_response: dict[str, Any],
  generated_website: dict[str, Any] | None = None,
) -> bool:
  if not isinstance(artifact_response, dict):
    return False

  for container in _payload_change_containers(artifact_response, generated_website):
    for key in ("changed_file_paths", "changed_paths", "patch_paths", "materialized_file_paths"):
      if _non_empty_string_list(container.get(key)):
        return True
    if _file_entry_paths(container.get("changed_files")):
      return True

    files = container.get("files")
    if container is artifact_response:
      if _file_entry_paths(files):
        return True
    elif _file_entry_paths(files, changed_only=True):
      return True

    diff_summary = container.get("code_diff_summary")
    if isinstance(diff_summary, dict):
      try:
        if int(diff_summary.get("file_count") or 0) > 0:
          return True
      except (TypeError, ValueError):
        pass

    diff_detail = container.get("diff_detail")
    if isinstance(diff_detail, dict) and isinstance(diff_detail.get("diffs"), list) and diff_detail.get("diffs"):
      return True

  return False

def _payload_explicitly_has_no_code_changes(
  artifact_response: dict[str, Any],
  generated_website: dict[str, Any] | None = None,
) -> bool:
  if not isinstance(artifact_response, dict):
    return False
  if _payload_has_code_change_evidence(artifact_response, generated_website):
    return False

  for container in _payload_change_containers(artifact_response, generated_website):
    saw_change_path_field = False
    for key in ("changed_file_paths", "changed_paths"):
      if key not in container:
        continue
      saw_change_path_field = True
    if saw_change_path_field:
      return True

  if "files" in artifact_response and isinstance(artifact_response.get("files"), list):
    return not _file_entry_paths(artifact_response.get("files"))

  return False

def build_update_conversation_message(
  *,
  artifact_response: dict[str, Any],
  generated_website: dict[str, Any] | None = None,
) -> str:
  summary = str(
    artifact_response.get("summary")
    or artifact_response.get("output_text")
    or ""
  ).strip()
  generic_summary = summary.lower() in _GENERIC_UPDATE_SUMMARIES
  validation = artifact_response.get("update_validation") if isinstance(artifact_response, dict) else None
  if isinstance(validation, dict) and validation.get("kind") == "brand_rename":
    expected = str(validation.get("expected") or "the requested name")
    if validation.get("applied"):
      return f"Updated the website name to {expected}."
    if summary and not generic_summary and _payload_has_code_change_evidence(artifact_response, generated_website):
      return summary[:400]
    return (
      f"The website name was not changed to {expected}. "
      "The agent explored files but did not update index.html or the navbar brand text."
    )
  clarification = str(artifact_response.get("clarification_question") or "").strip()
  if clarification:
    return clarification[:400]
  commit_result = artifact_response.get("commit_result")
  if not isinstance(commit_result, dict):
    runtime = artifact_response.get("runtime") if isinstance(artifact_response.get("runtime"), dict) else {}
    if isinstance(runtime.get("commit_result"), dict):
      commit_result = runtime["commit_result"]
  if isinstance(commit_result, dict):
    commit_message = str(commit_result.get("user_message") or "").strip()
    if commit_message and (
      commit_result.get("persisted")
      or _payload_explicitly_has_no_code_changes(artifact_response, generated_website)
    ):
      return commit_message[:500]
  if _payload_explicitly_has_no_code_changes(artifact_response, generated_website):
    runtime = artifact_response.get("runtime") if isinstance(artifact_response.get("runtime"), dict) else {}
    if not runtime and isinstance(artifact_response.get("agentic_runtime"), dict):
      runtime = artifact_response["agentic_runtime"]
    tool_failures = [str(item) for item in (runtime.get("tool_failures") or []) if str(item or "").strip()]
    rejected_writes = runtime.get("rejected_writes") if isinstance(runtime.get("rejected_writes"), list) else []
    locked_rejected = [
      str(item.get("path") or "")
      for item in rejected_writes
      if isinstance(item, dict) and str(item.get("reason") or "") == "locked_platform_file"
    ]
    if locked_rejected:
      return (
        "No app code changes were saved. The agent tried to edit locked platform files "
        f"({', '.join(locked_rejected[:4])}). Retry and ask for changes in src/pages or src/components only."
      )
    if any("syntax" in item.lower() for item in tool_failures):
      return (
        "The update edited files but saving was blocked by a syntax check (unbalanced braces or a missing export). "
        "Retry the same request — the agent will apply a smaller fix in the target page or component."
      )
    if summary and not generic_summary:
      return (
        "No code changes were applied. "
        f"The update agent summary was: {summary[:320]}"
      )
    return (
      "I rebuilt the preview, but no code changes were applied. "
      "The update agent did not produce a safe file patch for this request."
    )
  if summary and not generic_summary:
    return summary[:400]
  return "Updated the website preview from the provided prompt."


def build_generation_conversation_message(
  *,
  artifact_response: dict[str, Any],
  generated_website: dict[str, Any] | None = None,
) -> str:
  clarification = str(artifact_response.get("clarification_question") or "").strip()
  if clarification:
    return clarification[:400]

  runtime = artifact_response.get("runtime") if isinstance(artifact_response.get("runtime"), dict) else {}
  if str(runtime.get("status") or artifact_response.get("status") or "") == "needs_clarification":
    question = str(runtime.get("clarification_question") or artifact_response.get("summary") or "").strip()
    if question:
      return question[:400]

  summary = str(
    artifact_response.get("summary")
    or artifact_response.get("output_text")
    or runtime.get("output_text")
    or ""
  ).strip()
  generic_summary = summary.lower() in _GENERIC_GENERATION_SUMMARIES

  if _payload_explicitly_has_no_code_changes(artifact_response, generated_website):
    runtime = artifact_response.get("runtime") if isinstance(artifact_response.get("runtime"), dict) else {}
    tool_failures = [str(item) for item in (runtime.get("tool_failures") or []) if str(item or "").strip()]
    if any("syntax" in item.lower() for item in tool_failures):
      return (
        "The update edited files but saving was blocked by a syntax check (unbalanced braces or a missing export). "
        "Retry the same request — the agent will apply a smaller routing fix in src/App.jsx and related auth pages."
      )
    if isinstance(generated_website, dict):
      generated_file_count = len(_file_entry_paths(generated_website.get("files")))
      if generated_file_count:
        return f"Generated the website with {generated_file_count} file(s)."
    if summary and not generic_summary:
      return (
        "No website files were generated. "
        f"The generation summary was: {summary[:320]}"
      )
    return (
      "I prepared the preview shell, but no website files were generated for this request. "
      "Try adding more detail about pages, modules, and features you need."
    )

  changed_paths = _non_empty_string_list(artifact_response.get("changed_paths"))
  if not changed_paths:
    for container in _payload_change_containers(artifact_response, generated_website):
      changed_paths = _non_empty_string_list(container.get("changed_paths"))
      if changed_paths:
        break

  files = generated_website.get("files") if isinstance(generated_website, dict) else []
  file_count = len(_file_entry_paths(files)) if isinstance(files, list) else len(changed_paths)
  if changed_paths:
    return f"Generated the website with {len(changed_paths)} updated file(s)."
  if file_count:
    return f"Generated the website with {file_count} file(s)."

  if summary and not generic_summary:
    return summary[:400]

  return "Generated the website preview from the provided prompt."


def build_website_generation_response(
  state: GenerationPipelineState,
  *,
  generated_website: dict[str, Any],
  artifact_response: dict[str, Any],
) -> dict[str, Any]:
  implementation_notes = extract_implementation_notes(artifact_response)
  generated_website = normalize_loose_generated_website(
    generated_website,
    intent=state.intent,
    prompt=state.user_prompt,
    artifact_response=artifact_response,
  )
  multi_agent_system = deepcopy(state.prepared_sections.get("multi_agent_system") or {})
  gemini_tool_calling_setup = deepcopy(state.prepared_sections.get("gemini_tool_calling_setup") or {})
  google_adk_usage = deepcopy(state.prepared_sections.get("google_adk_usage") or {})
  is_update = state.intent == "website_update"
  is_simple_code = state.intent == "simple_code"
  title = generated_website["title"]
  subheadline = generated_website["subheadline"]
  files = generated_website["files"]

  multi_agent_system["goal"] = (
    f"Update website artifact: {title}"
    if is_update
    else f"Write standalone code artifact: {title}"
    if is_simple_code
    else f"Generate website artifact: {title}"
  )
  multi_agent_system["intent"] = state.intent
  multi_agent_system["active_agent"] = "Simple Code Writer Agent" if is_simple_code else "Prompt Analyst Agent"
  multi_agent_system["routing_result"] = state.routing_result
  multi_agent_system["conversation_response"] = {
    "type": "simple_code" if is_simple_code else "update" if is_update else "generation",
    "message": (
      build_update_conversation_message(
        artifact_response=artifact_response,
        generated_website=generated_website,
      )
      if is_update
      else build_generation_conversation_message(
        artifact_response=artifact_response,
        generated_website=generated_website,
      )
      if not is_simple_code
      else "Generated the requested standalone code file."
    ),
    "next_prompt_guidance": list_from_notes(
      implementation_notes,
      "recommended_next_actions",
      ["Review the preview.", "Ask for visual edits.", "Generate another section."],
    ),
  }
  shared_state = multi_agent_system.setdefault("shared_state", {})
  shared_state.update(
    {
      "prompt": state.user_prompt,
      "project_context": subheadline,
      "website_blueprint": title,
      "generated_files": (
        f"{len(files)} React/Tailwind file artifacts prepared for update."
        if is_update
        else f"{len(files)} standalone code file artifacts prepared."
        if is_simple_code
        else f"{len(files)} React/Tailwind file artifacts prepared."
      ),
      "validation_report": (
        "Updated artifact normalized and merged with existing project files by backend before response."
        if is_update
        else "Code artifact normalized and saved by backend before response."
        if is_simple_code
        else "Generated artifact normalized by backend before response."
      ),
    }
  )

  return sanitize_generation_response(
    {
      "multi_agent_system": multi_agent_system,
      "gemini_tool_calling_setup": gemini_tool_calling_setup,
      "google_adk_usage": google_adk_usage,
      "orchestration_flow": {
        "steps": build_generation_steps(state, generated_website),
        "generated_website": generated_website,
      },
      "agent_to_agent_communication": build_generation_communication(state, generated_website),
      "proactive_thinking": {
        "assumptions": list_from_notes(
          implementation_notes,
          "assumptions",
          ["The user wants the existing website updated while preserving unrelated files."]
          if is_update
          else ["The user wants a standalone code file, not a website."]
          if is_simple_code
          else ["The user wants a complete first version from one prompt."],
        ),
        "missing_information": list_from_notes(
          implementation_notes,
          "missing_information",
          []
          if is_simple_code
          else ["Exact brand assets", "Final copy", "Production integrations"],
        ),
        "predicted_risks": list_from_notes(
          implementation_notes,
          "predicted_risks",
          ["The requested language runtime may not be installed locally."]
          if is_simple_code
          else ["Some copy may need brand-specific refinement."],
        ),
        "self_checks": list_from_notes(
          implementation_notes,
          "self_checks",
          ["Generated code artifact has at least one file"]
          if is_simple_code
          else ["Generated website has sections", "Generated website has at least one file"],
        ),
        "recommended_next_actions": list_from_notes(
          implementation_notes,
          "recommended_next_actions",
          ["Review the updated preview.", "Request follow-up edits.", "Export the updated React files."]
          if is_update
          else ["Open the generated code file.", "Run it with the requested language runtime."]
          if is_simple_code
          else ["Review the preview.", "Request design refinements.", "Export the generated React files."],
        ),
      },
    }
  )

def build_generation_steps(state: GenerationPipelineState, generated_website: dict[str, Any]) -> list[dict[str, Any]]:
  generated_website = normalize_loose_generated_website(
    generated_website,
    intent=state.intent,
    prompt=state.user_prompt,
  )
  is_update = state.intent == "website_update"
  is_simple_code = state.intent == "simple_code"
  title = generated_website["title"]
  sections = generated_website["sections"]
  files = generated_website["files"]
  return [
    {
      "step": 1,
      "name": "Tool-based intent routing",
      "owner_agent": "Intent Router Agent",
      "input": state.user_prompt,
      "actions": [
        "Call route_generation_action",
        "Select generate_simple_code_file"
        if is_simple_code
        else "Select analyze_update_request"
        if state.intent == "website_update"
        else "Select analyze_prompt",
      ],
      "output": state.routing_result,
    },
    {
      "step": 2,
      "name": "Code request analysis" if is_simple_code else "Update request analysis" if is_update else "Prompt analysis",
      "owner_agent": "Simple Code Writer Agent" if is_simple_code else "Prompt Analyst Agent",
      "input": state.user_prompt,
      "actions": (
        ["Infer language", "Infer filename", "Prepare code-only artifact"]
        if is_simple_code
        else
        ["Identify requested changes", "Map update to existing project files"]
        if is_update
        else ["Identify website type", "Extract audience and content goals"]
      ),
      "output": title,
    },
    {
      "step": 3,
      "name": "Standalone code planning" if is_simple_code else "Predictive website planning",
      "owner_agent": "Simple Code Writer Agent" if is_simple_code else "Predictive Planning Agent",
      "input": sections,
      "actions": ["Choose code structure", "Choose input/output behavior"] if is_simple_code else ["Plan section order", "Choose conversion path"],
      "output": [section["name"] for section in sections],
    },
    {
      "step": 4,
      "name": "Standalone code generation" if is_simple_code else "Prescriptive update artifact generation" if is_update else "Prescriptive artifact generation",
      "owner_agent": "Simple Code Writer Agent" if is_simple_code else "Prescriptive Builder Agent",
      "input": title,
      "actions": (
        ["Generate runnable code file", "Skip website shell"]
        if is_simple_code
        else
        ["Generate changed React/Tailwind files", "Preserve unrelated project files"]
        if is_update
        else ["Generate preview content", "Generate React and Tailwind files"]
      ),
      "output": f"{len(files)} files prepared",
    },
    {
      "step": 5,
      "name": "Validation",
      "owner_agent": "Diagnostic UX Agent",
      "input": generated_website,
      "actions": ["Check generated file artifact", "Normalize missing artifact fields"]
      if is_simple_code
      else ["Check required preview data", "Normalize missing artifact fields"],
      "output": "Generated code artifact is response-ready." if is_simple_code else "Generated website artifact is response-ready.",
    },
  ]

def build_generation_communication(state: GenerationPipelineState, generated_website: dict[str, Any]) -> dict[str, Any]:
  generated_website = normalize_loose_generated_website(
    generated_website,
    intent=state.intent,
    prompt=state.user_prompt,
  )
  is_update = state.intent == "website_update"
  title = generated_website["title"]
  sections = generated_website["sections"]
  files = generated_website["files"]
  return {
    "message_contract": {
      "from_agent": "Prompt Analyst Agent",
      "to_agent": "Prescriptive Builder Agent",
      "sender": "Prompt Analyst Agent",
      "receiver": "Prescriptive Builder Agent",
      "task": (
        "Update the existing website artifact from the routed prompt."
        if is_update
        else "Build the website artifact from the routed prompt."
      ),
      "input": {
        "prompt": state.user_prompt,
        "routing_result": state.routing_result,
        "sections": [section["name"] for section in sections],
      },
      "output": {
        "website_title": title,
        "file_paths": [file_item["path"] for file_item in files if isinstance(file_item, dict)],
      },
      "next_action": "generate_update_artifact" if is_update else "generate_project_artifact",
      "context": {
        "prompt": state.user_prompt,
        "routing_result": state.routing_result,
        "website_title": title,
      },
      "expected_output": {
        "generated_website": (
          "Updated preview data and changed file artifacts"
          if is_update
          else "Complete preview data and file artifacts"
        ),
      },
      "confidence": 0.92,
      "risks": (
        ["Requested update may depend on project files outside the generated artifact surface."]
        if is_update
        else ["User may want brand-specific details that were not included in the prompt."]
      ),
    },
    "handoff_rules": [
      "Intent Router Agent must run before generation.",
      "Prompt Analyst Agent passes structured context to planning.",
      "Predictive Planning Agent selects sections before file generation.",
      "Diagnostic UX Agent validates the normalized website artifact.",
    ],
    "example_messages": [
      {
        "from_agent": "Prompt Analyst Agent",
        "to_agent": "Predictive Planning Agent",
        "message": {
          "prompt": state.user_prompt,
          "website_title": title,
          "sections": [section["name"] for section in sections],
        },
      }
    ],
  }

def extract_implementation_notes(response: dict[str, Any]) -> dict[str, Any]:
  notes = response.get("implementation_notes")
  if isinstance(notes, dict):
    return notes

  proactive_thinking = response.get("proactive_thinking")
  if isinstance(proactive_thinking, dict):
    return proactive_thinking

  return {}

def list_from_notes(notes: dict[str, Any], key: str, fallback: list[str]) -> list[str]:
  return normalize_string_list(notes.get(key), fallback)

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

def log_generated_website_tools(result: dict[str, Any]) -> None:
  generated_website = result["orchestration_flow"]["generated_website"]
  sections = generated_website.get("sections") or []
  files = generated_website.get("files") or []

  log_tool_call(
    "analyze_prompt",
    "output",
    {
      "intent": result["multi_agent_system"].get("intent"),
      "routing_result": result["multi_agent_system"].get("routing_result"),
      "website_title": generated_website.get("title"),
      "section_count": len(sections),
    },
  )
  log_tool_call(
    "generate_website_files",
    "output",
    {
      "file_count": len(files),
      "paths": [file.get("path") for file in files if isinstance(file, dict)],
    },
  )
  log_tool_call(
    "validate_generated_website",
    "output",
    {
      "status": "prepared",
      "section_count": len(sections),
      "file_count": len(files),
    },
  )
