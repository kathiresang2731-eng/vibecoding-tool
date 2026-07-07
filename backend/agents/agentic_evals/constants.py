from __future__ import annotations


ARTIFACT_INTENTS = {"website_generation", "website_update"}
CONVERSATION_INTENTS = {
  "greeting",
  "question",
  "general_query",
  "web_search",
  "project_info",
  "needs_more_detail",
  "needs_confirmation",
}
VALID_INTENTS = ARTIFACT_INTENTS | CONVERSATION_INTENTS

REQUIRED_ARTIFACT_RUNTIME_TOOLS = (
  "READ_PROJECT_FILES",
  "LOAD_PROJECT_MEMORY",
  "VALIDATE_PROJECT_ARTIFACT",
  "BUILD_STAGED_PROJECT_PREVIEW",
  "RUN_PREVIEW_VISUAL_QA",
  "WRITE_PROJECT_FILES",
  "PERSIST_PROJECT_MEMORY",
)

REQUIRED_FAILURE_FIELDS = ("status", "category", "code", "error", "user_message", "detail")
