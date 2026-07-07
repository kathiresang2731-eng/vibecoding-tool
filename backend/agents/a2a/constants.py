from __future__ import annotations


A2A_PROTOCOL_VERSION = "worktual-a2a-v1"
CANONICAL_HANDOFF_REQUIRED_FIELDS = (
  "sender",
  "receiver",
  "task",
  "input",
  "output",
  "confidence",
  "next_action",
)

A2A_CHANNEL_POLICY = {
  "routing": "Intent routing and branch selection handoffs.",
  "conversation": "Conversation-only replies that must not create files.",
  "analysis": "Website brief extraction and requirement analysis.",
  "planning": "Section order, conversion path, and implementation planning.",
  "ux_review": "UX review handoffs for workflow, conversion, and responsive layout concerns.",
  "accessibility": "Accessibility review handoffs for contrast, semantics, keyboard flow, and mobile fit.",
  "artifact": "Gemini-generated code artifact packaging and file handoff.",
  "validation": "Artifact contract validation and build-readiness checks.",
  "preview": "Preview build execution and build log handoffs.",
  "visual_qa": "Backend preview integrity QA handoffs before committing generated files.",
  "repair": "Gemini repair attempts and rollback handoffs after validation or preview failures.",
  "memory": "Project memory summaries for future turns.",
}

ACTION_CHANNELS = {
  "route_user_turn": "routing",
  "respond_without_file_generation": "conversation",
  "choose_next_agent": "planning",
  "read_project_files": "memory",
  "load_project_memory": "memory",
  "extract_website_brief": "analysis",
  "extract_update_brief": "analysis",
  "create_structured_brief": "analysis",
  "plan_sections_and_conversion_path": "planning",
  "create_website_plan": "planning",
  "review_ux_plan": "ux_review",
  "review_accessibility_plan": "accessibility",
  "package_generated_project_files": "artifact",
  "generate_project_artifact": "artifact",
  "generate_update_artifact": "artifact",
  "repair_project_artifact": "repair",
  "write_project_files": "artifact",
  "commit_staged_project_files": "artifact",
  "validate_generated_artifact_contract": "validation",
  "validate_code_agent_output": "validation",
  "validate_project_artifact": "validation",
  "validate_preview_build": "validation",
  "build_preview_candidate": "preview",
  "build_staged_project_preview": "preview",
  "run_preview_visual_qa": "visual_qa",
  "build_project_preview": "preview",
  "restore_previous_project_files": "repair",
  "prepare_conversation_memory": "memory",
  "prepare_generation_memory": "memory",
  "persist_project_memory": "memory",
}
