from __future__ import annotations

WEBSITE_ARTIFACT_OUTPUT_CONTRACT = """
Return exactly this JSON shape for the project artifact generator. Do not add
extra top-level keys:
{
  "generated_website": {
    "title": "string",
    "headline": "string",
    "subheadline": "string",
    "primary_cta": "string",
    "secondary_cta": "string",
    "preview_html": "optional standalone HTML document string; empty string is allowed because the backend builds a real Vite preview from files",
    "theme": {
      "colors": {
        "primary": "hex color",
        "secondary": "hex color",
        "accent": "hex color",
        "background": "hex color",
        "text": "hex color"
      },
      "style_direction": "string"
    },
    "design_tokens": {
      "source": "user_brand_guidelines|llm_inferred_from_brief|hybrid_user_and_llm_inferred",
      "rationale": "short explanation of how brand/theme/structure tokens were chosen",
      "colors": {
        "primary": {"value": "user-provided or dynamically inferred hex color", "contrast_ratio": "string", "source": "user|inferred|adjusted_for_accessibility"},
        "secondary": {"value": "user-provided or dynamically inferred hex color", "contrast_ratio": "string", "source": "user|inferred|adjusted_for_accessibility"},
        "accent": {"value": "user-provided or dynamically inferred hex color", "contrast_ratio": "string", "source": "user|inferred|adjusted_for_accessibility"},
        "neutral_dark": {"value": "user-provided or dynamically inferred hex color", "contrast_ratio": "string", "source": "user|inferred|adjusted_for_accessibility"},
        "neutral_light": {"value": "user-provided or dynamically inferred hex color", "contrast_ratio": "string", "source": "user|inferred|adjusted_for_accessibility"}
      },
      "typography": {
        "font_pairing": "user-provided or dynamically inferred font pairing",
        "heading_scale": {"h1": "string", "h2": "string", "h3": "string", "h4": "string", "h5": "string", "h6": "string"},
        "body_scale": "string",
        "tracking": "string"
      },
      "layout": {
        "philosophy": "user-provided or dynamically inferred enterprise layout direction, such as High-Density Corporate, Spacious Creative Minimalist, Operational SaaS, or another domain-fit structure",
        "container_max_width": "string",
        "grid": "string",
        "spacing_scale": "string",
        "section_padding": "string"
      },
      "motion": {
        "duration": "string",
        "easing": "string",
        "interaction_pattern": "string"
      }
    },
    "component_manifest": [
      {
        "name": "PascalCase component name",
        "path": "src/components/ComponentName.jsx or src/pages/PageName.jsx",
        "purpose": "string",
        "props": ["string"],
        "states": ["loading", "error", "hover", "active", "responsive"]
      }
    ],
    "seo": {
      "meta_title": "string",
      "meta_description": "string",
      "canonical_path": "string",
      "json_ld_schema_type": "Organization|LocalBusiness|Product|SoftwareApplication|WebSite|other"
    },
    "compliance": {
      "accessibility": ["semantic HTML5, aria labels, keyboard and focus checks"],
      "performance": ["lazy images, optimized CSS/Tailwind, dependency checks"],
      "seo": ["meta tags, heading hierarchy, JSON-LD checks"]
    },
    "sections": [
      {
        "name": "string",
        "purpose": "string",
        "content": "string",
        "items": ["string"]
      }
    ],
    "files": [
      {
        "path": "allowed relative path string. For simple_code, use a safe root standalone source filename such as reverse_number.py, armstrong.rs, Palindrome.java, main.go, or fibonacci.py unless the user asks for folders. For React/frontend work include the required frontend entry/config files when a frontend is being generated. For backend/API/DB work, infer file names from the current frontend modules, requested domain entities, existing folder conventions, framework conventions, and project file index. Do not use hardcoded backend file names from the prompt contract. Allowed paths are safe root standalone code files, src/*, public/*, backend/*, api/*, app/*, server/*, database/*, db/*, migrations/*, alembic/*, scripts/*, tests/*, supported root config files, package.json, requirements.txt, pyproject.toml, Dockerfile, and docker-compose.yml",
        "purpose": "string",
        "code": "string"
      }
    ]
  },
  "implementation_notes": {
    "assumptions": ["string"],
    "missing_information": ["string"],
    "predicted_risks": ["string"],
    "self_checks": ["string"],
    "recommended_next_actions": ["string"]
  }
}
"""

SIMPLE_CODE_ARTIFACT_OUTPUT_CONTRACT = """
Return exactly this compact JSON shape. Do not add extra top-level keys:
{
  "generated_website": {
    "files": [
      {
        "path": "safe root standalone source filename, for example PrimeNumber.java, prime_number.py, prime_number.rs, main.go, or palindrome.js",
        "purpose": "short purpose string",
        "code": "complete runnable source code"
      }
    ]
  },
  "implementation_notes": {
    "recommended_next_actions": ["one command showing how to run the generated file"],
    "self_checks": ["short check that the file matches the requested language and task"]
  }
}
"""

CONVERSATION_RESPONSE_CONTRACT = """
Return exactly this JSON shape for the selected conversation tool. Do not add
extra keys:
{
  "type": "greeting|needs_more_detail|project_info",
  "message": "string",
  "next_prompt_guidance": ["string"]
}
"""

DOMAIN_RESEARCH_RESPONSE_CONTRACT = """
Return exactly this JSON shape for website domain research. Do not add extra
keys:
{
  "status": "applied|generic",
  "source": "gemini_google_search",
  "domain": "short snake_case domain name",
  "display_name": "human-readable website category",
  "confidence": "low|medium|high",
  "reason": "string",
  "web_search_query": "string",
  "assumptions": ["string"],
  "audience": "string",
  "goal": "string",
  "style": "string",
  "required_sections": ["string"],
  "interactions": ["string"],
  "content_requirements": ["string"],
  "sample_products": [
    {
      "name": "string",
      "category": "string",
      "price": "string",
      "rating": "string",
      "tag": "string"
    }
  ],
  "sources": [
    {
      "title": "string",
      "url": "string"
    }
  ]
}
"""

DYNAMIC_TASK_DECOMPOSITION_CONTRACT = """
Return exactly this JSON shape for dynamic task decomposition. Do not add extra
keys:
{
  "domain": "short snake_case domain",
  "scope": "small|medium|large",
  "tasks": [
    {
      "id": "short snake_case task id",
      "name": "string",
      "required_capability": "short snake_case capability",
      "description": "string",
      "input_schema": {"type": "object"},
      "output_schema": {"type": "object"},
      "dependencies": ["task_id"],
      "risk_level": "low|medium|high",
      "runtime_action": "RUN_PROMPT_ANALYST|RUN_PLANNER|RUN_DYNAMIC_SPECIALISTS|RUN_UX_REVIEW_AGENT|RUN_ACCESSIBILITY_AGENT|RUN_CODE_AGENT|VALIDATE_PROJECT_ARTIFACT|BUILD_STAGED_PROJECT_PREVIEW|RUN_PREVIEW_VISUAL_QA|RUN_REPAIR_AGENT|PERSIST_PROJECT_MEMORY",
      "optional": false
    }
  ]
}
"""

DYNAMIC_AGENT_DEFINITION_CONTRACT = """
Return exactly this JSON shape for a dynamically created specialist agent. Do
not add extra keys:
{
  "id": "short snake_case agent id",
  "name": "string",
  "role": "string",
  "system_prompt": "string",
  "capabilities": ["short snake_case capability"],
  "supported_domains": ["short snake_case domain"]
}
"""

DYNAMIC_WORKFLOW_PLAN_CONTRACT = """
Return exactly this JSON shape for dynamic workflow planning. Do not add extra
keys:
{
  "parallel_groups": [["task_id"]],
  "completion_proof": [
    "artifact_valid",
    "staged_preview_ready",
    "visual_qa_passed",
    "files_committed",
    "memory_prepared"
  ],
  "reason": "string"
}
"""

ROUTING_RESPONSE_CONTRACT = """
Return exactly this JSON shape for route_generation_action. Do not add extra
keys:
{
  "intent": "greeting|needs_more_detail|project_info|simple_code|website_generation|website_update",
  "next_action": "respond_and_collect_website_brief|request_website_details|summarize_current_project|write_standalone_code_file|generate_website|update_website",
  "next_tool": "handle_greeting|request_website_details|summarize_current_project|generate_simple_code_file|analyze_prompt|analyze_update_request",
  "reason": "string under 220 characters — no quotes, newlines, or trailing punctuation outside JSON"
}
"""

UPDATE_ANALYSIS_CONTRACT = """
Return exactly this JSON shape for update analysis. Do not add extra keys:
{
  "update_mode": "targeted_patch|bug_fix|feature_patch|full_regeneration|needs_clarification",
  "request_kind": "brand_name_update|document_title_update|cta_text_update|theme_color_update|style_reference_update|interaction_wiring_update|pagination_page_size_update|bug_fix|feature_patch|full_regeneration|other",
  "execution_strategy": "deterministic_patch|scoped_model_patch|full_dynamic_workflow|clarify",
  "scope": "small|medium|large",
  "summary": "short description of the requested change",
  "target_symbols": ["existing code symbol, text, component, or feature"],
  "feature_plan": {
    "name": "PascalCase semantic feature/component name, empty unless feature_patch",
    "type": "component|page|panel|modal|drawer|helper|service|other",
    "items": ["requested tabs, sections, fields, or subfeatures"],
    "interaction": "short description of how the user opens or uses the feature"
  },
  "candidate_files": ["existing project path that may need modification"],
  "target_files": ["existing paths to edit when user wants one page/component to match another"],
  "reference_files": ["existing paths to read for style/color reference only — do not edit unless also in target_files"],
  "style_reference_summary": "when request_kind is style_reference_update, describe target vs reference styling intent",
  "interaction_summary": "when request_kind is interaction_wiring_update or bug_fix for broken buttons/clicks/handlers, describe component, trigger, and expected behavior",
  "interaction": {
    "component": "UI element, page, or feature name (e.g. cart button, navbar)",
    "trigger": "user action such as click, submit, or navigate",
    "expected": "expected behavior after the action"
  },
  "candidate_new_files": ["optional new project path for bounded feature components/helpers only"],
  "new_file_requirements": {
    "needed": false,
    "reason": "why existing files are enough or why new files are required",
    "planned_files": [
      {
        "path": "approved new source/helper path",
        "kind": "component|page|helper|service|style|data|backend|api|router|model|schema|database|migration|seed|test|config",
        "reason": "why this file should be separate instead of editing only existing files",
        "integration_file": "existing candidate file that will import/render this file",
        "import_name": "component/function/export name expected in the new file",
        "import_path_from_integration": "relative import path from integration_file"
      }
    ],
    "verification": {
      "existing_files_checked": ["existing paths used to decide placement/import"],
      "import_or_render_required": true
    }
  },
  "scoped_update_tasks": [
    {
      "id": "short_task_id",
      "summary": "one small update step",
      "prompt": "specific sub-request for this step",
      "candidate_files": ["existing project path for this step"],
      "candidate_new_files": ["optional approved new path for this step"],
      "target_symbols": ["symbols/text/features for this step"]
    }
  ],
  "required_agents": ["new_file_requirement_agent|targeted_update_agent|scoped_update_agent|debug_patch_agent|feature_patch_agent|full_dynamic_workflow"],
  "targeted_patch": {
    "kind": "brand_name_update|document_title_update|cta_text_update|theme_color_update|pagination_page_size_update|other",
    "old_value": "optional exact old visible text or metadata value",
    "new_value": "optional exact new visible text or metadata value",
    "page_size": "optional integer for pagination page size",
    "colors": ["optional color names such as red, yellow"],
    "primary_hex": "optional hex color",
    "secondary_hex": "optional hex color",
    "background_hex": "optional hex color",
    "target_description": "short description of the intended existing-code target"
  },
  "preserve_rules": ["specific existing behavior or file content that must remain unchanged"],
  "allow_full_regeneration": false,
  "clarification_question": "empty unless update_mode is needs_clarification",
  "reason": "string"
}
"""

SCOPED_UPDATE_PATCH_CONTRACT = """
Return exactly this JSON shape for a scoped website update. Do not add extra
keys, markdown, comments, or prose:
{
  "status": "completed|needs_scope_expansion|needs_clarification|blocked",
  "summary": "short string under 220 characters",
  "changed_files": [
      {
        "path": "one of the explicitly allowed existing paths or approved new feature paths",
        "code": "complete updated file contents"
      }
    ],
  "edits": [
    {
      "path": "one of the explicitly allowed existing project paths",
      "search_replace": "<<<<<<< SEARCH\nexact existing source snippet to replace\n=======\nreplacement source snippet\n>>>>>>> REPLACE",
      "search": "exact existing source snippet to replace",
      "replace": "replacement source snippet",
      "expected_replacements": 1
    }
  ],
  "requested_files": ["existing project path required for this subtask; empty for every other status"],
  "clarification_question": "empty unless status is needs_clarification"
}

Strict output rules:
- Return one JSON object only. The first character must be { and the last
  character must be }.
- status "completed" is valid only when edits or changed_files contains at
  least one item. Never return completed with both arrays empty.
- If an existing project file is required but is not in the supplied allowed
  file contents, return status "needs_scope_expansion", list the exact existing
  path in requested_files, and do not ask the user for permission.
- Use needs_clarification only when the user's intended behavior or target is
  genuinely ambiguous. Missing source-file access is not user ambiguity.
- status "blocked" must include a concrete clarification_question that explains
  what exact target is missing. Do not use blocked as a generic no-patch answer
  when approved files are available.
- Prefer edits for small changes. Do not return complete file code unless an
  exact edit is unsafe.
- For every existing-file edit, populate edit.search_replace with an explicit
  SEARCH/REPLACE block. The SEARCH side must be copied verbatim from the
  current candidate file content. Do not paraphrase, reformat, invent old code,
  use line numbers, or emit native partial-update artifacts. Use 3-15 lines
  when possible.
- Legacy edit.search and edit.replace fields may also be included, but
  search_replace is the preferred source of truth for backend merging.
- For click handlers, state changes, dropdowns, filters, pagination, modals,
  and other UI interactions, patch only the relevant state, handler, and render
  blocks. Do not rewrite the whole component.
- If using changed_files, every item must contain path and complete code.
- Only use changed_files for a new file when update_analysis.candidate_new_files
  explicitly contains that exact path. Edits are never allowed for new files.
- Do not return generated_website, files, implementation_notes, changedFiles,
  patch, diff, markdown fences, or nested wrapper objects.
- Never return a fallback/static website for update failures. If the exact
  scoped edit cannot be represented safely, return status "blocked" with a
  concise clarification_question.
"""
