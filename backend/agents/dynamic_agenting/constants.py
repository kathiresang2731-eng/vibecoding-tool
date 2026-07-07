from __future__ import annotations

import re


MAX_DYNAMIC_AGENTS_PER_WORKFLOW = 4
ALLOWED_DYNAMIC_TOOLS = {"READ_PROJECT_FILES", "LOAD_PROJECT_MEMORY"}
FORBIDDEN_DYNAMIC_TOOLS = {
  "WRITE_PROJECT_FILES",
  "BUILD_PROJECT_PREVIEW",
  "BUILD_STAGED_PROJECT_PREVIEW",
  "RUN_PREVIEW_VISUAL_QA",
  "PERSIST_PROJECT_MEMORY",
  "SYNC_LOCAL_PROJECT",
}
# Permanent core/specialist agents already own these capabilities. Gemini may
# plan with them, but the runtime must not create user-scoped dynamic agents for
# them because that causes duplicated, low-quality, or unsafe reusable agents.
CORE_OWNED_CAPABILITIES = {
  "accessibility_review",
  "agent_registry",
  "architecture_design",
  "artifact_validation",
  "code_generation",
  "direct_file_write",
  "domain_research",
  "file_write",
  "frontend_development",
  "layout_plan",
  "memory_persist",
  "memory_persistence",
  "preview_build",
  "project_planning",
  "project_validation",
  "react_tailwind_development",
  "repair_if_needed",
  "requirement_analysis",
  "supervision",
  "task_decomposition",
  "ux_audit",
  "ux_review",
  "visual_qa",
  "workflow_planning",
}
MODEL_DYNAMIC_TASK_LIMIT = 4
SPECIALIST_SUMMARY_MAX_CHARS = 1_400
SPECIALIST_ITEM_MAX_CHARS = 640
SPECIALIST_PROMPT_BRIEF_MAX_CHARS = 12_000
SPECIALIST_PROMPT_PLAN_MAX_CHARS = 10_000
# Capabilities in this policy set are never creatable as dynamic user agents.
# Gemini can propose work, but Python enforces this boundary before creation,
# persistence, hydration, or reuse.
NON_CREATABLE_AGENT_CAPABILITIES = CORE_OWNED_CAPABILITIES | {
  "commit",
  "file_commit",
  "filesystem_write",
  "memory",
  "memory_agent",
  "preview",
  "repair",
  "routing",
  "supervisor",
  "validation",
}
PROJECT_SPECIFIC_AGENT_PROMPT_PATTERNS = (
  re.compile(r"\bcurrent\s+(?:brand|business|project|request|website)\b", re.IGNORECASE),
  re.compile(r"\bthis\s+specific\s+(?:brand|business|project|request|website)\b", re.IGNORECASE),
  re.compile(r"\bfocus\s+is\s+(?:the\s+)?['\"][^'\"]+['\"]", re.IGNORECASE),
  re.compile(r"\bfor\s+(?:the\s+)?['\"][^'\"]+['\"]", re.IGNORECASE),
  re.compile(r"\b(?:brand|business|project)\s+(?:name\s+)?is\s+['\"][^'\"]+['\"]", re.IGNORECASE),
)
# Python-guarded runtime actions are owned by built-in agents. If Gemini proposes
# a dynamic task for one of these phases, assignment falls back to the owner here
# instead of creating a new dynamic agent.
PYTHON_GUARDED_ACTION_OWNERS = {
  "RUN_PROMPT_ANALYST": "domain-research-agent",
  "RUN_PLANNER": "ux-layout-agent",
  "RUN_UX_REVIEW_AGENT": "ux-layout-agent",
  "RUN_ACCESSIBILITY_AGENT": "ux-layout-agent",
  "RUN_CODE_AGENT": "code-generator-agent",
  "VALIDATE_PROJECT_ARTIFACT": "validation-agent",
  "BUILD_STAGED_PROJECT_PREVIEW": "preview-qa-agent",
  "RUN_PREVIEW_VISUAL_QA": "preview-qa-agent",
  "RUN_REPAIR_AGENT": "repair-agent",
  "PERSIST_PROJECT_MEMORY": "memory-agent",
}
