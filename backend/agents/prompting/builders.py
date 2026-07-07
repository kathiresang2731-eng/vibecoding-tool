from __future__ import annotations

from .contracts import (
  CONVERSATION_RESPONSE_CONTRACT,
  DOCUMENT_ARTIFACT_OUTPUT_CONTRACT,
  DOMAIN_RESEARCH_RESPONSE_CONTRACT,
  DYNAMIC_AGENT_DEFINITION_CONTRACT,
  DYNAMIC_TASK_DECOMPOSITION_CONTRACT,
  DYNAMIC_WORKFLOW_PLAN_CONTRACT,
  ROUTING_RESPONSE_CONTRACT,
  SCOPED_UPDATE_PATCH_CONTRACT,
  SIMPLE_CODE_ARTIFACT_OUTPUT_CONTRACT,
  UPDATE_ANALYSIS_CONTRACT,
  WEBSITE_ARTIFACT_OUTPUT_CONTRACT,
)
from .policies import prompt_policy_block

def build_intent_analysis_prompt(user_prompt: str) -> str:
  return f"""
User message:
{user_prompt.strip()}

Analyze the user intent for a dynamic web/full-stack project runtime. Identify
whether the request is conversation-only, website/frontend generation, backend
generation, database/API work, existing project update, or a complex app build.
Return the existing route_generation_action contract.

Shared prompt policy:
{prompt_policy_block(include_generation=False, include_update=False)}

{ROUTING_RESPONSE_CONTRACT}
"""


def build_update_analysis_prompt(
  user_prompt: str,
  *,
  project_file_index: list[dict],
  candidate_context: list[dict],
  memory_context: list[dict],
  error_diagnosis: dict | None = None,
) -> str:
  return f"""
User update request:
{user_prompt.strip()}

Existing project file index:
{project_file_index}

Relevant code-search matches:
{candidate_context}

Relevant project memory:
{memory_context}

Error handling agent diagnosis:
{error_diagnosis or {}}

You are the Update Analysis Agent. Decide the smallest safe execution mode for
this existing project update before any planning, specialist, review, or code
agent is called.

Shared prompt policy:
{prompt_policy_block(include_generation=False, include_update=True)}

Rules:
- Code-search entries with match_type=project_ui_knowledge are structural
  evidence extracted from the live project. Use their path, element kind,
  visible text, route, handler, target, and purpose to identify the exact
  rendered element the user referenced. They localize code ownership but do
  not replace your semantic intent decision.
- When the user quotes or closely identifies visible page text, prioritize its
  project_ui_knowledge owner as the primary target. Add router, shared state,
  API, or destination files only when the requested behavior actually crosses
  those boundaries.
- If Error handling agent diagnosis is non-empty, treat it as the primary
  debugging signal. Prefer update_mode=bug_fix, execution_strategy=scoped_model_patch,
  and candidate files from error_diagnosis.candidate_files unless the user is
  clearly requesting a new feature. Do not ask the user to repeat stack traces
  or console errors already present in the prompt.
- A single Universal Error Handling Agent orchestrates diagnostics for all
  programming languages. Use its language/category result to apply the right
  language-specific fix strategy: JavaScript/TypeScript runtime and data-shape
  checks, Python/FastAPI route/import/schema checks, SQL migration/schema
  checks, or Java/Go/PHP/Ruby/.NET framework checks.
- Select targeted_patch for isolated text, theme, configuration, constant, or
  known-file changes.
- Select bug_fix for runtime errors, build errors, missing variables/imports,
  broken behavior, or a specific defect.
- Select feature_patch for adding or modifying a bounded feature while
  preserving the existing website structure and design.
- Treat backend/API/database requests as first-class project updates. If the
  user asks for FastAPI, Python backend, PostgreSQL, database models, schemas,
  migrations, seed data, REST endpoints, auth, services, or API integration,
  choose candidate files from backend/*, app/*, api/*, server/*, database/*,
  db/*, migrations/*, scripts/*, tests/*, and root dependency/config files
  where available. Infer exact file names from existing project conventions,
  frontend modules/pages, domain entities, framework conventions, and the file
  index. Do not choose backend file names from a static backend-provided list.
- Select full_regeneration only when the user explicitly asks to rebuild,
  replace, redesign, or regenerate the entire website.
- Select needs_clarification when the requested target or desired result is
  ambiguous enough that editing could damage unrelated code.
- Never select full_regeneration for a bug fix, text update, theme update,
  pagination update, configuration change, or isolated feature request.
- candidate_files must contain only paths present in the existing project file
  index. Select at most 4 files and prefer files supported by code-search
  matches.
- For feature_patch, populate feature_plan with the semantic feature name,
  feature type, requested items, and interaction. The feature name should be a
  reusable PascalCase code component/page name inferred from the user's
  meaning, not from generic words like "update", "module", "website", or
  "page".
- candidate_new_files may contain at most 2 new source/helper paths only for
  feature_patch requests that need a small or medium new component/helper,
  backend, API, database, migration, seed, or test file to keep the existing
  integration file small. Infer the exact path from the existing project
  structure, frontend feature names, requested framework, domain entity names,
  import conventions, and routing conventions. Leave it empty for
  targeted_patch, bug_fix, full_regeneration, and clarification.
- Treat new-file selection as a dedicated New File Requirement Agent decision:
  decide whether a new file is actually required, name the exact new path, and
  verify which existing file will import, route, or render that new file.
- For backend/database updates, derive entities, tables, schemas, route names,
  and module names from the frontend pages, forms, mock data, state names,
  visible workflows, and user request. Never invent a generic static schema
  when the frontend already reveals the domain model.
- If candidate_new_files is non-empty, candidate_files must still include the
  existing source file(s) that will import or render the new file.
- Populate new_file_requirements when candidate_new_files is non-empty. Every
  planned file must include a reason, kind, integration_file, import_name, and
  import_path_from_integration. The integration_file must be present in
  candidate_files and the import path must be relative to that file.
- For broad requests with multiple independent changes, populate
  scoped_update_tasks with 2-4 ordered steps. Each step must be small enough to
  patch safely, include the existing candidate_files it needs, and include only
  the candidate_new_files needed by that step.
- For requests that contain a preamble followed by a list of desired pages,
  tabs, sections, or modules, every listed item must appear in
  scoped_update_tasks. If the list has more than 4 items, group related items
  into 2-4 ordered steps instead of omitting or truncating list items.
- required_agents must contain only the minimum agents needed. A targeted patch
  or bug fix never requires content, domain research, UX review, accessibility
  review, inventory, checkout, or full dynamic workflow agents.
- Select execution_strategy=deterministic_patch only when request_kind is
  brand_name_update, document_title_update, cta_text_update, or
  pagination_page_size_update AND targeted_patch includes the concrete value
  needed to apply the update safely.
- Select execution_strategy=scoped_model_patch for theme_color_update,
  style_reference_update, bug_fix, feature_patch, and other bounded
  existing-project changes.
- Select execution_strategy=full_dynamic_workflow only when update_mode is
  full_regeneration and the user explicitly requested a complete rebuild.
- Select execution_strategy=clarify when update_mode is needs_clarification.
- Preserve all unrelated files, layout, content, components, data, styling, and
  behavior.
- allow_full_regeneration must be true only when update_mode is
  full_regeneration and the user explicitly requested a complete rebuild.
- For brand/title/CTA updates, targeted_patch.new_value must contain the exact
  user-requested replacement text. targeted_patch.old_value is required when
  the user says "from A to B"; otherwise leave old_value empty.
- For theme/color/style updates, do not depend on backend static color mapping.
  Treat the existing source files as the authority. Select the shared theme/CSS
  files plus the rendered page/component files that visibly own the current
  palette, and use scoped_model_patch so the code-writing agent can make real
  project-aware edits.
- For critical UI interaction bugs, use model/code-context reasoning to extract
  a concrete interaction contract: component, trigger, expected behavior,
  source page/component, target page or route when present, and confidence.
  Set request_kind=interaction_wiring_update when the user reports a broken
  click, submit, navigation, handler, state transition, modal, dropdown, form,
  tab, filter, or route behavior. Select the likely source owner, route owner,
  and target page/component from the actual file index and code-search context.
  Do not rely on fixed prompt words; infer from the user's meaning and project
  code.
- For pagination updates, targeted_patch.page_size must contain the requested
  integer. Treat "increase each page size to 25" as an existing-project update,
  not a request for website details.
- If the user asks a follow-up like "change the main files also" and the exact
  prior target cannot be recovered from project memory, return
  needs_clarification instead of regenerating or guessing.

{UPDATE_ANALYSIS_CONTRACT}
"""


def build_scoped_update_patch_prompt(
  user_prompt: str,
  *,
  update_analysis: dict,
  candidate_files: list[dict],
  code_search_matches: list[dict],
) -> str:
  return f"""
User update request:
{user_prompt.strip()}

Validated update analysis:
{update_analysis}

Allowed existing files with complete current contents:
{candidate_files}

Relevant code-search matches:
{code_search_matches}

You are the Scoped Update Agent. Make the smallest complete code change that
satisfies the request across frontend, backend, database, or integration files.

Shared prompt policy:
{prompt_policy_block(include_generation=False, include_update=True)}

Rules:
- Treat this as one micro-step in a sequential coding workflow, like a coding
  agent applying a small reviewed patch. Do not solve every broader enhancement
  in this single response unless the current prompt explicitly names only one
  tiny change.
- Modify only the current approved candidate file for this step. If another
  existing project file is required for this same subtask and its contents were
  not supplied, return needs_scope_expansion with the exact path in
  requested_files. Do not ask the user for file-edit permission.
- Prefer line-level SEARCH/REPLACE edits over complete changed_files. Use
  changed_files only for a genuinely new file or when exact edits are unsafe.
- You are an expert full-stack development agent. When modifying an existing codebase,
  do not guess line numbers or use broken tool calls. Instead, output every
  existing-file code modification as an explicit SEARCH/REPLACE block.
- For backend/API/DB work, preserve the existing frontend unless integration is
  explicitly required. Analyze the current frontend structure, pages, forms,
  mock data, imports, state names, and workflows to infer backend modules,
  API resources, database entities, relationships, schema fields, and file
  names. Use existing project naming/folder conventions whenever present.
- For FastAPI + PostgreSQL requests, create or update only the minimal files
  needed for a runnable API, but let the model decide the exact module names
  from frontend/domain analysis and the existing folder layout. Include app
  entrypoint, DB/session config, domain models, request/response schemas,
  service/CRUD logic, routes, dependency/config files, env example, and optional
  seed/test files only when they are needed. Add frontend fetch integration only
  when the user asks to connect the UI to the API.
- For theme/color/style/visual updates, act as the code-writing agent, not a
  static color replacer. Inspect the allowed source file content, identify the
  real design system, CSS variables, Tailwind classes, inline styles, gradients,
  and rendered page/component ownership, then patch this file consistently with
  the user's requested visual direction. If another rendered source file owns
  visible old styling and is not included here, return needs_scope_expansion
  with the exact path. Do not rely on backend hard-coded palettes or regex
  mappings; reason from the project source.
- For interaction_wiring_update or bug-fix requests with update_analysis.interaction,
  treat that object as the Interaction Contract. It identifies the component,
  trigger, expected behavior, source page/component, and target route/page when
  known. A valid response must be one of: a real edit that wires the interaction,
  needs_scope_expansion with the exact missing owner file, or a concrete
  needs_clarification only when the behavior itself is ambiguous. Never return
  completed with no edits for a high-confidence interaction contract.
- For navigation interaction fixes, inspect the approved source button/handler
  and existing route declarations/imports. Use the project's existing router
  API/pattern; add or update only the minimal import, navigate/link call, and
  onClick/handler code needed to reach the existing target route.
- Follow update_analysis.scoped_edit_plan exactly when present. Treat
  scoped_edit_plan.scope_contract.allowed_existing_paths as the only editable
  existing paths, scoped_edit_plan.scope_contract.approved_new_paths as the only
  creatable new paths, and scoped_edit_plan.anchors_by_path as the preferred
  exact search anchors.
- Before writing an edit, choose the smallest exact anchor/snippet that contains
  the modification point. Return the actual edit JSON, not a plan or summary of
  what should be edited.
- Return only files from candidate_files or update_analysis.candidate_new_files.
  Never invent another path.
- You may return a new file in changed_files only when the exact path appears
  in update_analysis.candidate_new_files. You must also patch an existing
  candidate_files path to import or render the new file.
- Prefer edits with explicit SEARCH/REPLACE blocks for small or medium changes.
  Keep each SEARCH snippet as small as possible while remaining unique.
- For every existing-file edit, return edits[].search_replace in this exact
  block format inside the JSON string:
  <<<<<<< SEARCH
  [old code snippet copied exactly from the allowed file]
  =======
  [new updated code snippet]
  >>>>>>> REPLACE
- The backend will parse edits[].search_replace into exact search and replace
  values. Do not use line numbers, patches, markdown diffs, tool calls, or
  partial-update artifacts.
- Use changed_files with complete contents only when the requested change
  cannot be represented safely as exact edits. Never return the same path in
  both edits and changed_files.
- Never return a complete replacement of src/App.jsx for a bounded feature,
  text, theme, layout, or bug-fix update unless the user explicitly requested a
  full rebuild. Large App.jsx rewrites are rejected by the Python guardrail.
- Do not regenerate, redesign, rebrand, or rewrite unrelated website content.
- Preserve the existing domain, layout, styling, components, product data, and
  behavior unless the user explicitly requested changing them.
- For a bug fix, repair the reported root cause only. Ignore browser-extension
  warnings unless they are the actual application failure.
- If a required existing project file is not available, return
  needs_scope_expansion with its exact path. Return needs_clarification only
  when the user's intended result or target is genuinely ambiguous.
- Never ask the user to provide source, JSX, file contents, code snippets, or
  code segments from allowed files. The backend already provided the approved
  source context; use the best available exact anchor or return a no-patch
  blocked response.
- If scoped_edit_plan contains anchors for an allowed file, do not return an
  empty blocked response. Use the best exact anchor and return one minimal edit.
- Every string value must be valid JSON. Escape double quotes inside code
  snippets and encode line breaks inside search_replace, search, replace, and
  code values as \\n. Never place raw multiline code outside JSON strings.
- Do not include long narrative summaries. Put all patch content only in
  edits or changed_files.
- Do not return markdown or explanations outside the JSON contract.

{SCOPED_UPDATE_PATCH_CONTRACT}
"""


def build_task_decomposition_prompt(user_prompt: str, *, routing_result: dict, brief: dict) -> str:
  return f"""
User project prompt:
{user_prompt.strip()}

Routing result:
{routing_result}

Requirement brief:
{brief}

You are the Task Decomposer Agent. Break the request into capability tasks for a
dynamic web, backend, database, or full-stack project workflow.

Shared prompt policy:
{prompt_policy_block(include_generation=True, include_update=True)}

Rules:
- Include only concrete tasks that improve the generated project.
- Use RUN_DYNAMIC_SPECIALISTS for domain-specific capabilities such as
  checkout_flow, crm_pipeline, rbac, booking_workflow, inventory, analytics,
  api_design, database_schema, backend_service, auth_backend, migrations, and
  frontend_backend_integration.
- Never assign direct filesystem writes to a dynamic task.
- Do not create tasks for core runtime responsibilities: routing, requirement
  analysis, task decomposition, workflow planning, agent registry, supervision,
  memory persistence, code generation, validation, preview build, visual QA, or
  repair. Python and built-in agents own those phases.
- Validation, preview build, visual QA, file commit, and memory persistence are
  enforced by Python and must retain their guarded runtime actions.
- Keep dependencies acyclic.

{DYNAMIC_TASK_DECOMPOSITION_CONTRACT}
"""


def build_dynamic_agent_definition_prompt(task: dict, *, domain: str) -> str:
  return f"""
Domain:
{domain}

Capability task:
{task}

You are the Agent Registry Agent. Define a reusable specialist agent for this
missing capability.

Shared prompt policy:
{prompt_policy_block(include_generation=True, include_update=False)}

Rules:
- The agent may analyze, plan, or recommend structured implementation details.
- The agent may request only READ_PROJECT_FILES and LOAD_PROJECT_MEMORY.
- Project ID and user identity are bound by Python, never supplied or trusted
  from model arguments.
- The agent may propose complete candidate file changes for Python validation
  and integration, but it must not write files directly or request deletes.
- Python owns file writes, validation, preview builds, QA, and memory writes.
- Keep the agent focused on the requested capability.
- The definition must be reusable across projects. Do not hard-code the current
  brand, business name, user prompt, file paths, palette, product data, or
  one-off project context into the agent id, name, role, or system prompt.
- Do not define agents for core runtime responsibilities such as routing,
  memory persistence, code generation, validation, preview build, visual QA,
  repair, task decomposition, workflow planning, or supervision.

{DYNAMIC_AGENT_DEFINITION_CONTRACT}
"""


def build_workflow_planning_prompt(tasks: list[dict], assignments: list[dict]) -> str:
  return f"""
Capability tasks:
{tasks}

Agent assignments:
{assignments}

You are the Workflow Planner Agent. Propose safe parallel task groups while
preserving all task dependencies. Code generation must wait for planning.
Validation, preview build, visual QA, commit, and memory persistence must run in
strict order. DONE is allowed only after every completion-proof item is true.

Shared prompt policy:
{prompt_policy_block(include_generation=True, include_update=True)}

{DYNAMIC_WORKFLOW_PLAN_CONTRACT}
"""


def build_domain_research_prompt(user_prompt: str, fallback_context: dict) -> str:
  return f"""
User website prompt:
{user_prompt.strip()}

Fallback category hint (keywords only — not a layout template):
{fallback_context}

Use Google Search grounding when useful. You are the domain research agent: decide the
layout, page structure, visual style, interactions, entities, and sample content based on
the user prompt and category — do not copy preset section lists or product catalogs from
code templates.

Shared prompt policy:
{prompt_policy_block(include_generation=True, include_update=False)}

If the prompt names a category (e-commerce, farm, restaurant, SaaS, portfolio, clinic,
CRM, etc.), research modern UX patterns for that category and propose a concrete,
generation-ready plan. Return status "applied" only when you have a complete LLM-authored
plan. Leave sample_products empty unless the user needs illustrative catalog items.

{DOMAIN_RESEARCH_RESPONSE_CONTRACT}
"""


def build_routing_prompt(user_prompt: str) -> str:
  return f"""
User message:
{user_prompt.strip()}

You are the route_generation_action tool for Worktual AI Dev.
Return only the routing JSON. Classify the current user message, ignoring older
conversation context unless the message explicitly refers to it.

Infer the complete speech act; never route from isolated keywords or punctuation.
Intents:
- "greeting": small talk.
- "question": informational, conceptual, capability, or feasibility question; no file writes.
- "general_query": explanation, advice, comparison, or brainstorming.
- "web_search": explicit online research or time-sensitive external facts.
- "needs_more_detail": an intended build/update whose required outcome is still ambiguous.
- "project_info": inspect or explain the CURRENT project, files, logs, errors, or prior run;
  conversation-only, no confirmation, and no file writes.
- "simple_code": standalone program/function/script, not a website or current-project change.
- "document_artifact": create/save documentation, README, report, plan, research brief,
  CSV, Markdown, TXT, or PDF-ready Markdown source; not a website or app.
- "website_generation": concrete new website/app/backend/API/database project.
- "website_update": an authorized, actionable change to the current project, including a
  previous enhancement idea, feature, fix, backend, database, page, interaction, or theme.

Semantic examples:
- "I want to change the website theme. Is it possible?" => question
- "Change the website theme to red" => website_update
- "Can you change the website theme to red?" => website_update
- "give me the information about this website" => project_info
- "understand this error" => project_info
- "write a code for reverse number in python" => simple_code
- "create README.md for this API" => document_artifact
- "make a CSV checklist for QA testing" => document_artifact
- "research vector databases and save a plan as markdown" => document_artifact
- "implement those enhancement ideas" => website_update
- "write a python backend with FastAPI and Postgres for this website" => website_update
- "create a FastAPI backend with PostgreSQL for contacts, deals, and projects" => website_generation
- "Search the web for current React releases" => web_search

Use website_update only for an actionable request to perform changes. Use project_info
when the user only asks to understand, explain, analyze, or summarize current project
state. A question about whether a change is possible is not authorization to execute it.
backend route and PostgreSQL connection work follows the same new-project versus
current-project distinction.

Exact next_action/next_tool values:
- greeting -> respond_and_collect_website_brief / handle_greeting
- question -> answer_question / answer_question
- general_query -> answer_general_query / answer_general_query
- web_search -> search_web / search_web
- needs_more_detail -> request_website_details / request_website_details
- project_info -> summarize_current_project / summarize_current_project
- simple_code -> write_standalone_code_file / generate_simple_code_file
- document_artifact -> write_document_artifact / generate_document_artifact
- website_generation -> generate_website / analyze_prompt
- website_update -> update_website / analyze_update_request

For needs_more_detail, populate missing_fields and write one precise
clarification_question. For every other intent, return an empty missing_fields
array and an empty clarification_question.

{ROUTING_RESPONSE_CONTRACT}
"""


def build_routing_repair_prompt(user_prompt: str, invalid_response: dict) -> str:
  return f"""
User message:
{user_prompt.strip()}

The previous route_generation_action output did not match the required enum
contract:
{invalid_response}

Repair the output. Return only a valid route_generation_action JSON object.

Shared prompt policy:
{prompt_policy_block(include_generation=False, include_update=False)}

Allowed exact values:
- intent: "greeting", "question", "general_query", "web_search", "needs_more_detail", "project_info", "simple_code", "document_artifact", "website_generation", or "website_update"
- for "greeting": next_action "respond_and_collect_website_brief", next_tool "handle_greeting"
- for "question": next_action "answer_question", next_tool "answer_question"
- for "general_query": next_action "answer_general_query", next_tool "answer_general_query"
- for "web_search": next_action "search_web", next_tool "search_web"
- for "needs_more_detail": next_action "request_website_details", next_tool "request_website_details"
- for "project_info": next_action "summarize_current_project", next_tool "summarize_current_project"
- for "simple_code": next_action "write_standalone_code_file", next_tool "generate_simple_code_file"
- for "document_artifact": next_action "write_document_artifact", next_tool "generate_document_artifact"
- for "website_generation": next_action "generate_website", next_tool "analyze_prompt"
- for "website_update": next_action "update_website", next_tool "analyze_update_request"
- missing_fields and clarification_question are populated only for needs_more_detail

{ROUTING_RESPONSE_CONTRACT}
"""


def build_conversation_response_prompt(
  user_prompt: str,
  *,
  intent: str,
  selected_tool: str,
  routing_result: dict,
) -> str:
  return f"""
User message:
{user_prompt.strip()}

Routing tool result:
{routing_result}

Selected tool:
{selected_tool}

Write the assistant response for Worktual AI Dev.

Shared prompt policy:
{prompt_policy_block(include_generation=False, include_update=False)}

Instructions:
- Do not generate a website for this turn.
- Do not say there was an error.
- If intent is greeting, greet naturally in the user's language/tone, acknowledge their
  message specifically, and ask what they want to build. Vary your wording every time.
  Do not copy a stock phrase like "Share the website or app you want to build...".
- If intent is question, answer the user's actual question directly. For a
  feasibility question, explain what is possible and ask whether the user wants
  the change applied; do not claim that work has started and do not write files.
- If intent is general_query, provide a direct, useful answer without forcing the
  user into a website brief or suggesting that code execution has started.
- If intent is web_search, answer from Google Search grounding, distinguish
  current facts from inference, and include concise source links when available.
  Do not modify project files.
- If intent is needs_more_detail, ask for the missing website details before
  generation starts. When the routing reason says a current-project modification
  lacks a target or expected change, ask specifically for the page/component and
  desired visual or functional change; do not ask for business type or audience.
- If intent is project_info, summarize the CURRENT live website/project from
  the latest code context. Include what the website appears to be, key pages or
  sections, current strengths, gaps, and a concise enhancement plan. If the user
  asks what happened in the last update or generation attempt, answer from
  conversation/progress context: explain what was attempted, what changed or
  failed, and the current project state. Do not start a new update or generation
  turn. Do not ask for confirmation and do not propose that generation has started.
  Use plain readable headings such as Summary, Key areas, Buttons, Notes, and
  Enhancement plan. Do not wrap headings or labels in markdown stars.
- Keep the message concise, warm, and useful.
- Ask for details such as website type, brand/business name, audience, sections,
  visual style, and required features only when the intent is greeting or
  needs_more_detail.
- next_prompt_guidance must contain practical prompts the user can answer next.

Intent:
{intent}

{CONVERSATION_RESPONSE_CONTRACT}
"""


def build_simple_code_prompt(user_prompt: str, pipeline_context: str = "") -> str:
  return f"""
User code request:
{user_prompt.strip()}

You are the Simple Code Writer Agent for Worktual AI Dev.

The Chief Orchestrator selected simple_code because the user asked for a
standalone code/program/function/algorithm/script/snippet. Generate the code
artifact immediately. Do not create a website, React/Vite shell, landing page,
explanation page, or confirmation plan.

Compact code-only policy:
- Current user request is the source of truth.
- Return a safe standalone source file only; no website scaffold, dependency
  shell, markdown, prose-only answer, plan, or unrelated file.
- Use existing_standalone_files only when Prepared backend context explicitly
  includes them for a change/simplify/convert/fix/update request.
- Keep JSON compact and valid. Use safe paths and complete runnable source.
- Do not save or expose secrets, private paths, API keys, or full unrelated
  source as generated content.

Instructions:
- Infer the requested programming language from the prompt. If no language is
  specified, default to Python.
- Infer a clear safe filename from the requested task and language extension
  such as reverse_number.py, armstrong.rs, Palindrome.java, fibonacci.py, or
  main.py when no better name exists.
- Return one complete runnable file unless the user explicitly asks for
  multiple files.
- Return only the newly requested standalone code file(s). Never echo,
  rewrite, remove, or include unrelated existing project files from context.
- If Prepared backend context includes existing_standalone_files and the user
  asks to change, simplify, convert, fix, or update existing code, treat those
  files as the target context even when the user says "this code" or does not
  repeat the filename.
- Ignore unrelated prior project files or chat history unless the current user
  request explicitly names that exact file as the target.
- The code must directly satisfy the user request. Do not return pseudocode,
  markdown, prose-only answers, plans, or TODO placeholders.
- Include a small CLI/input block only when that is natural for the requested
  program. For function-only requests, include the function and a minimal
  `if __name__ == "__main__"` demo only if useful.
- Use standard library code unless the user explicitly asks for a dependency.
- Keep comments short and useful. Prefer simple readable code over clever code.
- Do not create, modify, or reference website files such as index.html,
  package.json, vite.config.js, src/App.jsx, src/main.jsx, src/components/*,
  src/pages/*, or src/theme/*. This is a code-only task.
- Populate generated_website.files with the code file(s). The backend will
  persist those files directly.
- Use generated_website.title/headline/subheadline/sections as code-only
  metadata. preview_html must be an empty string.
- implementation_notes.recommended_next_actions must include how to run the
  generated file, using the inferred language/toolchain.

Prepared backend context:
{pipeline_context}

{SIMPLE_CODE_ARTIFACT_OUTPUT_CONTRACT}
"""


def build_minimal_simple_code_prompt(user_prompt: str, pipeline_context: str = "") -> str:
  return f"""
User code request:
{user_prompt.strip()}

You are the Simple Code Writer Agent.

Compact code-only policy:
- Return one compact JSON object only.
- Generate standalone source code files only.
- Do not create website, React, Vite, package, theme, page, or dependency files.
- Default to Python if the language is not specified.
- Use a clear safe root filename with the correct extension.
- Use relevant learned requirements from Prepared context, but the current user request overrides memory.
- If Prepared context includes an existing standalone file, update that file only.

Prepared context:
{pipeline_context}

Return exactly:
{{
  "generated_website": {{
    "files": [
      {{"path": "filename.ext", "purpose": "short purpose", "code": "complete runnable source"}}
    ]
  }},
  "implementation_notes": {{
    "recommended_next_actions": ["run command"],
    "self_checks": ["short check"]
  }}
}}
"""


def build_document_artifact_prompt(user_prompt: str, pipeline_context: str = "") -> str:
  return f"""
User document request:
{user_prompt.strip()}

You are the Document Artifact Agent for Worktual AI Dev.

The Chief Orchestrator selected document_artifact because the user asked to
create or save documentation, Markdown, TXT, CSV, report, plan, research brief,
or PDF-ready source content. Generate the requested file artifact immediately.
Do not create a website, React/Vite shell, app scaffold, source-code project,
or confirmation plan.

Document-only policy:
- Current user request is the source of truth.
- Return safe document files only: .md, .txt, or .csv.
- If the user asks for PDF, return polished document content and use a .pdf
  filename; the backend will export it to a real PDF file.
- Use a clear safe path such as README.md, docs/plan.md, reports/audit.csv,
  research/brief.md, or notes/summary.txt.
- For CSV, return valid comma-separated content with a header row.
- For Markdown, use readable headings, tables, and checklists where useful.
- For TXT, keep plain text with clear sections.
- Do not include secrets, private paths, API keys, or unrelated project source.
- Do not create or modify website files such as index.html, package.json,
  vite.config.js, src/App.jsx, src/main.jsx, src/components/*, or src/pages/*.
- Populate generated_website.files with the document file(s). The backend will
  persist those files directly.

Prepared backend context:
{pipeline_context}

{DOCUMENT_ARTIFACT_OUTPUT_CONTRACT}
"""


def build_website_prompt(user_prompt: str, adk_mapping: str = "", pipeline_context: str = "", artifact_mode: str = "website_generation") -> str:
  if artifact_mode == "website_update":
    artifact_instruction = (
      "Update the existing project artifact for this prompt. Preserve unrelated "
      "project files, backend behavior, database contracts, and unrelated UI behavior. Return the changed/generated "
      "files needed for the requested update; the backend will merge these files "
      "with the existing project snapshot before preview and commit. Include "
      "src/App.jsx when the main React UI is affected, and include backend/database "
      "files when API, Python, FastAPI, PostgreSQL, models, schemas, migrations, "
      "or services are affected. The backend context includes "
      "the complete current contents for the existing project files; do not ask "
      "the user to provide source code or guess the current code."
    )
  else:
    artifact_instruction = (
      "Generate a complete first project artifact for this prompt. If the user "
      "asks for frontend, return a production-style Vite project structure. If "
      "the user asks for backend/API/database, return a production-style backend "
      "project structure with integration files, not just a React shell."
    )
  policy = prompt_policy_block(include_generation=True, include_update=artifact_mode == "website_update")

  return f"""
User project prompt:
{user_prompt.strip()}

{artifact_instruction}

Shared prompt policy:
{policy}

Your output is only the generated project artifact plus implementation notes.
The Python backend will package this artifact into the Worktual AI Dev backend
flow response after this call.

Provider policy:
- Gemini handled routing, conversation, prompt analysis, planning, UX review,
  accessibility review, supervision, and memory checkpoint decisions.
- Python executed backend tools and owns validation, preview building, QA, file
  commits, and memory writes.
- Do not answer greetings, ask follow-up questions, or perform control-plane
  decisions in this response.
- Current artifact mode: {artifact_mode}.

The generated_website.preview_html field is only a legacy preview surface. The
main backend builds previews from generated files when a frontend build is
applicable, so files are mandatory and preview_html may be an empty string.
Choose the generated file set from the user's requested stack:
- React/frontend or full-stack with frontend: include src/App.jsx as the primary
  React app plus index.html, package.json, src/main.jsx, src/index.css,
  tailwind.config.js, postcss.config.js, src/theme/tokens.js, reusable
  src/components/* files, route-backed src/pages/* files, relevant src/data/*
  files, and src/seo/schema.js when useful.
- Backend/API/database: inspect the current frontend/project context and infer
  backend file names, API resources, database entities, relationships, schemas,
  migrations, config, dependency, seed, and test files from the requested stack,
  existing folder conventions, frontend pages/forms/mock data/state names, and
  domain workflows. Do not rely on a static backend filename list.
- Full-stack backend + frontend: include both sets and connect the React UI to
  the API with fetch/service helpers only where the user requested connection.
For FastAPI + PostgreSQL requests, use Python, FastAPI, SQLAlchemy, Pydantic,
PostgreSQL connection settings, CORS, health checks, CRUD endpoints, and clear
environment variables. Derive table names, fields, relationships, route names,
and module names from the current frontend and user request. Do not put backend
logic inside React files.
When using Tailwind utilities, package.json must include tailwindcss, postcss,
and autoprefixer devDependencies, and src/index.css must include @tailwind base,
@tailwind components, and @tailwind utilities before any custom CSS.
Use React components and Tailwind classes only for frontend files that compile
inside a Vite app.
Enterprise AI-native generation rules:
- Never generate a monolithic src/App.jsx. src/App.jsx must be a thin
  composition shell that imports route views, layout shells, and components.
- Generate atomic, independently swappable components under src/components/*
  such as Hero, FeatureGrid, BentoInsights, Testimonials, PricingPanel,
  SupportPanel, ComplianceBanner, and EnterpriseComplianceFooter when relevant.
- Generate a component_manifest entry for every major component/page, including
  its file path, purpose, props, and required loading/error/hover/active/
  responsive states.
- Generate src/theme/tokens.js with enterprise design tokens for primary,
  secondary, accent, neutral dark/light colors, typography, spacing, container
  widths, radii, shadows, and motion. If the user provides brand guidelines,
  themes, structure, colors, typography, or layout rules, those inputs are the
  source of truth. Preserve them unless they violate accessibility, then adjust
  minimally and explain the adjustment in implementation_notes. If the user does
  not provide brand guidelines, dynamically infer the token system from the
  requested business, audience, industry, workflow, and emotional tone. Never
  use a static default theme, fixed palette, or one-size-fits-all structure.
  src/index.css must expose those tokens as CSS custom properties. Components
  must consume token variables or Tailwind theme mappings instead of scattering
  arbitrary hardcoded visual values.
- Translate the user brief and brand clues into a precise enterprise brand
  book: accessible color contrast, strict heading 1-6 and body scale, tracking
  constraints, and a layout philosophy chosen from the user request or inferred
  dynamically, such as High-Density Corporate, Spacious Creative Minimalist,
  Operational SaaS, or another domain-fit structure.
- Use modern AI-first UX patterns by default: adaptive dark/light theming,
  domain-appropriate glassmorphism, bento-grid composition, micro-interactions,
  and smooth CSS transitions. If Framer Motion is used, add framer-motion to
  package.json and keep animation lightweight.
- Write real vertical-specific copy with PAS or AIDA style structure. Do not
  use Lorem Ipsum, placeholder cards, or generic "feature one" filler.
- Every interactive component must include clear loading, error, hover,
  active/focus, and Mobile/Tablet/Desktop responsive states.
- Interactive completeness is mandatory: every button, CTA, and nav link must
  call a real function. Use react-router-dom useNavigate/Link/NavLink for route
  changes. Never assign onClick to a non-function value (this causes runtime
  TypeError in production builds).
- Marketing and landing pages must include multiple sections (hero, features,
  proof/metrics, CTA, footer) with accessible contrast — no invisible headings.
- Accessibility is mandatory: semantic HTML5 landmarks, aria-labels for
  icon-only or ambiguous controls, keyboard-reachable navigation, visible focus
  states, correct button/link semantics, and a sensible heading hierarchy.
- Performance is mandatory: lazy-load non-critical images, use loading="lazy"
  and decoding="async" when rendering images, avoid bloated dependencies, and
  keep Tailwind/CSS clean and purposeful.
- SEO is mandatory: index.html must include meta tag skeletons, Open Graph or
  Twitter card placeholders where useful, and the app must include JSON-LD
  structured data through src/seo/schema.js or an equivalent generated file.
When the website has distinct primary navigation destinations or functional
modules, create real route-backed page components under src/pages/* and use
React Router (including react-router-dom in package.json) or an equivalent
route-aware app shell. Header and sidebar links must navigate to those pages;
do not implement the entire product as hash-anchor sections on one long page.
Use a one-page layout only for an explicitly requested landing page or a
genuinely small brochure/portfolio brief.
Any generated .js/.jsx/.ts/.tsx file must include a React value import when it
uses JSX or React.* APIs; do not rely on React being available as a browser global.
When domain_research is included in the prepared backend context, treat it as LLM-authored guidance
for the user's request — not a fixed template. Infer layout, sections, styling,
and content from the user prompt plus domain_research when present; do not assume preset
pages or product catalogs unless the user or domain research explicitly requires them.

Backend execution pipeline context:
The Python backend owns and executes these stages in this exact order before
returning the final API response:
1. multi_agent_system
2. gemini_tool_calling_setup
3. google_adk_usage
4. orchestration_flow
5. agent_to_agent_communication
6. proactive_thinking

This website artifact call runs only after route_generation_action has selected
website_generation or website_update. Use this prepared backend context only to
align the artifact with the active agents, tools, and ADK mapping. Do not
restate the backend flow as top-level output.

Prepared backend context:
{pipeline_context}

Google ADK hybrid mapping available to the backend:
{adk_mapping}

{WEBSITE_ARTIFACT_OUTPUT_CONTRACT}
"""
