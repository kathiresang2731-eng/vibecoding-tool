from __future__ import annotations

from typing import Any

from .canonical_roles import (
  CANONICAL_CONTEXT_AGENT,
  CANONICAL_DOCUMENT_ARTIFACT,
  CANONICAL_ORCHESTRATOR,
  CANONICAL_QUALITY_GATE,
  CANONICAL_READ_ONLY_ASSISTANT,
  CANONICAL_SAVE_MEMORY,
  CANONICAL_SIMPLE_CODE,
  CANONICAL_WEBSITE_BUILDER,
  canonical_role_for_agent,
  canonicalize_agent_entry,
  canonicalize_agent_list,
)


def _tool_purpose(*, does: str, when: str, when_not: str = "") -> str:
  text = f"{does} Use when: {when}"
  if when_not:
    return f"{text} Do not use when: {when_not}"
  return text


# ---------------------------------------------------------------------------
# Orchestration agents (routing, conversation, legacy artifact pipeline)
# ---------------------------------------------------------------------------

ORCHESTRATION_AGENT_TEAM: list[dict[str, Any]] = [
  {
    "name": "Intent Router Agent",
    "role": "Classifies each user turn before any generation, update, or file write runs.",
    "goal": "Select the correct intent and next backend tool from message meaning, not keywords.",
    "mode": "diagnostic",
    "tools": ["route_generation_action"],
    "responsibilities": [
      "Call route_generation_action as the first step on every non-confirmation turn",
      "Return intent, next_action, next_tool, and reason as strict JSON",
      "Never start website generation without a routed artifact intent",
    ],
    "inputs": ["user_prompt"],
    "outputs": ["routing_decision", "next_tool"],
  },
  {
    "name": "Read-only Assistant Agent",
    "role": "Answers questions, general queries, and grounded web searches without changing project files.",
    "goal": "Give a direct answer while preserving the boundary between asking about a change and authorizing one.",
    "mode": "descriptive",
    "tools": ["answer_question", "answer_general_query", "search_web"],
    "responsibilities": [
      "Answer feasibility and capability questions without starting code updates",
      "Handle general knowledge and advice turns directly",
      "Use Google Search grounding for explicit or time-sensitive web requests",
    ],
    "inputs": ["user_prompt", "optional_project_context"],
    "outputs": ["conversation_response", "next_prompt_guidance"],
  },
  {
    "name": "Requirement Confirmation Agent",
    "role": "Prepares and confirms an execution brief before high-impact work.",
    "goal": "Pause generation until the user explicitly confirms the planned changes.",
    "mode": "diagnostic",
    "tools": ["confirm_execution_brief"],
    "responsibilities": [
      "Summarize goal, planned files, assumptions, and protected scope",
      "Persist the brief and wait for confirm, revise, or cancel",
      "Block file writes until confirmation is explicit",
    ],
    "inputs": ["user_prompt", "pending_execution_brief"],
    "outputs": ["confirmation_brief", "confirmation_decision"],
  },
  {
    "name": "Simple Code Writer Agent",
    "role": "Generates standalone code files for simple_code turns.",
    "goal": "Return complete runnable code artifacts without a website shell.",
    "mode": "prescriptive",
    "tools": ["generate_simple_code_file"],
    "responsibilities": [
      "Infer language and filename from the user request",
      "Generate self-contained code without React/Vite scaffolding",
      "Return artifacts for backend validation only",
    ],
    "inputs": ["user_prompt", "routing_decision"],
    "outputs": ["generated_code_files", "run_guidance"],
  },
  {
    "name": "Document Artifact Agent",
    "role": "Generates documentation, planning, research, CSV, Markdown, TXT, and PDF-ready source files.",
    "goal": "Return useful document artifacts without creating website or app scaffolding.",
    "mode": "prescriptive",
    "tools": ["generate_document_artifact"],
    "responsibilities": [
      "Infer the requested document format and safe filename",
      "Generate complete document content in .md, .txt, .csv, or .pdf form",
      "Return artifacts for backend validation only",
    ],
    "inputs": ["user_prompt", "routing_decision"],
    "outputs": ["generated_document_files", "review_guidance"],
  },
  {
    "name": "Prompt Analyst Agent",
    "role": "Extracts structured requirements from the user prompt and project context.",
    "goal": "Produce a website brief with audience, sections, stack, and missing fields.",
    "mode": "descriptive",
    "tools": ["analyze_prompt", "RUN_PROMPT_ANALYST"],
    "responsibilities": [
      "Parse business type, audience, tone, and required sections",
      "Surface missing_information before expensive generation",
      "Include existing files and memory in update turns",
    ],
    "inputs": ["user_prompt", "project_files", "memory"],
    "outputs": ["project_context", "website_goal", "brief"],
  },
  {
    "name": "Diagnostic UX Agent",
    "role": "Reviews requirements and plans for UX, conversion, and layout risks.",
    "goal": "Find gaps and risks before code generation starts.",
    "mode": "diagnostic",
    "tools": ["RUN_UX_REVIEW_AGENT", "RUN_PARALLEL_REVIEW_AGENTS"],
    "responsibilities": [
      "Detect missing inputs and weak conversion paths",
      "Flag responsive layout and content hierarchy risks",
      "Feed recommendations into the validation plan",
    ],
    "inputs": ["project_context", "plan"],
    "outputs": ["risk_report", "validation_plan"],
  },
  {
    "name": "Predictive Planning Agent",
    "role": "Plans sections, layout hierarchy, and implementation sequence.",
    "goal": "Deliver a generation-ready blueprint the code agent can execute.",
    "mode": "predictive",
    "tools": ["RUN_PLANNER"],
    "responsibilities": [
      "Choose page sections and component hierarchy",
      "Plan interactions, backend touchpoints, and quality gates",
      "Prefer concrete paths and preserve rules on updates",
    ],
    "inputs": ["project_context", "risk_report", "brief"],
    "outputs": ["website_blueprint", "plan"],
  },
  {
    "name": "Prescriptive Builder Agent",
    "role": "Generates final React + Tailwind artifacts from an approved blueprint.",
    "goal": "Return validated generated_website files and next actions.",
    "mode": "prescriptive",
    "tools": ["generate_website_files", "validate_generated_website", "RUN_CODE_AGENT"],
    "responsibilities": [
      "Generate UI content and editable source files",
      "Package sections, theme, and file paths in artifact JSON",
      "Never commit files directly; backend gates handle persistence",
    ],
    "inputs": ["website_blueprint", "validation_plan", "plan"],
    "outputs": ["generated_website"],
  },
  {
    "name": "Streaming File Agent",
    "role": "Fast coding agent that reads and writes project files through Gemini tool calls.",
    "goal": "Implement or update the website by calling read_file, list_files, write_file, and str_replace until the request is done.",
    "mode": "prescriptive",
    "tools": ["read_file", "write_file", "str_replace", "list_files"],
    "responsibilities": [
      "Read relevant files before editing",
      "Prefer str_replace for small edits and write_file for new or full files",
      "Keep React sources under src/ and never edit runtime shim files",
    ],
    "inputs": ["user_prompt", "intent", "project_context", "attachments"],
    "outputs": ["changed_files", "assistant_summary"],
  },
  {
    "name": "Parallel Stream Orchestrator",
    "role": "Plans optional specialists then delegates to the Streaming File Agent.",
    "goal": "Run content/layout/catalog planning in parallel when useful, then stream file edits.",
    "mode": "predictive",
    "tools": ["read_file", "write_file", "str_replace", "list_files"],
    "responsibilities": [
      "Select the minimum specialist set for the prompt",
      "Run specialists in parallel threads when not skipped",
      "Inject specialist JSON plans into the streaming file agent prompt",
    ],
    "inputs": ["user_prompt", "intent"],
    "outputs": ["specialist_plans", "generated_website"],
  },
  {
    "name": "Supervisor Agent",
    "role": "Chooses the next legal runtime action and stops the loop when proof is complete.",
    "goal": "Drive the full runtime loop from intake through validation, preview, commit, and memory persistence.",
    "mode": "diagnostic",
    "tools": [],
    "responsibilities": [
      "Pick next_action only from the provided available_actions list",
      "Never skip required backend tools or completion gates",
      "End with DONE only after WRITE_PROJECT_FILES and PERSIST_PROJECT_MEMORY proof",
    ],
    "inputs": ["runtime_state", "available_actions", "completion_proof"],
    "outputs": ["next_agent", "next_action", "stop_or_continue"],
  },
]

# ---------------------------------------------------------------------------
# Runtime agents (full supervisor loop)
# ---------------------------------------------------------------------------

RUNTIME_AGENT_POLICIES: dict[str, dict[str, Any]] = {
  "Memory Agent": {
    "role": "workspace_context",
    "goal": "Load project files and memory at intake; persist the accepted summary at the end.",
    "responsibility": "Load project files and persistent memory at intake, then persist the accepted runtime summary after commit.",
    "tools": ["READ_PROJECT_FILES", "LOAD_PROJECT_MEMORY", "PERSIST_PROJECT_MEMORY"],
    "input": ["project_id"],
    "backend_authority": True,
  },
  "Universal Error Handling Agent": {
    "role": "error_triage",
    "goal": "Classify build/runtime/API errors and narrow root-cause files before patching.",
    "responsibility": "Classify user-provided build/runtime/API errors and identify likely root-cause files before update analysis.",
    "tools": [],
    "input": ["prompt"],
    "output": ["status"],
  },
  "Update Analysis Agent": {
    "role": "scope_control",
    "goal": "Choose the smallest safe update mode and approved candidate files.",
    "responsibility": "Select the smallest safe existing-project update strategy and candidate files.",
    "tools": [],
    "input": ["prompt", "files"],
    "output": ["update_mode", "candidate_files"],
  },
  "Scoped Update Agent": {
    "role": "scoped_patch",
    "goal": "Patch only backend-approved paths with the smallest effective change.",
    "responsibility": "Patch only backend-approved files for a targeted update, bug fix, or bounded feature change.",
    "tools": [],
    "input": ["update_analysis", "candidate_files"],
    "output": ["changed_file_paths"],
    "max_retries": 1,
  },
  "Prompt Analyst Agent": {
    "role": "requirements",
    "goal": "Turn prompt, files, and memory into a structured website or update brief.",
    "responsibility": "Turn the user prompt, project files, and memory into a structured website brief.",
    "tools": [],
    "input": ["prompt"],
    "output": ["brief"],
  },
  "Planner Agent": {
    "role": "planning",
    "goal": "Create the section, layout, quality-gate, and implementation plan.",
    "responsibility": "Create the website/update plan, quality gates, and implementation sequence.",
    "tools": [],
    "input": ["brief"],
    "output": ["plan"],
  },
  "Agent Registry Agent": {
    "role": "dynamic_specialists",
    "goal": "Plan and run bounded specialist agents before code generation.",
    "responsibility": "Plan and execute bounded specialist-agent contributions.",
    "tools": [],
  },
  "UX Review Agent": {
    "role": "ux_review",
    "goal": "Review the plan for workflow, conversion, responsive layout, and content risks.",
    "responsibility": "Review workflow, conversion, responsive layout, and content risks.",
    "tools": [],
    "input": ["plan"],
  },
  "Accessibility Agent": {
    "role": "accessibility_review",
    "goal": "Review contrast, semantics, keyboard flow, and mobile fit before code is generated.",
    "responsibility": "Review contrast, semantic structure, keyboard flow, and mobile fit.",
    "tools": [],
    "input": ["plan"],
  },
  "Code Agent": {
    "role": "code_generation",
    "goal": "Generate candidate project artifact JSON without committing files.",
    "responsibility": "Generate candidate project code without committing files.",
    "tools": [],
    "input": ["plan"],
    "output": ["generated_website"],
    "max_retries": 1,
  },
  "Code Generator Agent": {
    "role": "patch_integration",
    "goal": "Merge validated dynamic-agent patches into the staged artifact.",
    "responsibility": "Integrate validated dynamic-agent candidate patches into the staged artifact.",
    "tools": [],
    "input": ["candidate_changes"],
    "output": ["generated_website"],
  },
  "Materialize Agent": {
    "role": "workspace_materialization",
    "goal": "Stage candidate files in the workspace and stream them to the UI before preview.",
    "responsibility": "Materialize planned candidate files before validation and preview.",
    "tools": [],
    "input": ["files"],
    "output": ["files_materialized"],
    "backend_authority": True,
  },
  "Repair Agent": {
    "role": "artifact_repair",
    "goal": "Repair candidate code after validation, preview, or runtime failures.",
    "responsibility": "Repair candidate code after validation, preview, or runtime failures.",
    "tools": [],
    "input": ["generated_website"],
    "output": ["generated_website"],
    "max_retries": 1,
  },
  "Validation Agent": {
    "role": "contract_validation",
    "goal": "Validate artifact shape, paths, dependencies, and commit readiness.",
    "responsibility": "Validate artifact shape, file paths, dependency safety, and commit readiness.",
    "tools": ["VALIDATE_PROJECT_ARTIFACT"],
    "input": ["generated_website"],
    "output": ["status"],
    "backend_authority": True,
    "requires_completion_gate": True,
  },
  "Preview Agent": {
    "role": "staged_preview",
    "goal": "Build a staged Vite preview from candidate files before final commit.",
    "responsibility": "Build candidate files in a staged preview before the final project write.",
    "tools": ["BUILD_STAGED_PROJECT_PREVIEW"],
    "input": ["files"],
    "output": ["version"],
    "backend_authority": True,
    "requires_completion_gate": True,
  },
  "Visual QA Agent": {
    "role": "runtime_qa",
    "goal": "Verify staged preview integrity before files are committed.",
    "responsibility": "Validate the staged preview runtime before commit.",
    "tools": ["RUN_PREVIEW_VISUAL_QA"],
    "input": ["preview_url"],
    "output": ["status"],
    "backend_authority": True,
    "requires_completion_gate": True,
  },
  "Commit Agent": {
    "role": "file_commit",
    "goal": "Write files only after validation, staged preview, and QA gates pass.",
    "responsibility": "Write files only after validation, staged preview, and QA gates pass.",
    "tools": ["WRITE_PROJECT_FILES"],
    "input": ["files"],
    "output": ["file_count"],
    "backend_authority": True,
    "requires_completion_gate": True,
  },
  "Supervisor Agent": {
    "role": "supervisor",
    "goal": "Select the next legal runtime action and end with DONE when completion proof is satisfied.",
    "responsibility": "Stop the loop only after completion proof is satisfied.",
    "tools": [],
  },
}

_RUNTIME_AGENT_MODES: dict[str, str] = {
  "workspace_context": "intake",
  "error_triage": "diagnostic",
  "scope_control": "diagnostic",
  "scoped_patch": "prescriptive",
  "requirements": "descriptive",
  "planning": "predictive",
  "dynamic_specialists": "predictive",
  "ux_review": "diagnostic",
  "accessibility_review": "diagnostic",
  "code_generation": "prescriptive",
  "patch_integration": "prescriptive",
  "workspace_materialization": "prescriptive",
  "artifact_repair": "prescriptive",
  "contract_validation": "diagnostic",
  "staged_preview": "prescriptive",
  "runtime_qa": "diagnostic",
  "file_commit": "prescriptive",
  "supervisor": "diagnostic",
}


def _runtime_agent_team_entries() -> list[dict[str, Any]]:
  covered = {entry["name"] for entry in ORCHESTRATION_AGENT_TEAM}
  entries: list[dict[str, Any]] = []
  for name, policy in RUNTIME_AGENT_POLICIES.items():
    if name in covered:
      continue
    role_key = str(policy.get("role") or "runtime")
    entries.append(
      canonicalize_agent_entry({
        "name": name,
        "role": str(policy["responsibility"]),
        "goal": str(policy.get("goal") or ""),
        "mode": _RUNTIME_AGENT_MODES.get(role_key, "runtime"),
        "tools": list(policy.get("tools") or []),
        "responsibilities": [str(policy["responsibility"])],
        "inputs": list(policy.get("input") or []),
        "outputs": list(policy.get("output") or []),
      })
    )
  return entries


VISIBLE_AGENT_TEAM: list[dict[str, Any]] = [
  {
    "name": CANONICAL_ORCHESTRATOR,
    "role": "Routes the user turn, confirms risky work, and supervises legal flow transitions.",
    "goal": "Choose the correct branch before any generation, update, or file write starts.",
    "mode": "diagnostic",
    "tools": ["route_generation_action", "confirm_execution_brief"],
    "internal_agents": ["Intent Router Agent", "Requirement Confirmation Agent", "Supervisor Agent"],
  },
  {
    "name": CANONICAL_READ_ONLY_ASSISTANT,
    "role": "Handles questions, greetings, general queries, and project information without file changes.",
    "goal": "Answer directly when no artifact mutation is authorized.",
    "mode": "descriptive",
    "tools": ["handle_greeting", "answer_question", "answer_general_query", "search_web", "summarize_current_project"],
    "internal_agents": ["Read-only Assistant Agent", "Conversation Agent"],
  },
  {
    "name": CANONICAL_SIMPLE_CODE,
    "role": "Generates standalone code files outside the website runtime.",
    "goal": "Create complete runnable scripts/programs without React/Vite scaffolding.",
    "mode": "prescriptive",
    "tools": ["generate_simple_code_file"],
    "internal_agents": ["Simple Code Writer Agent"],
  },
  {
    "name": CANONICAL_DOCUMENT_ARTIFACT,
    "role": "Generates document artifacts such as Markdown, TXT, CSV, and PDF-ready content.",
    "goal": "Create documents without website/app generation.",
    "mode": "prescriptive",
    "tools": ["generate_document_artifact"],
    "internal_agents": ["Document Artifact Agent"],
  },
  {
    "name": CANONICAL_CONTEXT_AGENT,
    "role": "Loads files, memory, project context, update scope, and plans before implementation.",
    "goal": "Give the builder only the relevant context and smallest safe scope.",
    "mode": "diagnostic",
    "tools": ["READ_PROJECT_FILES", "LOAD_PROJECT_MEMORY", "analyze_prompt", "analyze_update_request"],
    "internal_agents": [
      "Memory Agent",
      "Universal Error Handling Agent",
      "Update Analysis Agent",
      "Prompt Analyst Agent",
      "Planner Agent",
      "Predictive Planning Agent",
    ],
  },
  {
    "name": CANONICAL_WEBSITE_BUILDER,
    "role": "Generates or updates website files through the selected internal execution strategy.",
    "goal": "Apply only the needed builder path for generation, scoped update, or streaming edit.",
    "mode": "prescriptive",
    "tools": ["generate_website_files", "RUN_CODE_AGENT", "RUN_SCOPED_UPDATE_AGENT", "read_file", "write_file", "str_replace", "list_files"],
    "internal_agents": [
      "Prescriptive Builder Agent",
      "Streaming File Agent",
      "Parallel Stream Orchestrator",
      "Scoped Update Agent",
      "Code Agent",
      "Code Generator Agent",
      "Materialize Agent",
    ],
  },
  {
    "name": CANONICAL_QUALITY_GATE,
    "role": "Validates artifacts, builds previews, and runs QA checks before save.",
    "goal": "Prevent invalid, unsafe, or broken files from being committed.",
    "mode": "diagnostic",
    "tools": ["VALIDATE_PROJECT_ARTIFACT", "BUILD_STAGED_PROJECT_PREVIEW", "RUN_PREVIEW_VISUAL_QA"],
    "internal_agents": ["Diagnostic UX Agent", "UX Review Agent", "Accessibility Agent", "Validation Agent", "Preview Agent", "Visual QA Agent"],
  },
  {
    "name": CANONICAL_SAVE_MEMORY,
    "role": "Commits accepted files and persists project memory after successful completion.",
    "goal": "Save only validated changes and record concise memory for future follow-ups.",
    "mode": "prescriptive",
    "tools": ["WRITE_PROJECT_FILES", "PERSIST_PROJECT_MEMORY"],
    "internal_agents": ["Commit Agent", "Memory Agent"],
  },
]
VISIBLE_AGENT_TEAM = canonicalize_agent_list(VISIBLE_AGENT_TEAM)

INTERNAL_AGENT_REGISTRY: list[dict[str, Any]] = canonicalize_agent_list(ORCHESTRATION_AGENT_TEAM) + _runtime_agent_team_entries()

# Backward-compatible name. Use VISIBLE_AGENT_TEAM for user-facing prompt/log surfaces
# and INTERNAL_AGENT_REGISTRY/FULL_AGENT_REGISTRY when execution internals are needed.
DEFAULT_AGENT_TEAM: list[dict[str, Any]] = VISIBLE_AGENT_TEAM

SPECIALIST_AGENT_POLICIES: dict[str, dict[str, Any]] = {
  "content": {
    "name": "Content Specialist Agent",
    "role": "content_strategy",
    "goal": "Plan copy, sections, tone, and messaging hierarchy for the request.",
    "tools": [],
  },
  "layout": {
    "name": "Layout Specialist Agent",
    "role": "ux_layout",
    "goal": "Plan pages, components, and responsive layout structure.",
    "tools": [],
  },
  "catalog": {
    "name": "Catalog Specialist Agent",
    "role": "data_catalog",
    "goal": "Plan entities, fields, and sample catalog items when products or inventory matter.",
    "tools": [],
  },
}

SPECIALIST_AGENT_REGISTRY: list[dict[str, Any]] = [
  canonicalize_agent_entry({
    "name": str(policy.get("name") or name),
    "role": str(policy.get("role") or name),
    "goal": str(policy.get("goal") or ""),
    "mode": "predictive",
    "tools": list(policy.get("tools") or []),
    "responsibilities": [str(policy.get("goal") or "")],
    "inputs": ["user_prompt", "project_context"],
    "outputs": ["specialist_plan"],
  })
  for name, policy in SPECIALIST_AGENT_POLICIES.items()
]

FULL_AGENT_REGISTRY = VISIBLE_AGENT_TEAM + INTERNAL_AGENT_REGISTRY + SPECIALIST_AGENT_REGISTRY

# ---------------------------------------------------------------------------
# Orchestration tools (routing / conversation / legacy artifact)
# ---------------------------------------------------------------------------

DEFAULT_TOOL_REGISTRY: list[dict[str, Any]] = [
  {
    "name": "route_generation_action",
    "purpose": _tool_purpose(
      does="Route each user turn to the correct backend branch.",
      when="Every new user message before generation, updates, or file writes.",
      when_not="The user is replying to a pending execution brief (confirmation flow handles that).",
    ),
    "input_schema": {
      "type": "object",
      "properties": {
        "message": {"type": "string", "description": "The current user message to classify."},
        "conversation_context": {"type": "string", "description": "Optional chat context label."},
      },
      "required": ["message"],
      "additionalProperties": False,
    },
    "output_schema": {
      "type": "object",
      "properties": {
        "intent": {"type": "string"},
        "next_action": {"type": "string"},
        "next_tool": {"type": "string"},
        "reason": {"type": "string"},
      },
    },
    "approval_required": False,
    "approval_policy": "none",
    "execution_order": 0,
  },
  {
    "name": "handle_greeting",
    "owner_agent": "Intent Router Agent",
    "purpose": _tool_purpose(
      does="Intent Router tool that replies to greeting or small-talk and asks for the website brief.",
      when="Routing selected greeting intent.",
      when_not="The user already provided a generation-ready website brief.",
    ),
    "input_schema": {
      "type": "object",
      "properties": {
        "message": {"type": "string"},
        "conversation_context": {"type": "string"},
      },
      "required": ["message"],
      "additionalProperties": False,
    },
    "output_schema": {
      "type": "object",
      "properties": {
        "intent": {"type": "string"},
        "reply": {"type": "string"},
        "next_prompt_guidance": {"type": "array", "items": {"type": "string"}},
      },
    },
    "approval_required": False,
    "approval_policy": "none",
    "execution_order": 1,
  },
  {
    "name": "answer_question",
    "purpose": _tool_purpose(
      does="Answer a direct informational, conceptual, or feasibility question without writing files.",
      when="Routing selected question intent.",
      when_not="The user gave an actionable implementation or update command.",
    ),
    "input_schema": {
      "type": "object",
      "properties": {
        "message": {"type": "string"},
        "conversation_context": {"type": "string"},
      },
      "required": ["message"],
      "additionalProperties": False,
    },
    "output_schema": {
      "type": "object",
      "properties": {
        "intent": {"type": "string"},
        "reply": {"type": "string"},
        "next_prompt_guidance": {"type": "array", "items": {"type": "string"}},
      },
    },
    "approval_required": False,
    "approval_policy": "none",
    "execution_order": 1,
  },
  {
    "name": "answer_general_query",
    "purpose": _tool_purpose(
      does="Answer a general explanation, advice, comparison, or brainstorming request.",
      when="Routing selected general_query intent.",
      when_not="The answer requires current web data or project file changes.",
    ),
    "input_schema": {
      "type": "object",
      "properties": {
        "message": {"type": "string"},
        "conversation_context": {"type": "string"},
      },
      "required": ["message"],
      "additionalProperties": False,
    },
    "output_schema": {
      "type": "object",
      "properties": {
        "intent": {"type": "string"},
        "reply": {"type": "string"},
        "next_prompt_guidance": {"type": "array", "items": {"type": "string"}},
      },
    },
    "approval_required": False,
    "approval_policy": "none",
    "execution_order": 1,
  },
  {
    "name": "search_web",
    "purpose": _tool_purpose(
      does="Use Google Search grounding to answer an explicit or time-sensitive web query.",
      when="Routing selected web_search intent.",
      when_not="The request can be answered from the current project or stable model knowledge.",
    ),
    "input_schema": {
      "type": "object",
      "properties": {
        "message": {"type": "string"},
        "conversation_context": {"type": "string"},
        "web_search": {"type": "boolean"},
      },
      "required": ["message"],
      "additionalProperties": False,
    },
    "output_schema": {
      "type": "object",
      "properties": {
        "intent": {"type": "string"},
        "reply": {"type": "string"},
        "next_prompt_guidance": {"type": "array", "items": {"type": "string"}},
      },
    },
    "approval_required": False,
    "approval_policy": "none",
    "execution_order": 1,
  },
  {
    "name": "generate_simple_code_file",
    "purpose": _tool_purpose(
      does="Generate standalone code file artifacts.",
      when="Routing selected simple_code and the user wants a script, function, or program file.",
      when_not="The user wants a website, web app, API project, or project file changes.",
    ),
    "input_schema": {
      "type": "object",
      "properties": {
        "message": {"type": "string"},
        "routing_result": {"type": "object"},
      },
      "required": ["message"],
      "additionalProperties": False,
    },
    "output_schema": {
      "type": "object",
      "properties": {
        "generated_website": {"type": "object"},
        "implementation_notes": {"type": "object"},
      },
      "required": ["generated_website"],
    },
    "approval_required": False,
    "approval_policy": "none",
    "execution_order": 1,
  },
  {
    "name": "generate_document_artifact",
    "purpose": _tool_purpose(
      does="Generate document file artifacts.",
      when="Routing selected document_artifact and the user wants Markdown, TXT, CSV, documentation, a report, a plan, research brief, or PDF export.",
      when_not="The user wants a website, web app, source-code program, API project, or project UI update.",
    ),
    "input_schema": {
      "type": "object",
      "properties": {
        "message": {"type": "string"},
        "routing_result": {"type": "object"},
      },
      "required": ["message"],
      "additionalProperties": False,
    },
    "output_schema": {
      "type": "object",
      "properties": {
        "generated_website": {"type": "object"},
        "implementation_notes": {"type": "object"},
      },
      "required": ["generated_website"],
    },
    "approval_required": False,
    "approval_policy": "none",
    "execution_order": 1,
  },
  {
    "name": "request_website_details",
    "purpose": _tool_purpose(
      does="Ask the user for missing website details.",
      when="Routing selected needs_more_detail.",
      when_not="The prompt already includes concrete pages, audience, and features.",
    ),
    "input_schema": {
      "type": "object",
      "properties": {
        "message": {"type": "string"},
        "missing_fields": {"type": "array", "items": {"type": "string"}},
      },
      "required": ["message", "missing_fields"],
      "additionalProperties": False,
    },
    "output_schema": {
      "type": "object",
      "properties": {
        "intent": {"type": "string"},
        "reply": {"type": "string"},
        "next_prompt_guidance": {"type": "array", "items": {"type": "string"}},
      },
    },
    "approval_required": False,
    "approval_policy": "none",
    "execution_order": 2,
  },
  {
    "name": "confirm_execution_brief",
    "purpose": _tool_purpose(
      does="Present an execution brief and wait for explicit user approval.",
      when="High-impact generation or broad updates require confirmation.",
      when_not="Low-risk scoped updates or conversation-only turns.",
    ),
    "input_schema": {
      "type": "object",
      "properties": {
        "message": {"type": "string"},
        "execution_brief": {"type": "object"},
      },
      "required": ["message"],
      "additionalProperties": False,
    },
    "output_schema": {
      "type": "object",
      "properties": {
        "intent": {"type": "string"},
        "reply": {"type": "string"},
        "confirmation": {"type": "object"},
      },
    },
    "approval_required": True,
    "approval_policy": "explicit_user_confirmation",
    "execution_order": 2,
  },
  {
    "name": "analyze_prompt",
    "purpose": _tool_purpose(
      does="Analyze the user prompt into structured website requirements.",
      when="Starting new website generation after routing.",
      when_not="The turn is an update, greeting, or simple_code request.",
    ),
    "input_schema": {
      "type": "object",
      "properties": {"prompt": {"type": "string", "description": "The user website brief."}},
      "required": ["prompt"],
      "additionalProperties": False,
    },
    "output_schema": {
      "type": "object",
      "properties": {
        "website_type": {"type": "string"},
        "audience": {"type": "string"},
        "required_sections": {"type": "array", "items": {"type": "string"}},
      },
    },
    "approval_required": False,
    "approval_policy": "none",
    "execution_order": 3,
  },
  {
    "name": "analyze_update_request",
    "purpose": _tool_purpose(
      does="Analyze an existing-project update request and scope candidate files.",
      when="Routing selected website_update.",
      when_not="The user only wants project information or a greeting.",
    ),
    "input_schema": {
      "type": "object",
      "properties": {"prompt": {"type": "string"}},
      "required": ["prompt"],
      "additionalProperties": False,
    },
    "output_schema": {
      "type": "object",
      "properties": {
        "update_mode": {"type": "string"},
        "candidate_files": {"type": "array", "items": {"type": "string"}},
      },
    },
    "approval_required": False,
    "approval_policy": "none",
    "execution_order": 3,
  },
  {
    "name": "summarize_current_project",
    "purpose": _tool_purpose(
      does="Summarize or explain the current project without changing files.",
      when="Routing selected project_info.",
      when_not="The user asked to build, update, or fix project files.",
    ),
    "input_schema": {
      "type": "object",
      "properties": {"prompt": {"type": "string"}},
      "required": ["prompt"],
      "additionalProperties": False,
    },
    "output_schema": {
      "type": "object",
      "properties": {
        "reply": {"type": "string"},
        "project_summary": {"type": "object"},
      },
    },
    "approval_required": False,
    "approval_policy": "none",
    "execution_order": 2,
  },
  {
    "name": "generate_website_files",
    "purpose": _tool_purpose(
      does="Create React + Tailwind files from an approved blueprint.",
      when="Legacy artifact generation path after planning is complete.",
      when_not="Streaming File Agent fast path is active for this turn.",
    ),
    "input_schema": {
      "type": "object",
      "properties": {
        "website_blueprint": {"type": "object"},
        "sections": {"type": "array", "items": {"type": "object"}},
      },
      "required": ["website_blueprint", "sections"],
      "additionalProperties": True,
    },
    "output_schema": {
      "type": "object",
      "properties": {"files": {"type": "array", "items": {"type": "object"}}},
    },
    "approval_required": False,
    "approval_policy": "preview",
    "execution_order": 4,
  },
  {
    "name": "validate_generated_website",
    "purpose": _tool_purpose(
      does="Validate generated sections, files, responsiveness, and accessibility.",
      when="After artifact JSON is produced and before commit or preview.",
      when_not="No generated_website artifact exists yet.",
    ),
    "input_schema": {
      "type": "object",
      "properties": {"generated_website": {"type": "object"}},
      "required": ["generated_website"],
      "additionalProperties": False,
    },
    "output_schema": {
      "type": "object",
      "properties": {
        "status": {"type": "string"},
        "issues": {"type": "array", "items": {"type": "string"}},
      },
    },
    "approval_required": False,
    "approval_policy": "none",
    "execution_order": 5,
  },
]

# ---------------------------------------------------------------------------
# Runtime action descriptions (supervisor loop)
# ---------------------------------------------------------------------------

RUNTIME_ACTION_DESCRIPTIONS: dict[str, str] = {
  "READ_PROJECT_FILES": _tool_purpose(
    does="Read all supported project files into runtime state.",
    when="Intake before planning or scoped updates on an existing project.",
    when_not="Files are already loaded for this loop iteration.",
  ),
  "LOAD_PROJECT_MEMORY": _tool_purpose(
    does="Load persisted project and user memory checkpoints.",
    when="Before prompt analysis, planning, or update scoping.",
    when_not="Memory was loaded in the same bootstrap pass.",
  ),
  "RUN_PARALLEL_PROJECT_BOOTSTRAP": _tool_purpose(
    does="Read project files and load memory in parallel.",
    when="Starting the full runtime loop intake phase.",
    when_not="Bootstrap already completed for this run.",
  ),
  "RUN_UPDATE_ANALYST": _tool_purpose(
    does="Classify the update into the smallest safe mode and candidate files.",
    when="Routing intent is website_update on an existing project.",
    when_not="This is a greenfield website_generation turn.",
  ),
  "RUN_ERROR_HANDLING_AGENT": _tool_purpose(
    does="Triage build, runtime, API, or database errors and suggest root-cause files.",
    when="The user message includes an error log or failure description.",
    when_not="The user only asks what the error means without requesting a fix.",
  ),
  "RUN_SCOPED_UPDATE_AGENT": _tool_purpose(
    does="Patch only backend-approved existing files.",
    when="Update analysis selected scoped mode with approved paths.",
    when_not="A full regeneration or streaming fast path is already handling the turn.",
  ),
  "RUN_PROMPT_ANALYST": _tool_purpose(
    does="Build a structured brief from prompt, files, and memory.",
    when="Planning phase before RUN_PLANNER or code generation.",
    when_not="A valid brief already exists for this run.",
  ),
  "RUN_PLANNER": _tool_purpose(
    does="Create sections, layout, interactions, and quality-gate plan.",
    when="A brief exists and code generation has not started.",
    when_not="Streaming fast path skips full planning.",
  ),
  "RUN_DYNAMIC_AGENT_PLANNER": _tool_purpose(
    does="Plan dynamic specialist agents and guarded workflow tasks.",
    when="Dynamic generation is enabled and capability tasks need decomposition.",
    when_not="No dynamic agents are required for this prompt.",
  ),
  "RUN_DYNAMIC_SPECIALISTS": _tool_purpose(
    does="Execute bounded content, component, or domain specialists.",
    when="Dynamic workflow plan assigned specialist tasks.",
    when_not="Specialists already completed or dynamic generation is disabled.",
  ),
  "RUN_UX_REVIEW_AGENT": _tool_purpose(
    does="Review the plan for UX, conversion, and responsive risks.",
    when="A plan exists and pre-code review is required.",
    when_not="Parallel review agents already cover UX in this pass.",
  ),
  "RUN_ACCESSIBILITY_AGENT": _tool_purpose(
    does="Review the plan for contrast, semantics, keyboard, and mobile fit.",
    when="A plan exists and accessibility review is required.",
    when_not="Parallel review agents already cover accessibility in this pass.",
  ),
  "RUN_PARALLEL_REVIEW_AGENTS": _tool_purpose(
    does="Run UX and accessibility reviews in parallel.",
    when="Both reviews are needed before code generation.",
    when_not="Either review already completed.",
  ),
  "RUN_CODE_AGENT": _tool_purpose(
    does="Generate strict project artifact JSON from the approved plan.",
    when="Plan and reviews are ready; files are not committed yet.",
    when_not="Streaming File Agent or scoped update already produced files.",
  ),
  "RUN_DYNAMIC_PATCH_INTEGRATOR": _tool_purpose(
    does="Merge validated dynamic-agent candidate patches into the artifact.",
    when="Dynamic specialists returned candidate file changes.",
    when_not="No dynamic candidate changes exist.",
  ),
  "MATERIALIZE_CANDIDATE_FILES": _tool_purpose(
    does="Write candidate files to the workspace and stream them to the UI.",
    when="Candidate artifact files exist and preview preparation is next.",
    when_not="Files are already materialized for this candidate set.",
  ),
  "RUN_REPAIR_AGENT": _tool_purpose(
    does="Repair or regenerate the artifact using the latest failure.",
    when="Validation, preview, or runtime QA failed within retry budget.",
    when_not="No failure exists or repair budget is exhausted.",
  ),
  "VALIDATE_PROJECT_ARTIFACT": _tool_purpose(
    does="Validate artifact shape, required files, theme, sections, and paths.",
    when="Candidate files exist and before preview or commit.",
    when_not="Artifact already validated successfully in this pass.",
  ),
  "BUILD_STAGED_PROJECT_PREVIEW": _tool_purpose(
    does="Build a Vite preview from candidate files before commit.",
    when="Validation passed and preview is required for this change.",
    when_not="Backend-only change skips preview or preview already built.",
  ),
  "RUN_PREVIEW_VISUAL_QA": _tool_purpose(
    does="Run preview integrity QA on the staged build.",
    when="Staged preview build succeeded.",
    when_not="Preview was skipped or QA already passed.",
  ),
  "WRITE_PROJECT_FILES": _tool_purpose(
    does="Commit staged files to the project store and linked local folder.",
    when="Validation, preview, and QA gates passed.",
    when_not="Any completion gate failed or files are already committed.",
  ),
  "PERSIST_PROJECT_MEMORY": _tool_purpose(
    does="Persist generation memory and runtime summary.",
    when="Files are committed and the run is finishing.",
    when_not="Commit has not completed or memory was already persisted.",
  ),
  "DONE": _tool_purpose(
    does="Stop the supervisor runtime loop.",
    when="Completion proof shows commit and memory persistence succeeded.",
    when_not="Any required gate or backend tool step is still outstanding.",
  ),
}

# ---------------------------------------------------------------------------
# Backend / platform tool descriptions (executable registry)
# ---------------------------------------------------------------------------

WEBSITE_TOOL_DESCRIPTIONS: dict[str, str] = {
  "READ_PROJECT_FILES": RUNTIME_ACTION_DESCRIPTIONS["READ_PROJECT_FILES"],
  "LOAD_PROJECT_MEMORY": RUNTIME_ACTION_DESCRIPTIONS["LOAD_PROJECT_MEMORY"],
  "PERSIST_PROJECT_MEMORY": RUNTIME_ACTION_DESCRIPTIONS["PERSIST_PROJECT_MEMORY"],
  "WRITE_PROJECT_FILES": RUNTIME_ACTION_DESCRIPTIONS["WRITE_PROJECT_FILES"],
  "VALIDATE_PROJECT_ARTIFACT": RUNTIME_ACTION_DESCRIPTIONS["VALIDATE_PROJECT_ARTIFACT"],
  "BUILD_PROJECT_PREVIEW": _tool_purpose(
    does="Build a Vite preview for already saved project files.",
    when="Preview is needed after files exist in the project store.",
    when_not="Use BUILD_STAGED_PROJECT_PREVIEW for uncommitted candidate files.",
  ),
  "BUILD_STAGED_PROJECT_PREVIEW": RUNTIME_ACTION_DESCRIPTIONS["BUILD_STAGED_PROJECT_PREVIEW"],
  "RUN_PREVIEW_VISUAL_QA": RUNTIME_ACTION_DESCRIPTIONS["RUN_PREVIEW_VISUAL_QA"],
  "SYNC_LOCAL_PROJECT": _tool_purpose(
    does="Pull from or push to the linked local project folder.",
    when="The project has a linked local_path and sync is requested.",
    when_not="No linked local workspace exists.",
  ),
}

PLATFORM_TOOL_DESCRIPTIONS: dict[str, str] = {
  "READ_FILE": _tool_purpose(
    does="Read one project file by path.",
    when="You need exact current source before str_replace or a targeted edit.",
    when_not="Use LIST_DIR to discover paths or READ_PROJECT_FILES for full load.",
  ),
  "READ_FILE_RANGE": _tool_purpose(
    does="Read a line range from one project file.",
    when="Only part of a large file is needed.",
    when_not="The whole file is small enough for READ_FILE.",
  ),
  "LIST_DIR": _tool_purpose(
    does="List file and folder names under a project path prefix.",
    when="Discovering structure or finding which files exist.",
    when_not="You already know the exact path to read or edit.",
  ),
  "GLOB_SEARCH": _tool_purpose(
    does="Find project files matching a glob pattern.",
    when="Searching by filename pattern across the project.",
    when_not="A simple directory listing is enough.",
  ),
  "SEARCH_CODEBASE": _tool_purpose(
    does="Search project file contents for a query string.",
    when="Finding symbols, strings, or references across files.",
    when_not="You already know the target file path.",
  ),
  "STR_REPLACE": _tool_purpose(
    does="Replace an exact substring once in a staged project file.",
    when="Making a small, exact edit to existing content.",
    when_not="Creating a new file or rewriting most of a file (use write_file).",
  ),
  "APPLY_PATCH": _tool_purpose(
    does="Apply unified-diff patches to staged project files.",
    when="Multiple structured patches are available.",
    when_not="A single exact replacement is enough.",
  ),
  "RUN_TERMINAL": _tool_purpose(
    does="Run an allowlisted terminal command in the linked workspace.",
    when="Tests, installs, or diagnostics require a shell command.",
    when_not="File reads or writes alone can solve the task.",
  ),
  "GIT_STATUS": _tool_purpose(
    does="Show git status for the linked workspace.",
    when="Inspecting working tree state before commit or diff.",
    when_not="No linked git workspace exists.",
  ),
  "GIT_DIFF": _tool_purpose(
    does="Show git diff for the linked workspace.",
    when="Reviewing unstaged or staged changes.",
    when_not="No linked git workspace exists.",
  ),
  "GIT_COMMIT": _tool_purpose(
    does="Commit changes in the linked workspace.",
    when="User-approved git commit is required in the local folder.",
    when_not="approved=true is missing or WRITE_PROJECT_FILES should be used instead.",
  ),
  "RUN_TESTS": _tool_purpose(
    does="Run project tests in the linked workspace.",
    when="Verifying behavior after code changes.",
    when_not="Lint or validation alone is sufficient.",
  ),
  "RUN_LINT": _tool_purpose(
    does="Run lint or syntax checks on project files.",
    when="Checking style or syntax after edits.",
    when_not="Full test suite is explicitly required.",
  ),
}

STREAMING_FILE_TOOL_DESCRIPTIONS: dict[str, str] = {
  "read_file": _tool_purpose(
    does="Read one project file and return its content.",
    when="Before str_replace or write_file on an existing path, or to inspect current implementation.",
    when_not="Discovering which files exist (use list_files) or creating a brand-new path without inspection.",
  ),
  "list_files": _tool_purpose(
    does="List file and folder names under a directory prefix.",
    when="Exploring project structure or finding paths under src/ or a subdirectory.",
    when_not="You already know the exact file path to read or edit.",
  ),
  "write_file": _tool_purpose(
    does="Create or overwrite a project file with full content. Side effect: stages and persists the file.",
    when="Creating a new file or replacing most of an existing file.",
    when_not="Making a small exact edit (use str_replace) or editing src/worktual-*-shim.* files.",
  ),
  "str_replace": _tool_purpose(
    does="Replace one exact old_string with new_string in a file. Side effect: stages and persists the file.",
    when="Making a small, precise edit and you have the exact text to match.",
    when_not="old_string appears zero or multiple times, the file is new, or a full rewrite is simpler.",
  ),
}

# Compact descriptions sent to Gemini on every tool-loop step (lower latency, clearer edits).
STREAMING_FILE_GEMINI_TOOL_DESCRIPTIONS: dict[str, str] = {
  "read_file": (
    "Read one file by path. Use before editing an existing file so str_replace old_string matches exactly."
  ),
  "list_files": (
    "List names under a directory prefix (e.g. src/pages). Use only when the target path is unknown."
  ),
  "write_file": (
    "Create a new file or replace an entire file. Do not use for small edits—use str_replace instead."
  ),
  "str_replace": (
    "Replace one exact old_string with new_string in an existing file. Read the file first; old_string must match once."
  ),
  "search_codebase": (
    "Search the project for code related to a natural-language query. Returns matching file paths and snippets."
  ),
}

REAL_BACKEND_TOOL_REGISTRY_ENTRIES: list[dict[str, Any]] = [
  {"name": "READ_PROJECT_FILES", "purpose": WEBSITE_TOOL_DESCRIPTIONS["READ_PROJECT_FILES"], "execution_order": 1, "source": "backend.agent_tools"},
  {"name": "LOAD_PROJECT_MEMORY", "purpose": WEBSITE_TOOL_DESCRIPTIONS["LOAD_PROJECT_MEMORY"], "execution_order": 2, "source": "backend.agent_tools"},
  {"name": "VALIDATE_PROJECT_ARTIFACT", "purpose": WEBSITE_TOOL_DESCRIPTIONS["VALIDATE_PROJECT_ARTIFACT"], "execution_order": 4, "source": "backend.agent_tools"},
  {"name": "BUILD_STAGED_PROJECT_PREVIEW", "purpose": WEBSITE_TOOL_DESCRIPTIONS["BUILD_STAGED_PROJECT_PREVIEW"], "execution_order": 5, "source": "backend.agent_tools"},
  {"name": "WRITE_PROJECT_FILES", "purpose": WEBSITE_TOOL_DESCRIPTIONS["WRITE_PROJECT_FILES"], "execution_order": 6, "source": "backend.agent_tools"},
  {"name": "BUILD_PROJECT_PREVIEW", "purpose": WEBSITE_TOOL_DESCRIPTIONS["BUILD_PROJECT_PREVIEW"], "execution_order": 7, "source": "backend.agent_tools"},
  {"name": "RUN_PREVIEW_VISUAL_QA", "purpose": WEBSITE_TOOL_DESCRIPTIONS["RUN_PREVIEW_VISUAL_QA"], "execution_order": 8, "source": "backend.agent_tools"},
  {"name": "PERSIST_PROJECT_MEMORY", "purpose": WEBSITE_TOOL_DESCRIPTIONS["PERSIST_PROJECT_MEMORY"], "execution_order": 9, "source": "backend.agent_tools"},
]
